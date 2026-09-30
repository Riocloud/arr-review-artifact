"""MiniMax live runner for SAGE-Law experiments.

This module uses MiniMax's OpenAI-compatible chat-completions endpoint. It is a
generation and artifact-contract runner; Harvey LAB judging is handled by the
separate benchmark harness.
"""

from __future__ import annotations

import json
import os
import time
import traceback
import urllib.error
import urllib.request
import http.client
import multiprocessing as mp
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .authority import WRAPPERS
from .constraints import apply_release_adapter, evaluate_constraints
from .deliverables import combined_markdown, parse_deliverables
from .documents import load_task_context
from .dry_run import safe_task_path, write_trace
from .harvey import write_json
from .models import canonical_model_names

DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MINIMAX_MODELS = ("MiniMax-M2.7-highspeed", "MiniMax-M3")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 1800
DEFAULT_PROVIDER_RETRY_ATTEMPTS = 8
DEFAULT_PROVIDER_RETRY_SLEEP_SECONDS = 5.0
DEFAULT_PROVIDER_RETRY_MAX_SLEEP_SECONDS = 180.0
DEFAULT_PROVIDER_RATE_LIMIT_SLEEP_SECONDS = 30.0


def worker_context() -> mp.context.BaseContext:
    """Use fork where available so live-run patches and env are inherited cheaply."""

    try:
        return mp.get_context("fork")
    except ValueError:
        return mp.get_context()


def minimax_chat_url() -> str:
    base_url = provider_base_url().rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def provider_name() -> str:
    override = os.environ.get("SAGE_LAW_PROVIDER")
    if override:
        provider = override.strip().lower().replace("_", "-")
        if provider in {"openai-compatible", "openai-compatible-api", "aggregator", "generic", "custom"}:
            return "openai"
        return provider
    if os.environ.get("MINIMAX_BASE_URL"):
        return "minimax"
    if os.environ.get("DEEPSEEK_BASE_URL"):
        return "deepseek"
    if os.environ.get("OPENAI_BASE_URL") and not os.environ.get("MINIMAX_BASE_URL"):
        return "openai"
    has_minimax = bool(os.environ.get("MINIMAX_API_KEY"))
    has_deepseek = bool(os.environ.get("DEEPSEEK_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if has_minimax and not has_deepseek:
        return "minimax"
    if has_deepseek and not has_minimax:
        return "deepseek"
    if has_openai and not has_minimax and not has_deepseek:
        return "openai"
    return "minimax"


def provider_base_url() -> str:
    provider = provider_name()
    if provider == "deepseek":
        return os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
    if provider == "openai":
        return os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
    return (
        os.environ.get("MINIMAX_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_MINIMAX_BASE_URL
    )


def provider_api_key() -> str | None:
    provider = provider_name()
    if provider == "deepseek":
        return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    return os.environ.get("MINIMAX_API_KEY") or os.environ.get("OPENAI_API_KEY")


def provider_uses_reasoning_split() -> bool:
    override = os.environ.get("SAGE_LAW_REASONING_SPLIT")
    if override is not None:
        return override.strip().lower() not in {"0", "false", "no", "off"}
    if provider_name() == "minimax":
        return True
    if os.environ.get("SAGE_LAW_PROVIDER"):
        return False
    base_url = provider_base_url().lower()
    return "minimax" in base_url or "minimaxi" in base_url


def provider_is_deepseek() -> bool:
    if provider_name() == "deepseek":
        return True
    if os.environ.get("SAGE_LAW_PROVIDER"):
        return False
    return "deepseek" in provider_base_url().lower()


def provider_uses_streaming() -> bool:
    override = os.environ.get("SAGE_LAW_STREAM")
    if override is not None:
        return override.strip().lower() not in {"0", "false", "no", "off"}
    return provider_name() == "openai"


def provider_retry_attempts() -> int:
    return int(os.environ.get("SAGE_LAW_PROVIDER_RETRY_ATTEMPTS", DEFAULT_PROVIDER_RETRY_ATTEMPTS))


def provider_retry_sleep_seconds() -> float:
    return float(os.environ.get("SAGE_LAW_PROVIDER_RETRY_SLEEP_SECONDS", DEFAULT_PROVIDER_RETRY_SLEEP_SECONDS))


def provider_retry_max_sleep_seconds() -> float:
    return float(os.environ.get("SAGE_LAW_PROVIDER_RETRY_MAX_SLEEP_SECONDS", DEFAULT_PROVIDER_RETRY_MAX_SLEEP_SECONDS))


def provider_rate_limit_sleep_seconds() -> float:
    return float(
        os.environ.get(
            "SAGE_LAW_PROVIDER_RATE_LIMIT_SLEEP_SECONDS",
            DEFAULT_PROVIDER_RATE_LIMIT_SLEEP_SECONDS,
        )
    )


def provider_retry_delay(attempt: int, status_code: int | None = None) -> float:
    base = provider_retry_sleep_seconds()
    cap = provider_retry_max_sleep_seconds()
    if status_code == 429:
        floor = provider_rate_limit_sleep_seconds()
        return min(max(cap, floor), max(floor, base * (2 ** (attempt - 1))))
    return min(cap, base * attempt)


def provider_body_error(body: dict[str, Any]) -> str | None:
    """Return provider-level errors encoded inside HTTP-200 JSON bodies."""

    base_resp = body.get("base_resp")
    if isinstance(base_resp, dict):
        status_code = base_resp.get("status_code")
        if status_code not in (None, 0, "0"):
            status_msg = base_resp.get("status_msg") or base_resp.get("message") or ""
            return f"provider_body_error status_code={status_code}: {status_msg}"
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type") or "unknown"
        message = error.get("message") or error
        return f"provider_body_error code={code}: {message}"
    if isinstance(error, str) and error:
        return f"provider_body_error: {error}"
    return None


def stream_options_enabled() -> bool:
    return os.environ.get("SAGE_LAW_STREAM_INCLUDE_USAGE", "").strip().lower() in {"1", "true", "yes", "on"}


def read_streaming_chat_response(response: Any) -> dict[str, Any]:
    """Read an OpenAI-compatible SSE chat completion stream into a normal body."""

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish = "missing_finish_reason"
    usage: dict[str, Any] = {}
    body_meta: dict[str, Any] = {}
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        embedded_error = provider_body_error(chunk)
        if embedded_error:
            raise RuntimeError(embedded_error)
        for key in ("id", "object", "created", "model", "system_fingerprint", "service_tier"):
            if key in chunk and key not in body_meta:
                body_meta[key] = chunk[key]
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                finish = str(choice["finish_reason"])
            delta = choice.get("delta") or choice.get("message") or {}
            if isinstance(delta, dict):
                content = delta.get("content")
                if content:
                    content_parts.append(str(content))
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    reasoning_parts.append(str(reasoning))
    message = {"role": "assistant", "content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    return {
        **body_meta,
        "choices": [{"finish_reason": finish, "index": 0, "message": message}],
        "usage": usage,
    }


def build_prompt(
    task: dict[str, Any],
    wrapper: str,
    task_context: dict[str, Any] | None = None,
    required_filenames: list[str] | None = None,
) -> list[dict[str, str]]:
    full_task = task_context["task"] if task_context else {}
    instructions = full_task.get("instructions") or ""
    activation = (task_context or {}).get("activation") or {"mode": "manifest_only"}
    deliverables_obj = full_task.get("deliverables") or {filename: filename for filename in task["deliverables"]}
    all_expected_filenames = list(deliverables_obj.values() if isinstance(deliverables_obj, dict) else deliverables_obj)
    expected_filenames = list(required_filenames or all_expected_filenames)
    doc_sections: list[str] = []
    for document in (task_context or {}).get("documents", []):
        doc_sections.append(
            "\n".join(
                [
                    f"### {document['relative_path']}",
                    document["text"],
                    "[truncated]" if document.get("truncated") else "",
                ]
            ).strip()
        )
    documents_text = "\n\n".join(doc_sections) if doc_sections else "(No document text supplied.)"
    criteria_hint = (
        f"The Harvey LAB task has {task['criteria_count']} atomic rubric criteria. "
        "Do not invent citations or jurisdiction facts not present in the task summary."
    )
    wrapper_hint = {
        "raw_agent": "Produce a concise legal-work-product draft.",
        "rag_agent": "Produce a concise draft and explicitly mark where document support would be required.",
        "cbea_lcv_legal": "List bounded commitments first, then draft only commitments you can support from the prompt.",
        "sage_law": (
            "Treat text as a proposal, not authority. Return coverage debt for unsupported "
            "source, jurisdiction, authority-status, issue, recommendation, or release claims."
        ),
    }[wrapper]
    if required_filenames:
        output_contract = [
            "Produce the complete Harvey LAB deliverable for exactly the required filename below.",
            "Begin immediately with the deliverable content on the first line; do not deliberate before writing.",
            "Return only the file content in Markdown/plain text. Do not wrap it in JSON.",
            "Do not include a Markdown code fence, explanatory preface, or hidden reasoning.",
            f"Required filename: {', '.join(expected_filenames)}",
            "The content must be complete enough for legal-work-product review against the task rubric.",
        ]
        system_output_rule = (
            "Return only the requested benchmark deliverable content. "
            "Begin immediately with the deliverable content. "
            "Do not wrap the response in JSON or a Markdown code fence. "
        )
    else:
        output_contract = [
            "Produce complete Harvey LAB deliverables. Return only valid JSON, with no Markdown fence and no extra prose.",
            "Start the response with the literal characters {\"deliverables\". Do not write <think> blocks.",
            "The JSON schema is:",
            '{"deliverables": {"<filename>": "<complete deliverable content in Markdown/plain text>"}}',
            f"Required filenames: {', '.join(expected_filenames)}",
            "The content for each filename must be complete enough for legal-work-product review against the task rubric.",
            "Do not include chain-of-thought or hidden reasoning. Do not omit a required filename.",
        ]
        system_output_rule = (
            "Return complete benchmark deliverables as valid JSON only. "
            "Do not output <think> blocks or hidden reasoning. "
        )
    user = "\n".join(
        [
            f"Task title: {task['title']}",
            f"Task id: {task['task_id']}",
            f"Practice area: {task['practice_area']}",
            f"Work type: {task['work_type']}",
            f"Deliverables: {', '.join(task['deliverables'])}",
            f"Failure-mode labels for this experiment: {', '.join(task['failure_modes'])}",
            f"Context lane: {activation.get('mode', 'manifest_only')}",
            (
                "Context handling: raw_full means ordered long-context document stuffing; "
                "activated means bounded evidence activation with selected source chunks."
            ),
            "",
            "## Task Instructions",
            instructions or "(Instructions unavailable in manifest-only smoke mode.)",
            "",
            "## Source Documents",
            documents_text,
            "",
            criteria_hint,
            "",
            wrapper_hint,
            "",
            (
                "Split fallback: generate only the required filename below, while preserving the full task context."
                if required_filenames
                else ""
            ),
            "",
            "## Output Contract",
            *output_contract,
        ]
    )
    return [
        {
            "role": "system",
            "content": (
                "You are supporting a legal-AI benchmark smoke test. "
                "Do not provide legal advice. Do not claim legal correctness. "
                + system_output_rule
            ),
        },
        {"role": "user", "content": user},
    ]


def call_minimax(
    model: str,
    messages: list[dict[str, str]],
    max_completion_tokens: int,
    temperature: float,
    request_timeout: int,
    response_format_json: bool = True,
    response_format_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_key = provider_api_key()
    if not api_key:
        raise SystemExit("Set MINIMAX_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY before running live smoke.")
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
        "temperature": temperature,
    }
    if provider_uses_reasoning_split():
        payload["reasoning_split"] = True
    if response_format_override is not None:
        payload["response_format"] = response_format_override
    elif provider_is_deepseek() and response_format_json:
        payload["response_format"] = {"type": "json_object"}
    if provider_is_deepseek():
        thinking = os.environ.get("DEEPSEEK_THINKING", "enabled").strip().lower()
        if thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking}
        if thinking != "disabled":
            payload["reasoning_effort"] = os.environ.get("DEEPSEEK_REASONING_EFFORT", "high")
    stream_response = provider_uses_streaming()
    if stream_response:
        payload["stream"] = True
        if stream_options_enabled():
            payload["stream_options"] = {"include_usage": True}
    request = urllib.request.Request(
        minimax_chat_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.time()
    last_error: BaseException | None = None
    retry_attempts = provider_retry_attempts()
    for attempt in range(1, retry_attempts + 1):
        status_code: int | None = None
        try:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                if stream_response:
                    body = read_streaming_chat_response(response)
                else:
                    body = json.loads(response.read().decode("utf-8"))
                status = response.status
            embedded_error = provider_body_error(body)
            if embedded_error:
                raise RuntimeError(embedded_error)
            break
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                raise SystemExit(f"MiniMax HTTP {exc.code}: {error_body}") from exc
            last_error = SystemExit(f"MiniMax HTTP {exc.code}: {error_body}")
        except (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            ConnectionResetError,
            TimeoutError,
            RuntimeError,
        ) as exc:
            last_error = exc
        if attempt < retry_attempts:
            time.sleep(provider_retry_delay(attempt, status_code))
    else:
        raise SystemExit(str(last_error) if last_error else "MiniMax request failed")
    return {
        "status": status,
        "elapsed_seconds": round(time.time() - started, 3),
        "response": body,
    }


def extract_content(response_body: dict[str, Any]) -> str:
    choices = response_body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def finish_reason(response: dict[str, Any]) -> str:
    choices = response.get("response", {}).get("choices") or []
    if not choices:
        return "missing_choice"
    return str(choices[0].get("finish_reason") or "missing_finish_reason")


def aggregate_usage(responses: list[dict[str, Any]]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for response in responses:
        response_usage = response.get("response", {}).get("usage", {})
        if not isinstance(response_usage, dict):
            continue
        for key, value in response_usage.items():
            if isinstance(value, int):
                usage[key] = usage.get(key, 0) + value
    return usage


def split_fallback_response(responses: list[dict[str, Any]], finish: str = "stop") -> dict[str, Any]:
    return {
        "status": 200,
        "elapsed_seconds": round(sum(float(response.get("elapsed_seconds") or 0.0) for response in responses), 3),
        "split_fallback": True,
        "split_response_count": len(responses),
        "response": {
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {"content": "[split fallback assembled from per-deliverable responses]"},
                }
            ],
            "usage": aggregate_usage(responses),
        },
    }


def artifact_is_complete(run_dir: Path, wrapper: str, expected_filenames: list[str]) -> bool:
    if (run_dir / "run_error.json").exists():
        return False
    required_files = [
        run_dir / "provider_response.json",
        run_dir / "gate_decision.json",
        run_dir / "final_work_product.md",
    ]
    if not all(path.exists() and path.stat().st_size > 0 for path in required_files):
        return False
    try:
        provider_response = json.loads((run_dir / "provider_response.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if finish_reason(provider_response) == "length":
        return False
    status_path = run_dir / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if deliverable_error_is_retryable(status.get("deliverable_error")):
            return False
    output_dir = run_dir / "output"
    if not all((output_dir / filename).exists() for filename in expected_filenames):
        return False
    if wrapper == "sage_law":
        review_output_dir = run_dir / "review_output"
        if not all((review_output_dir / filename).exists() for filename in expected_filenames):
            return False
    return True


def prior_response_needs_split_fallback(run_dir: Path) -> dict[str, Any] | None:
    """Return prior response metadata when resume should go straight to split mode."""

    response_path = run_dir / "provider_response.json"
    if not response_path.exists():
        return None
    try:
        response = json.loads(response_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    prior_finish_reason = finish_reason(response)
    prior_deliverable_error = None
    status_path = run_dir / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text())
        except (OSError, json.JSONDecodeError):
            status = {}
        prior_deliverable_error = status.get("deliverable_error")
    if prior_finish_reason == "length" or deliverable_error_is_retryable(prior_deliverable_error):
        return {
            "finish_reason": prior_finish_reason,
            "deliverable_error": prior_deliverable_error,
        }
    return None


def write_run_status(
    run_dir: Path,
    status: str,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    context_mode: str,
    response: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
    deliverable_error: str | None = None,
    task_context: dict[str, Any] | None = None,
) -> None:
    body: dict[str, Any] = {
        "schema_version": "sage-law.run-status.v1",
        "status": status,
        "task_id": task["task_id"],
        "model": model,
        "wrapper": wrapper,
        "context_mode": context_mode,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "finish_reason": finish_reason(response) if response else None,
        "deliverable_error": deliverable_error,
        "error": error,
    }
    if response:
        usage = response.get("response", {}).get("usage", {})
        body["provider_elapsed_seconds"] = response.get("elapsed_seconds")
        body["usage"] = usage
    if task_context:
        body["context_chars"] = task_context.get("context_chars")
        body["document_count_in_context"] = task_context.get("document_count_in_context")
        body["activation"] = task_context.get("activation")
    write_json(run_dir / "status.json", body)
    if error is not None:
        write_json(run_dir / "run_error.json", error)
    elif (run_dir / "run_error.json").exists():
        (run_dir / "run_error.json").unlink()


def log_progress(message: str) -> None:
    print(
        json.dumps(
            {
                "event_time": datetime.now(timezone.utc).isoformat(),
                **json.loads(message),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def progress_event(event: str, **kwargs: Any) -> str:
    return json.dumps({"event": event, **kwargs}, ensure_ascii=False)


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def leaf_lock_is_active(run_dir: Path, stale_seconds: int | None = None) -> bool:
    stale_seconds = stale_seconds or int(os.environ.get("SAGE_LAW_LEAF_LOCK_STALE_SECONDS", "43200"))
    lock_dir = run_dir / ".leaf.lock"
    if not lock_dir.exists():
        return False
    try:
        owner_body = json.loads((lock_dir / "owner.json").read_text())
        pid = int(owner_body.get("pid", 0))
        if pid > 0:
            return process_is_alive(pid)
    except Exception:
        pass
    try:
        return time.time() - lock_dir.stat().st_mtime <= stale_seconds
    except OSError:
        return False


def acquire_leaf_lock(run_dir: Path, stale_seconds: int | None = None) -> bool:
    """Acquire an atomic cross-process lock for one leaf output directory."""

    stale_seconds = stale_seconds or int(os.environ.get("SAGE_LAW_LEAF_LOCK_STALE_SECONDS", "43200"))
    lock_dir = run_dir / ".leaf.lock"
    owner = {
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        lock_dir.mkdir()
        write_json(lock_dir / "owner.json", owner)
        return True
    except FileExistsError:
        pass

    stale = False
    try:
        owner_body = json.loads((lock_dir / "owner.json").read_text())
        pid = int(owner_body.get("pid", 0))
        stale = pid <= 0 or not process_is_alive(pid)
    except Exception:
        stale = True
    try:
        stale = stale or (time.time() - lock_dir.stat().st_mtime > stale_seconds)
    except OSError:
        stale = True
    if not stale:
        return False

    try:
        for child in lock_dir.iterdir():
            child.unlink()
        lock_dir.rmdir()
        lock_dir.mkdir()
        write_json(lock_dir / "owner.json", owner)
        return True
    except (FileExistsError, OSError):
        return False


def release_leaf_lock(run_dir: Path) -> None:
    lock_dir = run_dir / ".leaf.lock"
    owner_path = lock_dir / "owner.json"
    try:
        owner = json.loads(owner_path.read_text())
        if int(owner.get("pid", 0)) != os.getpid():
            return
        owner_path.unlink()
        lock_dir.rmdir()
    except FileNotFoundError:
        return
    except OSError:
        return


def error_kind(error: dict[str, str] | None) -> str | None:
    if error is None:
        return None
    message = error.get("error", "")
    if "finish_reason=length" in message:
        return "length"
    if "deliverable_json_parse_failed" in message or "missing_deliverables" in message:
        return "parse_or_contract"
    if "timed out" in message or "timeout" in message.lower():
        return "timeout"
    network_markers = (
        "HTTP",
        "urlopen",
        "Connection reset",
        "connection reset",
        "Remote end closed connection",
        "Connection aborted",
        "temporarily unavailable",
        "provider_body_error",
    )
    if any(marker in message for marker in network_markers):
        return "provider_or_network"
    return "other"


def error_type_counts(errors: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        kind = error_kind(error) or "none"
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def deliverable_error_is_retryable(deliverable_error: str | None) -> bool:
    """Return whether a deliverable contract error should force a rerun."""

    if not deliverable_error:
        return False
    if deliverable_error.startswith("deliverable_json_parse_failed"):
        return True
    if deliverable_error.startswith("missing_deliverables"):
        return True
    if deliverable_error.startswith("split_fallback_failed"):
        return True
    return False


def section_fallback_parts() -> int:
    return max(2, int(os.environ.get("SAGE_LAW_SECTION_FALLBACK_PARTS", "4")))


def section_fallback_tokens(max_completion_tokens: int) -> int:
    configured = os.environ.get("SAGE_LAW_SECTION_FALLBACK_TOKENS")
    if configured:
        return max(1024, int(configured))
    return max(4096, min(max_completion_tokens, 8192))


def section_subpart_count() -> int:
    return max(2, int(os.environ.get("SAGE_LAW_SECTION_SUBPARTS", "3")))


def section_subpart_tokens(max_completion_tokens: int) -> int:
    configured = os.environ.get("SAGE_LAW_SECTION_SUBPART_TOKENS")
    if configured:
        return max(1024, int(configured))
    return max(2048, min(max_completion_tokens, 4096))


def section_guidance(part_index: int, part_count: int) -> str:
    guidance = {
        1: "front matter, task framing, relevant facts, definitions, assumptions, and document/source background",
        2: "main substantive analysis, clauses, legal/commercial issues, evidence mapping, and governing constraints",
        3: "detailed issue coverage, tables, risk ratings, drafting provisions, support analysis, and open questions",
        4: "recommendations or next steps if requested, reservations, appendices, schedules, and closing material",
    }
    if part_index in guidance:
        return guidance[part_index]
    if part_index == part_count:
        return "remaining appendices, tables, reservations, QA checks, and closing material"
    return "the next coherent middle section of the deliverable without repeating prior parts"


def build_section_prompt(
    task: dict[str, Any],
    wrapper: str,
    task_context: dict[str, Any] | None,
    filename: str,
    part_index: int,
    part_count: int,
) -> list[dict[str, str]]:
    messages = build_prompt(task, wrapper, task_context=task_context, required_filenames=[filename])
    section_instruction = "\n".join(
        [
            "Gateway-safe section fallback:",
            f"Generate only part {part_index} of {part_count} for {filename}.",
            f"This part should cover: {section_guidance(part_index, part_count)}.",
            "Begin immediately with the section content on the first line.",
            "Do not summarize the whole deliverable unless that belongs in this part.",
            "Do not try to write the entire deliverable in this part.",
            "Target 700-1200 words or the equivalent table/checklist rows for this part only.",
            "Stop at a clean boundary when this part is complete; later parts will cover the rest.",
            "Do not mention gateway fallback, retries, chunking, or internal execution.",
            "Do not wrap the response in JSON or a Markdown code fence.",
            "The final benchmark file will concatenate all parts, so make this part substantive and non-placeholder.",
        ]
    )
    return [*messages, {"role": "user", "content": section_instruction}]


def build_section_subpart_prompt(
    task: dict[str, Any],
    wrapper: str,
    task_context: dict[str, Any] | None,
    filename: str,
    part_index: int,
    part_count: int,
    subpart_index: int,
    subpart_count: int,
) -> list[dict[str, str]]:
    messages = build_section_prompt(task, wrapper, task_context, filename, part_index, part_count)
    subpart_instruction = "\n".join(
        [
            "Subsection fallback:",
            f"Generate only subpart {subpart_index} of {subpart_count} for part {part_index} of {part_count}.",
            "Keep this subsection bounded and immediately useful; do not try to cover the entire part.",
            "Begin immediately with the subsection content on the first line.",
            "Target 400-800 words or the equivalent table/checklist rows for this subsection only.",
            "Hard cap: stop before 900 words even if more could be said.",
            "Do not continue into another subsection; later subparts will cover the rest.",
            "Do not mention fallback, retries, chunking, or internal execution.",
            "Do not wrap the response in JSON or a Markdown code fence.",
            "The final benchmark file will concatenate all sections and subsections.",
        ]
    )
    return [*messages, {"role": "user", "content": subpart_instruction}]


def run_section_subpart_fallback(
    run_dir: Path,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    filename: str,
    task_context: dict[str, Any] | None,
    max_completion_tokens: int,
    temperature: float,
    request_timeout: int,
    split_index: int,
    part_index: int,
    part_count: int,
) -> tuple[str, str | None, list[dict[str, Any]], dict[str, Any]]:
    subpart_total = section_subpart_count()
    subpart_token_cap = section_subpart_tokens(max_completion_tokens)
    responses: list[dict[str, Any]] = []
    manifest_parts: list[dict[str, Any]] = []
    contents: list[str] = []
    errors: list[str] = []
    for subpart_index in range(1, subpart_total + 1):
        messages = build_section_subpart_prompt(
            task,
            wrapper,
            task_context,
            filename,
            part_index,
            part_count,
            subpart_index,
            subpart_total,
        )
        request_payload = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": subpart_token_cap,
            "temperature": temperature,
            "reasoning_split": provider_uses_reasoning_split(),
            "stream": provider_uses_streaming(),
            "section_subpart_fallback": True,
            "split_index": split_index,
            "filename": filename,
            "part_index": part_index,
            "part_count": part_count,
            "subpart_index": subpart_index,
            "subpart_count": subpart_total,
        }
        write_json(
            run_dir / f"request_split_{split_index:02d}_part_{part_index:02d}_sub_{subpart_index:02d}.json",
            request_payload,
        )
        try:
            response = call_minimax(
                model,
                messages,
                subpart_token_cap,
                temperature,
                request_timeout,
                response_format_json=False,
            )
            responses.append(response)
            write_json(
                run_dir / f"provider_response_split_{split_index:02d}_part_{part_index:02d}_sub_{subpart_index:02d}.json",
                response,
            )
            content = extract_content(response["response"]).strip()
            finish = finish_reason(response)
            subpart_error = None
            if finish == "length":
                subpart_error = f"subpart {subpart_index}: finish_reason=length"
            elif not content:
                subpart_error = f"subpart {subpart_index}: empty_response"
            if subpart_error:
                errors.append(subpart_error)
            contents.append(f"### Part {part_index}.{subpart_index} of {part_count}.{subpart_total}\n\n{content}")
            manifest_parts.append(
                {
                    "subpart_index": subpart_index,
                    "finish_reason": finish,
                    "content_chars": len(content),
                    "error": subpart_error,
                }
            )
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - retryable fallback path
            message = f"subpart {subpart_index}: {exc}"
            errors.append(message)
            manifest_parts.append({"subpart_index": subpart_index, "error": message})
    manifest = {
        "filename": filename,
        "part_index": part_index,
        "part_count": part_count,
        "subpart_count": subpart_total,
        "subpart_tokens": subpart_token_cap,
        "subparts": manifest_parts,
        "errors": errors,
    }
    write_json(run_dir / f"section_subpart_fallback_split_{split_index:02d}_part_{part_index:02d}.json", manifest)
    if errors:
        return (
            f"MiniMax section subpart fallback failed for {filename} part {part_index}: {'; '.join(errors)}",
            f"section_subpart_fallback_failed: {'; '.join(errors)}",
            responses,
            manifest,
        )
    return "\n\n".join(contents), None, responses, manifest


def run_sectioned_deliverable_fallback(
    run_dir: Path,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    filename: str,
    task_context: dict[str, Any] | None,
    max_completion_tokens: int,
    temperature: float,
    request_timeout: int,
    split_index: int,
) -> tuple[str, str | None, list[dict[str, Any]], dict[str, Any]]:
    """Generate one deliverable in multiple gateway-safe sections."""

    part_count = section_fallback_parts()
    part_tokens = section_fallback_tokens(max_completion_tokens)
    responses: list[dict[str, Any]] = []
    manifest_parts: list[dict[str, Any]] = []
    contents: list[str] = []
    errors: list[str] = []
    for part_index in range(1, part_count + 1):
        messages = build_section_prompt(
            task,
            wrapper,
            task_context,
            filename,
            part_index,
            part_count,
        )
        request_payload = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": part_tokens,
            "temperature": temperature,
            "reasoning_split": provider_uses_reasoning_split(),
            "stream": provider_uses_streaming(),
            "section_fallback": True,
            "split_index": split_index,
            "filename": filename,
            "part_index": part_index,
            "part_count": part_count,
        }
        write_json(run_dir / f"request_split_{split_index:02d}_part_{part_index:02d}.json", request_payload)
        content = ""
        part_error = None
        finish = None
        subpart_manifest = None
        try:
            response = call_minimax(
                model,
                messages,
                part_tokens,
                temperature,
                request_timeout,
                response_format_json=False,
            )
            responses.append(response)
            write_json(run_dir / f"provider_response_split_{split_index:02d}_part_{part_index:02d}.json", response)
            content = extract_content(response["response"]).strip()
            finish = finish_reason(response)
            if finish == "length":
                part_error = f"part {part_index}: finish_reason=length"
            elif not content:
                part_error = f"part {part_index}: empty_response"
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - retryable fallback path
            part_error = f"part {part_index}: {exc}"
        if part_error:
            sub_content, sub_error, sub_responses, subpart_manifest = run_section_subpart_fallback(
                run_dir=run_dir,
                task=task,
                model=model,
                wrapper=wrapper,
                filename=filename,
                task_context=task_context,
                max_completion_tokens=max_completion_tokens,
                temperature=temperature,
                request_timeout=request_timeout,
                split_index=split_index,
                part_index=part_index,
                part_count=part_count,
            )
            responses.extend(sub_responses)
            if sub_error:
                part_error = f"{part_error}; {sub_error}"
                content = sub_content
            else:
                content = sub_content
                part_error = None
        if part_error:
            errors.append(part_error)
        contents.append(f"## Part {part_index} of {part_count}\n\n{content}")
        manifest_parts.append(
            {
                "part_index": part_index,
                "finish_reason": finish,
                "content_chars": len(content),
                "error": part_error,
                "subpart_fallback": subpart_manifest,
                "subpart_recovered": bool(subpart_manifest and not part_error),
            }
        )
    manifest = {
        "filename": filename,
        "part_count": part_count,
        "part_tokens": part_tokens,
        "parts": manifest_parts,
        "errors": errors,
    }
    write_json(run_dir / f"section_fallback_split_{split_index:02d}.json", manifest)
    if errors:
        return (
            f"MiniMax section fallback failed for {filename}: {'; '.join(errors)}",
            f"sectioned_fallback_failed: {'; '.join(errors)}",
            responses,
            manifest,
        )
    return "\n\n".join(contents), None, responses, manifest


def run_split_deliverable_fallback(
    run_dir: Path,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    expected_filenames: list[str],
    task_context: dict[str, Any] | None,
    max_completion_tokens: int,
    temperature: float,
    request_timeout: int,
) -> tuple[dict[str, str], str | None, dict[str, Any]]:
    """Generate each expected deliverable separately after an overlong bundle."""

    split_deliverables: dict[str, str] = {}
    split_responses: list[dict[str, Any]] = []
    split_manifest: list[dict[str, Any]] = []
    split_errors: list[str] = []
    for index, filename in enumerate(expected_filenames, start=1):
        file_manifest: dict[str, Any] = {"filename": filename}
        file_error = None
        deliverable_error = None
        messages = build_prompt(task, wrapper, task_context=task_context, required_filenames=[filename])
        request_payload = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
            "reasoning_split": provider_uses_reasoning_split(),
            "stream": provider_uses_streaming(),
            "split_fallback": True,
            "split_index": index,
            "filename": filename,
        }
        write_json(run_dir / f"request_split_{index:02d}.json", request_payload)
        try:
            response = call_minimax(
                model,
                messages,
                max_completion_tokens,
                temperature,
                request_timeout,
                response_format_json=False,
            )
            split_responses.append(response)
            write_json(run_dir / f"provider_response_split_{index:02d}.json", response)
            content = extract_content(response["response"])
            if content.strip().startswith("{"):
                deliverables, deliverable_error = parse_deliverables(content, [filename])
            elif content.strip():
                deliverables, deliverable_error = {filename: content.strip()}, None
            else:
                deliverables = {filename: content}
                deliverable_error = f"missing_deliverables: {filename}"
            split_deliverables[filename] = deliverables.get(filename, content)
            file_finish_reason = finish_reason(response)
            file_manifest.update(
                {
                    "finish_reason": file_finish_reason,
                    "deliverable_error": deliverable_error,
                    "content_chars": len(split_deliverables[filename]),
                }
            )
            if file_finish_reason == "length":
                file_error = f"{filename}: finish_reason=length"
            elif deliverable_error and deliverable_error_is_retryable(deliverable_error):
                file_error = f"{filename}: {deliverable_error}"
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - split fallback is retryable as a leaf
            file_error = f"{filename}: {exc}"
            file_manifest["primary_error"] = file_error
            split_deliverables[filename] = f"MiniMax split fallback failed for {filename}: {exc}"
        if file_error:
            section_content, section_error, section_responses, section_manifest = run_sectioned_deliverable_fallback(
                run_dir=run_dir,
                task=task,
                model=model,
                wrapper=wrapper,
                filename=filename,
                task_context=task_context,
                max_completion_tokens=max_completion_tokens,
                temperature=temperature,
                request_timeout=request_timeout,
                split_index=index,
            )
            split_responses.extend(section_responses)
            file_manifest["section_fallback"] = section_manifest
            if section_error:
                file_error = f"{file_error}; {section_error}"
                split_deliverables[filename] = section_content
            else:
                file_error = None
                deliverable_error = None
                split_deliverables[filename] = section_content
                file_manifest["section_recovered"] = True
                file_manifest["content_chars"] = len(section_content)
        file_manifest["error"] = file_error
        if file_error:
            split_errors.append(file_error)
        split_manifest.append(file_manifest)
    write_json(run_dir / "split_fallback_manifest.json", {"files": split_manifest, "errors": split_errors})
    response = split_fallback_response(
        split_responses,
        finish="length" if any("finish_reason=length" in error for error in split_errors) else "stop",
    )
    if split_errors:
        return split_deliverables, f"split_fallback_failed: {'; '.join(split_errors)}", response
    return split_deliverables, None, response


def _write_smoke_artifacts_unlocked(
    root: Path,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    max_completion_tokens: int,
    temperature: float,
    retry_on_length: bool,
    length_retry_tokens: int,
    request_timeout: int,
    lab_dir: Path | None,
    max_documents: int,
    max_document_chars: int,
    max_context_chars: int,
    context_mode: str,
    max_activated_chunks: int,
    chunk_chars: int,
    split_first: bool = False,
) -> dict[str, str] | None:
    run_dir = root / context_mode / safe_task_path(task["task_id"]) / model / wrapper
    run_dir.mkdir(parents=True, exist_ok=True)
    if artifact_is_complete(run_dir, wrapper, task["deliverables"]):
        log_progress(
            progress_event(
                "skip_complete_before_start",
                context_mode=context_mode,
                task_id=task["task_id"],
                model=model,
                wrapper=wrapper,
            )
        )
        return None
    task_context = (
        load_task_context(
            lab_dir,
            task["task_id"],
            max_documents,
            max_document_chars,
            max_context_chars,
            context_mode=context_mode,
            max_activated_chunks=max_activated_chunks,
            chunk_chars=chunk_chars,
        )
        if lab_dir
        else None
    )
    messages = build_prompt(task, wrapper, task_context=task_context)
    error = None
    deliverable_error = None
    response = None
    bundle = None
    token_caps = [max_completion_tokens]
    if retry_on_length and length_retry_tokens > max_completion_tokens:
        token_caps.append(length_retry_tokens)
    try:
        write_run_status(run_dir, "started", task, model, wrapper, context_mode, task_context=task_context)
        expected_filenames = task["deliverables"]
        prior_split = prior_response_needs_split_fallback(run_dir)
        if split_first:
            write_json(
                run_dir / "split_fallback_trigger.json",
                {
                    "finish_reason": None,
                    "deliverable_error": None,
                    "expected_filenames": expected_filenames,
                    "split_first": True,
                },
            )
            deliverables, deliverable_error, response = run_split_deliverable_fallback(
                run_dir=run_dir,
                task=task,
                model=model,
                wrapper=wrapper,
                expected_filenames=expected_filenames,
                task_context=task_context,
                max_completion_tokens=length_retry_tokens,
                temperature=temperature,
                request_timeout=request_timeout,
            )
            write_json(run_dir / "provider_response.json", response)
        elif prior_split:
            write_json(
                run_dir / "split_fallback_trigger.json",
                {
                    "finish_reason": prior_split.get("finish_reason"),
                    "deliverable_error": prior_split.get("deliverable_error"),
                    "expected_filenames": expected_filenames,
                    "resume_direct": True,
                },
            )
            deliverables, deliverable_error, response = run_split_deliverable_fallback(
                run_dir=run_dir,
                task=task,
                model=model,
                wrapper=wrapper,
                expected_filenames=expected_filenames,
                task_context=task_context,
                max_completion_tokens=length_retry_tokens,
                temperature=temperature,
                request_timeout=request_timeout,
            )
            write_json(run_dir / "provider_response.json", response)
        else:
            for attempt, token_cap in enumerate(token_caps, start=1):
                request_payload = {
                    "model": model,
                    "messages": messages,
                    "max_completion_tokens": token_cap,
                    "temperature": temperature,
                    "reasoning_split": provider_uses_reasoning_split(),
                    "stream": provider_uses_streaming(),
                    "attempt": attempt,
                }
                write_json(run_dir / f"request_attempt_{attempt}.json", request_payload)
                write_json(run_dir / "request.json", request_payload)
                if task_context is not None:
                    write_json(run_dir / "task_context.json", {
                        "document_count_in_context": task_context["document_count_in_context"],
                        "context_chars": task_context["context_chars"],
                        "activation": task_context.get("activation"),
                        "documents": [
                            {
                                "filename": document["filename"],
                                "relative_path": document["relative_path"],
                                "text_chars": len(document["text"]),
                                "truncated": document["truncated"],
                            }
                            for document in task_context["documents"]
                        ],
                    })
                response = call_minimax(model, messages, token_cap, temperature, request_timeout)
                write_json(run_dir / f"provider_response_attempt_{attempt}.json", response)
                write_json(run_dir / "provider_response.json", response)
                if finish_reason(response) != "length":
                    break
            if response is None:
                raise RuntimeError("MiniMax call did not return a response")
            content = extract_content(response["response"])
            deliverables, deliverable_error = parse_deliverables(content, expected_filenames)
            if finish_reason(response) == "length" or deliverable_error_is_retryable(deliverable_error):
                write_json(
                    run_dir / "split_fallback_trigger.json",
                    {
                        "finish_reason": finish_reason(response),
                        "deliverable_error": deliverable_error,
                        "expected_filenames": expected_filenames,
                    },
                )
                deliverables, deliverable_error, response = run_split_deliverable_fallback(
                    run_dir=run_dir,
                    task=task,
                    model=model,
                    wrapper=wrapper,
                    expected_filenames=expected_filenames,
                    task_context=task_context,
                    max_completion_tokens=length_retry_tokens,
                    temperature=temperature,
                    request_timeout=request_timeout,
                )
                write_json(run_dir / "provider_response.json", response)
        length_error = None
        if finish_reason(response) == "length":
            length_error = (
                "finish_reason=length after retry; output is truncated "
                f"at max_completion_tokens={token_caps[-1]}"
            )
        bundle = evaluate_constraints(task, wrapper, deliverables, task_context, deliverable_error or length_error)
        apply_release_adapter(run_dir, task, wrapper, deliverables, bundle)
        content = combined_markdown(deliverables)
        if finish_reason(response) == "length":
            error = {
                "task_id": task["task_id"],
                "model": model,
                "wrapper": wrapper,
                "context_mode": context_mode,
                "error": length_error or "finish_reason=length",
            }
        elif deliverable_error and deliverable_error_is_retryable(deliverable_error):
            error = {
                "task_id": task["task_id"],
                "model": model,
                "wrapper": wrapper,
                "context_mode": context_mode,
                "error": deliverable_error,
            }
    except (Exception, SystemExit) as exc:
        error = {
            "task_id": task["task_id"],
            "model": model,
            "wrapper": wrapper,
            "context_mode": context_mode,
            "error": str(exc),
        }
        content = f"MiniMax smoke call failed: {exc}\n"
        deliverables = {filename: content for filename in task["deliverables"]}
        bundle = evaluate_constraints(task, wrapper, deliverables, task_context, str(exc))
        apply_release_adapter(run_dir, task, wrapper, deliverables, bundle)
    (run_dir / "final_work_product.md").write_text(content + "\n")
    if bundle is None:
        bundle = evaluate_constraints(task, wrapper, {filename: content for filename in task["deliverables"]}, task_context)
    for name, obj in bundle.items():
        write_json(run_dir / f"{name}.json", obj)
    write_trace(run_dir / "trace.md", task, wrapper, bundle)
    write_run_status(
        run_dir,
        "completed" if error is None else "retryable_error",
        task,
        model,
        wrapper,
        context_mode,
        response=response,
        error=error,
        deliverable_error=deliverable_error,
        task_context=task_context,
    )
    return error


def write_smoke_artifacts(
    root: Path,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    max_completion_tokens: int,
    temperature: float,
    retry_on_length: bool,
    length_retry_tokens: int,
    request_timeout: int,
    lab_dir: Path | None,
    max_documents: int,
    max_document_chars: int,
    max_context_chars: int,
    context_mode: str,
    max_activated_chunks: int,
    chunk_chars: int,
    split_first: bool = False,
) -> dict[str, str] | None:
    run_dir = root / context_mode / safe_task_path(task["task_id"]) / model / wrapper
    run_dir.mkdir(parents=True, exist_ok=True)
    if not acquire_leaf_lock(run_dir):
        log_progress(
            progress_event(
                "job_locked_skip",
                context_mode=context_mode,
                task_id=task["task_id"],
                model=model,
                wrapper=wrapper,
            )
        )
        return None
    try:
        if artifact_is_complete(run_dir, wrapper, task["deliverables"]):
            log_progress(
                progress_event(
                    "skip_complete_after_lock",
                    context_mode=context_mode,
                    task_id=task["task_id"],
                    model=model,
                    wrapper=wrapper,
                )
            )
            return None
        return _write_smoke_artifacts_unlocked(
            root=root,
            task=task,
            model=model,
            wrapper=wrapper,
            max_completion_tokens=max_completion_tokens,
            temperature=temperature,
            retry_on_length=retry_on_length,
            length_retry_tokens=length_retry_tokens,
            request_timeout=request_timeout,
            lab_dir=lab_dir,
            max_documents=max_documents,
            max_document_chars=max_document_chars,
            max_context_chars=max_context_chars,
            context_mode=context_mode,
            max_activated_chunks=max_activated_chunks,
            chunk_chars=chunk_chars,
            split_first=split_first,
        )
    finally:
        release_leaf_lock(run_dir)


def send_worker_result(result_sink: Any, payload: dict[str, Any]) -> None:
    if hasattr(result_sink, "send"):
        result_sink.send(payload)
    else:
        result_sink.put(payload)


def write_smoke_artifacts_worker(result_sink: Any, kwargs: dict[str, Any]) -> None:
    """Process target for one isolated leaf run."""

    try:
        error = write_smoke_artifacts(**kwargs)
        send_worker_result(result_sink, {"error": error, "parent_status": False})
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - report leaf crashes to parent
        send_worker_result(result_sink, {
            "error": {
                "task_id": kwargs["task"]["task_id"],
                "model": kwargs["model"],
                "wrapper": kwargs["wrapper"],
                "context_mode": kwargs["context_mode"],
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "traceback": "".join(traceback.format_exception(exc)),
            },
            "parent_status": True,
        })
    finally:
        try:
            result_sink.close()
        except Exception:
            pass


def leaf_run_dir(root: Path, context_mode: str, task: dict[str, Any], model: str, wrapper: str) -> Path:
    return root / context_mode / safe_task_path(task["task_id"]) / model / wrapper


def write_parent_retryable_status(
    root: Path,
    context_mode: str,
    task: dict[str, Any],
    model: str,
    wrapper: str,
    error: dict[str, str],
) -> None:
    run_dir = leaf_run_dir(root, context_mode, task, model, wrapper)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run_status(
        run_dir,
        "retryable_error",
        task,
        model,
        wrapper,
        context_mode,
        error=error,
    )


def run_minimax_smoke(
    manifest_path: Path,
    out_dir: Path,
    models: tuple[str, ...] = DEFAULT_MINIMAX_MODELS,
    wrappers: tuple[str, ...] = ("raw_agent", "sage_law"),
    task_limit: int = 1,
    max_completion_tokens: int = 4096,
    temperature: float = 0.2,
    concurrency: int = 1,
    retry_on_length: bool = True,
    length_retry_tokens: int = 8192,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    lab_dir: Path | None = None,
    max_documents: int = 12,
    max_document_chars: int = 6000,
    max_context_chars: int = 80000,
    run_id: str | None = None,
    resume: bool = False,
    context_mode: str = "activated",
    max_activated_chunks: int = 16,
    chunk_chars: int = 1200,
    leaf_timeout: float | None = None,
    split_first: bool = False,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    models = canonical_model_names(models)
    for wrapper in wrappers:
        if wrapper not in WRAPPERS:
            raise SystemExit(f"Unknown wrapper: {wrapper}")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    root = out_dir / run_id
    root.mkdir(parents=True, exist_ok=True)
    planned_jobs = [
        (task, model, wrapper)
        for task in manifest["tasks"][:task_limit]
        for model in models
        for wrapper in wrappers
    ]
    jobs = []
    skipped_jobs = []
    for task, model, wrapper in planned_jobs:
        run_dir = root / context_mode / safe_task_path(task["task_id"]) / model / wrapper
        if resume and artifact_is_complete(run_dir, wrapper, task["deliverables"]):
            skipped_jobs.append({
                "task_id": task["task_id"],
                "model": model,
                "wrapper": wrapper,
                "reason": "complete",
            })
            log_progress(
                progress_event(
                    "skip_complete",
                    context_mode=context_mode,
                    task_id=task["task_id"],
                    model=model,
                    wrapper=wrapper,
                    skipped=len(skipped_jobs),
                )
            )
            continue
        if resume and leaf_lock_is_active(run_dir):
            skipped_jobs.append({
                "task_id": task["task_id"],
                "model": model,
                "wrapper": wrapper,
                "reason": "locked",
            })
            log_progress(
                progress_event(
                    "skip_locked",
                    context_mode=context_mode,
                    task_id=task["task_id"],
                    model=model,
                    wrapper=wrapper,
                    skipped=len(skipped_jobs),
                )
            )
            continue
        jobs.append((task, model, wrapper))
    errors: list[dict[str, str]] = []
    concurrency = max(1, concurrency)
    if leaf_timeout is not None and leaf_timeout <= 0:
        leaf_timeout = None
    total_jobs = len(jobs)
    completed_jobs = 0
    started_at = time.time()
    log_progress(
        progress_event(
            "run_start",
            run_id=run_id,
            context_mode=context_mode,
            planned_run_count=len(planned_jobs),
            artifact_run_count=total_jobs,
            skipped_run_count=len(skipped_jobs),
            concurrency=concurrency,
            request_timeout=request_timeout,
            leaf_timeout=leaf_timeout,
        )
    )
    def leaf_kwargs(task: dict[str, Any], model: str, wrapper: str) -> dict[str, Any]:
        return {
            "root": root,
            "task": task,
            "model": model,
            "wrapper": wrapper,
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
            "retry_on_length": retry_on_length,
            "length_retry_tokens": length_retry_tokens,
            "request_timeout": request_timeout,
            "lab_dir": lab_dir,
            "max_documents": max_documents,
            "max_document_chars": max_document_chars,
            "max_context_chars": max_context_chars,
            "context_mode": context_mode,
            "max_activated_chunks": max_activated_chunks,
            "chunk_chars": chunk_chars,
            "split_first": split_first,
        }

    if leaf_timeout is not None:
        ctx = worker_context()
        running_processes: dict[int, tuple[Any, Any, dict[str, Any], str, str, float]] = {}
        next_job_index = 0

        def submit_next_process() -> int | None:
            nonlocal next_job_index
            if next_job_index >= total_jobs:
                return None
            task, model, wrapper = jobs[next_job_index]
            next_job_index += 1
            log_progress(
                progress_event(
                    "job_start",
                    context_mode=context_mode,
                    task_id=task["task_id"],
                    model=model,
                    wrapper=wrapper,
                )
            )
            parent_conn, child_conn = ctx.Pipe(duplex=False)
            process = ctx.Process(
                target=write_smoke_artifacts_worker,
                args=(child_conn, leaf_kwargs(task, model, wrapper)),
            )
            process.start()
            child_conn.close()
            key = process.pid or id(process)
            running_processes[key] = (process, parent_conn, task, model, wrapper, time.time())
            return key

        def finish_process_job(
            process_key: int,
            error: dict[str, str] | None,
            job_started_at: float,
        ) -> None:
            nonlocal completed_jobs
            process, result_conn, task, model, wrapper, _ = running_processes.pop(process_key)
            try:
                process.join(timeout=0)
            finally:
                try:
                    result_conn.close()
                except Exception:
                    pass
            completed_jobs += 1
            log_progress(
                progress_event(
                    "job_done" if error is None else "job_error",
                    context_mode=context_mode,
                    task_id=task["task_id"],
                    model=model,
                    wrapper=wrapper,
                    completed=completed_jobs,
                    total=total_jobs,
                    elapsed_seconds=round(time.time() - job_started_at, 1),
                    error_kind=error_kind(error),
                    error=error.get("error") if error else None,
                )
            )
            if error is not None:
                errors.append(error)
            submit_next_process()

        for _ in range(min(concurrency, total_jobs)):
            submit_next_process()
        last_heartbeat = time.time()
        while running_processes:
            now = time.time()
            completed_or_timed_out = False
            for process_key, (process, result_conn, task, model, wrapper, job_started_at) in list(running_processes.items()):
                elapsed = now - job_started_at
                if process.is_alive() and elapsed > leaf_timeout:
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                    error = {
                        "task_id": task["task_id"],
                        "model": model,
                        "wrapper": wrapper,
                        "context_mode": context_mode,
                        "error": f"leaf wall-clock timeout after {round(elapsed, 1)}s",
                    }
                    write_parent_retryable_status(root, context_mode, task, model, wrapper, error)
                    finish_process_job(process_key, error, job_started_at)
                    completed_or_timed_out = True
                    continue
                if process.is_alive():
                    continue
                process.join(timeout=0)
                result: dict[str, Any] | None = None
                try:
                    if result_conn.poll():
                        result = result_conn.recv()
                except (EOFError, OSError):
                    result = None
                if result is None:
                    error = {
                        "task_id": task["task_id"],
                        "model": model,
                        "wrapper": wrapper,
                        "context_mode": context_mode,
                        "error": f"leaf worker exited without result; exitcode={process.exitcode}",
                    }
                    write_parent_retryable_status(root, context_mode, task, model, wrapper, error)
                else:
                    error = result.get("error")
                    if error is not None and result.get("parent_status"):
                        write_parent_retryable_status(root, context_mode, task, model, wrapper, error)
                finish_process_job(process_key, error, job_started_at)
                completed_or_timed_out = True
            now = time.time()
            if not completed_or_timed_out and now - last_heartbeat >= 30:
                queued_jobs = total_jobs - completed_jobs - len(running_processes)
                running = [
                    {
                        "task_id": task["task_id"],
                        "model": model,
                        "wrapper": wrapper,
                        "elapsed_seconds": round(now - job_started_at, 1),
                    }
                    for process, result_conn, task, model, wrapper, job_started_at in running_processes.values()
                ][:10]
                log_progress(
                    progress_event(
                        "heartbeat",
                        context_mode=context_mode,
                        completed=completed_jobs,
                        in_flight=len(running_processes),
                        queued=queued_jobs,
                        running=len(running_processes),
                        total=total_jobs,
                        elapsed_seconds=round(now - started_at, 1),
                        running_sample=running,
                    )
                )
                last_heartbeat = now
            time.sleep(0.2)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_job = {}
            next_job_index = 0

            def submit_next_job():
                nonlocal next_job_index
                if next_job_index >= total_jobs:
                    return None
                task, model, wrapper = jobs[next_job_index]
                next_job_index += 1
                log_progress(
                    progress_event(
                        "job_start",
                        context_mode=context_mode,
                        task_id=task["task_id"],
                        model=model,
                        wrapper=wrapper,
                    )
                )
                future = executor.submit(write_smoke_artifacts, **leaf_kwargs(task, model, wrapper))
                future_to_job[future] = (task, model, wrapper, time.time())
                return future

            pending = {
                future
                for future in (submit_next_job() for _ in range(min(concurrency, total_jobs)))
                if future is not None
            }
            last_heartbeat = time.time()
            while pending:
                done, pending = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
                now = time.time()
                if not done and now - last_heartbeat >= 30:
                    queued_jobs = total_jobs - completed_jobs - len(pending)
                    running = [
                        {
                            "task_id": task["task_id"],
                            "model": model,
                            "wrapper": wrapper,
                            "elapsed_seconds": round(now - job_started_at, 1),
                        }
                        for future, (task, model, wrapper, job_started_at) in future_to_job.items()
                        if future in pending
                    ][:10]
                    log_progress(
                        progress_event(
                            "heartbeat",
                            context_mode=context_mode,
                            completed=completed_jobs,
                            in_flight=len(pending),
                            queued=queued_jobs,
                            running=len(pending),
                            total=total_jobs,
                            elapsed_seconds=round(now - started_at, 1),
                            running_sample=running,
                        )
                    )
                    last_heartbeat = now
                    continue
                for future in done:
                    task, model, wrapper, job_started_at = future_to_job[future]
                    del future_to_job[future]
                    try:
                        error = future.result()
                    except (Exception, SystemExit) as exc:  # noqa: BLE001 - one bad leaf must not kill the run
                        error = {
                            "task_id": task["task_id"],
                            "model": model,
                            "wrapper": wrapper,
                            "context_mode": context_mode,
                            "error": str(exc),
                            "exception_type": type(exc).__name__,
                            "traceback": "".join(traceback.format_exception(exc)),
                        }
                        run_dir = root / context_mode / safe_task_path(task["task_id"]) / model / wrapper
                        run_dir.mkdir(parents=True, exist_ok=True)
                        write_run_status(
                            run_dir,
                            "retryable_error",
                            task,
                            model,
                            wrapper,
                            context_mode,
                            error=error,
                        )
                    completed_jobs += 1
                    log_progress(
                        progress_event(
                            "job_done" if error is None else "job_error",
                            context_mode=context_mode,
                            task_id=task["task_id"],
                            model=model,
                            wrapper=wrapper,
                            completed=completed_jobs,
                            total=total_jobs,
                            elapsed_seconds=round(time.time() - job_started_at, 1),
                            error_kind=error_kind(error),
                            error=error.get("error") if error else None,
                        )
                    )
                    if error is not None:
                        errors.append(error)
                    next_future = submit_next_job()
                    if next_future is not None:
                        pending.add(next_future)
    summary = {
        "schema_version": "sage-law.minimax-smoke-summary.v1",
        "run_id": run_id,
        "manifest": str(manifest_path),
        "out_dir": str(root),
        "models": list(models),
        "wrappers": list(wrappers),
        "task_limit": task_limit,
        "planned_run_count": len(planned_jobs),
        "artifact_run_count": len(jobs),
        "skipped_run_count": len(skipped_jobs),
        "resume": resume,
        "concurrency": concurrency,
        "max_completion_tokens": max_completion_tokens,
        "retry_on_length": retry_on_length,
        "length_retry_tokens": length_retry_tokens,
        "request_timeout": request_timeout,
        "lab_dir": str(lab_dir) if lab_dir else None,
        "max_documents": max_documents,
        "max_document_chars": max_document_chars,
        "max_context_chars": max_context_chars,
        "context_mode": context_mode,
        "max_activated_chunks": max_activated_chunks,
        "chunk_chars": chunk_chars,
        "leaf_timeout": leaf_timeout,
        "split_first": split_first,
        "skipped_jobs": skipped_jobs,
        "error_count": len(errors),
        "error_types": error_type_counts(errors),
        "errors": errors,
    }
    write_json(root / "summary.json", summary)
    return summary
