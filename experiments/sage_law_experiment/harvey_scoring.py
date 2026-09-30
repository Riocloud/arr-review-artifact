"""Harvey LAB criterion scoring for local SAGE-Law run leaves.

The public Harvey evaluator assumes one run under ``harvey-labs/results``.
Our experiment grid stores one leaf per context/task/model/wrapper, so this
module mirrors Harvey's criterion prompt and all-pass semantics directly over
those leaf directories.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .deliverables import (
    extract_json_object,
    repair_common_json,
    repair_invalid_backslash_escapes_inside_strings,
    repair_minimax_doubled_inner_quote_escapes,
    strip_code_fences,
    strip_think_blocks,
)
from .documents import DOCX_EXTRACTION_VERSION, read_document
from .harvey import write_json
from .minimax import (
    minimax_chat_url,
    provider_api_key,
    provider_rate_limit_sleep_seconds,
    provider_uses_reasoning_split,
)

RUBRIC_CRITERION_PROMPT = """You are evaluating a legal AI agent's work product against a specific quality criterion.

## Task
{task_description}

## Agent's Output
{agent_output}

## Criterion
**{criterion_title}**

{match_criteria}

## Instructions
Evaluate the agent's output against the criterion above.
- **PASS**: The agent's output satisfies the criterion as described
- **FAIL**: The agent's output does not satisfy the criterion as described

Respond with JSON only:

```json
{{
  "verdict": "pass" | "fail",
  "reasoning": "Brief explanation"
}}
```
"""

BATCH_RUBRIC_CRITERION_PROMPT = """You are evaluating a legal AI agent's work product against multiple specific quality criteria.

## Task
{task_description}

## Agent's Output
{agent_output}

## Criteria
{criteria_json}

## Instructions
Evaluate the agent's output against every criterion above.
- **PASS**: The agent's output satisfies that criterion as described
- **FAIL**: The agent's output does not satisfy that criterion as described
- Return one result for every criterion ID. Do not drop or rename IDs.

Respond with JSON only:

```json
{{
  "results": [
    {{
      "id": "criterion id",
      "verdict": "pass" | "fail",
      "reasoning": "Brief explanation"
    }}
  ]
}}
```
"""

SKIP_DIRS = {"node_modules", ".npm", "__pycache__", ".git", "venv", ".venv"}
SKIP_EXTENSIONS = {".lock", ".map"}
SKIP_FILES = {"package-lock.json"}


JudgeFn = Callable[[str], dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]


class JudgeProviderHTTPError(RuntimeError):
    """Provider HTTP error with status code preserved for retry backoff."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"MiniMax judge HTTP {status_code}: {body}")
        self.status_code = status_code
        self.body = body


@dataclass
class MiniMaxJudge:
    """MiniMax-backed JSON judge for Harvey criterion prompts."""

    model: str = "MiniMax-M2.7-highspeed"
    max_completion_tokens: int = 2048
    temperature: float = 0.0
    request_timeout: int = 1800
    retries: int = 3
    retry_sleep_seconds: float = 2.0
    reasoning_split: bool = False

    def __call__(self, prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts_made = 0
        for attempt in range(1, self.retries + 1):
            attempts_made = attempt
            try:
                return self._call_once(prompt, attempt)
            except Exception as exc:  # noqa: BLE001 - judge retry records provider/parser failures
                last_error = exc
                if _should_split_batch_without_retry(prompt, exc):
                    break
                if attempt < self.retries:
                    time.sleep(_judge_retry_delay(exc, attempt, self.retry_sleep_seconds))
        raise RuntimeError(f"MiniMax judge failed after {attempts_made} attempts: {last_error}") from last_error

    def _call_once(self, prompt: str, attempt: int) -> dict[str, Any]:
        api_key = provider_api_key()
        if not api_key:
            raise RuntimeError("Set MINIMAX_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY before scoring.")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict legal benchmark grader. Return only JSON matching "
                        "the schema requested by the user. Do not output chain-of-thought."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": self.max_completion_tokens,
            "temperature": self.temperature,
        }
        if self.reasoning_split and provider_uses_reasoning_split():
            payload["reasoning_split"] = True
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
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
                status = response.status
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise JudgeProviderHTTPError(exc.code, error_body) from exc
        content = _extract_content(body)
        parsed = _parse_judge_response_content(content)
        result = dict(parsed)
        result["_parsed_result"] = parsed
        if _verdict_value(result) is not None:
            result["verdict"] = _normalize_verdict(_verdict_value(result))
        if _reasoning_value(result) is not None:
            result["reasoning"] = str(_reasoning_value(result) or "")
        result.update(
            {
                "judge_provider_status": status,
                "judge_elapsed_seconds": round(time.time() - started, 3),
                "judge_attempt": attempt,
                "judge_usage": body.get("usage", {}),
                "judge_finish_reason": _finish_reason(body),
            }
        )
        return result


def _judge_retry_delay(exc: Exception, attempt: int, base_sleep_seconds: float) -> float:
    if isinstance(exc, JudgeProviderHTTPError):
        if exc.status_code == 429:
            if attempt >= 2 and _is_long_window_rate_limit(exc.body):
                return 230.0 * 60.0
            return max(provider_rate_limit_sleep_seconds(), base_sleep_seconds * (2 ** (attempt - 1)))
        if exc.status_code in {408, 425, 500, 502, 503, 504, 524}:
            return max(15.0, base_sleep_seconds * attempt)
    return base_sleep_seconds * attempt


def _should_split_batch_without_retry(prompt: str, exc: Exception) -> bool:
    if not _is_batch_criterion_prompt(prompt):
        return False
    return _is_json_parse_failure(exc)


def _is_batch_criterion_prompt(prompt: str) -> bool:
    return "## Criteria" in prompt and '"match_criteria"' in prompt and '"id"' in prompt


def _is_json_parse_failure(exc: Exception) -> bool:
    return "json_parse_failed" in str(exc).lower()


def _is_long_window_rate_limit(body: str) -> bool:
    normalized = body.lower()
    return (
        "usage limit exceeded" in normalized
        and ("5-hour usage limit" in normalized or "token plan" in normalized)
    )


def discover_scoreable_runs(
    run_dir: Path,
    *,
    context_modes: tuple[str, ...] | None = None,
    models: tuple[str, ...] | None = None,
    wrappers: tuple[str, ...] | None = None,
    statuses: tuple[str, ...] | None = ("completed",),
    task_ids: set[str] | None = None,
    output_mode: str = "released",
) -> list[Path]:
    """Return leaf run directories that contain scoreable ``output`` files."""

    run_dir = Path(run_dir)
    output_dir_name = _output_dir_name(output_mode)
    candidates = (
        [run_dir / output_dir_name]
        if (run_dir / output_dir_name).is_dir()
        else list(run_dir.rglob(output_dir_name))
    )
    leaves: list[Path] = []
    seen: set[Path] = set()
    context_filter = set(context_modes or ())
    model_filter = set(models or ())
    wrapper_filter = set(wrappers or ())
    status_filter = set(statuses or ())
    task_filter = set(task_ids or ())
    for output_dir in sorted(candidates):
        if output_dir_name == "output" and "review_output" in output_dir.parts:
            continue
        leaf = output_dir.parent
        if leaf in seen:
            continue
        status = _read_json(leaf / "status.json") or {}
        if task_filter and str(status.get("task_id") or "") not in task_filter:
            continue
        if status_filter and status.get("status") not in status_filter:
            continue
        if context_filter and status.get("context_mode") not in context_filter:
            continue
        if model_filter and status.get("model") not in model_filter:
            continue
        if wrapper_filter and status.get("wrapper") not in wrapper_filter:
            continue
        if any(path.is_file() for path in output_dir.rglob("*")):
            leaves.append(leaf)
            seen.add(leaf)
    return leaves


def load_agent_output(
    run_dir: Path,
    criterion: dict[str, Any],
    max_output_chars: int = 120_000,
    output_mode: str = "released",
) -> str:
    """Load criterion-scoped output text using Harvey's deliverables field."""

    output_dir = _output_dir_for_run(Path(run_dir), output_mode)
    deliverables = [str(name) for name in criterion.get("deliverables", []) if name]
    if deliverables:
        sections = []
        for expected in deliverables:
            path = _resolve_output_file(output_dir, expected)
            if path is None:
                sections.append(f"## Agent Output: {expected}\n(File not found: {expected})")
                continue
            content = _read_output_file(path)
            sections.append(f"## Agent Output: {expected}\n{content}")
        output = "\n\n".join(sections) if sections else "(No agent output found)"
    else:
        output = _load_all_output(output_dir)
    if len(output) > max_output_chars:
        return output[:max_output_chars] + "\n\n[agent output truncated for judge context]"
    return output


def score_run_with_judge(
    run_dir: Path,
    lab_dir: Path,
    judge_model: str,
    judge: JudgeFn,
    parallel: int = 6,
    max_output_chars: int = 120_000,
    progress: ProgressFn | None = None,
    resume: bool = True,
    output_mode: str = "released",
    criteria_batch_size: int = 1,
    score_namespace: str | None = None,
) -> dict[str, Any]:
    """Score one SAGE-Law run leaf against all Harvey criteria."""

    run_dir = Path(run_dir)
    task_id = _task_id_for_run(run_dir)
    task = _load_task_config(Path(lab_dir), task_id)
    criteria = task["criteria"]
    cache_dir = run_dir / _score_cache_dir_name(output_mode, score_namespace)
    cache_dir.mkdir(exist_ok=True)
    output_cache: dict[tuple[str, ...], str] = {}

    def cached_agent_output(criterion: dict[str, Any]) -> str:
        cache_key = tuple(str(name) for name in criterion.get("deliverables", []) if name)
        cached = output_cache.get(cache_key)
        if cached is not None:
            return cached
        rendered = load_agent_output(
            run_dir,
            criterion,
            max_output_chars=max_output_chars,
            output_mode=output_mode,
        )
        output_cache[cache_key] = rendered
        return rendered

    def score_one(criterion: dict[str, Any]) -> dict[str, Any]:
        cache_path = cache_dir / f"{_safe_criterion_id(criterion)}.json"
        if resume and cache_path.exists():
            cached = _read_json(cache_path)
            if cached:
                if progress:
                    progress({"event": "criterion_skip", "criterion_id": criterion.get("id")})
                return cached
        prompt = RUBRIC_CRITERION_PROMPT.format(
            task_description=task.get("title", ""),
            agent_output=cached_agent_output(criterion),
            criterion_title=criterion["title"],
            match_criteria=criterion["match_criteria"],
        )
        started = time.time()
        try:
            raw_result = judge(prompt)
        except Exception as exc:  # noqa: BLE001 - failed judge calls must checkpoint as failures
            if progress:
                progress({"event": "criterion_error", "criterion_id": criterion.get("id"), "error": str(exc)})
            raise RuntimeError(f"criterion {criterion.get('id')} judge_error: {exc}") from exc
        result = {
            "id": criterion["id"],
            "title": criterion["title"],
            "verdict": _normalize_verdict(_verdict_value(raw_result)),
            "reasoning": str(_reasoning_value(raw_result) or ""),
            "deliverables": criterion.get("deliverables", []),
            "elapsed_seconds": round(time.time() - started, 3),
            "judge": _judge_metadata(raw_result),
            "raw_judge_result": _raw_judge_result(raw_result),
        }
        write_json(cache_path, result)
        if progress:
            progress({"event": "criterion_done", "criterion_id": criterion.get("id"), "verdict": result["verdict"]})
        return result

    if criteria_batch_size <= 1:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
            criteria_results = list(executor.map(score_one, criteria))
    else:
        criteria_results = score_criteria_batches(
            run_dir=run_dir,
            task=task,
            criteria=criteria,
            judge=judge,
            parallel=parallel,
            max_output_chars=max_output_chars,
            progress=progress,
            resume=resume,
            output_mode=output_mode,
            cache_dir=cache_dir,
            batch_size=criteria_batch_size,
            agent_output_loader=cached_agent_output,
        )

    n_criteria = len(criteria_results)
    n_passed = sum(1 for criterion in criteria_results if criterion["verdict"] == "pass")
    all_pass = n_criteria > 0 and n_passed == n_criteria
    scores = {
        "schema_version": "sage-law.harvey-scores.v1",
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "summary": (
            f"{n_passed}/{n_criteria} criteria passed."
            + (" ALL-PASS." if all_pass else f" Missed {n_criteria - n_passed}; task FAIL.")
        ),
        "all_pass": all_pass,
        "n_criteria": n_criteria,
        "n_passed": n_passed,
        "criteria_results": criteria_results,
        "run_id": str(run_dir),
        "task": task_id,
        "judge_model": judge_model,
        "score_namespace": _score_namespace_value(score_namespace),
        "output_mode": output_mode,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "run_metadata": _run_metadata(run_dir, output_mode=output_mode),
    }
    write_json(run_dir / _scores_file_name(output_mode, score_namespace), scores)
    return scores


def score_criteria_batches(
    *,
    run_dir: Path,
    task: dict[str, Any],
    criteria: list[dict[str, Any]],
    judge: JudgeFn,
    parallel: int,
    max_output_chars: int,
    progress: ProgressFn | None,
    resume: bool,
    output_mode: str,
    cache_dir: Path,
    batch_size: int,
    agent_output_loader: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    criteria_results: dict[str, dict[str, Any]] = {}
    missing_by_deliverables: dict[tuple[str, ...], list[dict[str, Any]]] = {}

    for criterion in criteria:
        criterion_id = str(criterion["id"])
        cache_path = cache_dir / f"{_safe_criterion_id(criterion)}.json"
        if resume and cache_path.exists():
            cached = _read_json(cache_path)
            if cached:
                criteria_results[criterion_id] = cached
                if progress:
                    progress({"event": "criterion_skip", "criterion_id": criterion_id})
                continue
        deliverables = tuple(str(name) for name in criterion.get("deliverables", []) if name)
        missing_by_deliverables.setdefault(deliverables, []).append(criterion)

    group_states = [
        {"criteria": grouped, "index": 0, "batch_size": max(1, batch_size)}
        for grouped in missing_by_deliverables.values()
    ]
    next_group_cursor = 0
    fallback_batch_size = _fallback_criteria_batch_size(batch_size)

    def pop_next_batch() -> tuple[int, list[dict[str, Any]]] | None:
        nonlocal next_group_cursor
        if not group_states:
            return None
        for offset in range(len(group_states)):
            group_index = (next_group_cursor + offset) % len(group_states)
            state = group_states[group_index]
            grouped = state["criteria"]
            index = int(state["index"])
            if not isinstance(grouped, list) or index >= len(grouped):
                continue
            size = int(state["batch_size"])
            end = min(len(grouped), index + size)
            state["index"] = end
            next_group_cursor = (group_index + 1) % len(group_states)
            return group_index, grouped[index:end]
        return None

    def score_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        did_split = False

        def score_batch_inner(inner_batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal did_split
            started = time.time()
            prompt = BATCH_RUBRIC_CRITERION_PROMPT.format(
                task_description=task.get("title", ""),
                agent_output=agent_output_loader(inner_batch[0]),
                criteria_json=json.dumps(
                    [
                        {
                            "id": criterion["id"],
                            "title": criterion["title"],
                            "match_criteria": criterion["match_criteria"],
                        }
                        for criterion in inner_batch
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            try:
                raw_result = judge(prompt)
            except Exception as exc:  # noqa: BLE001 - failed judge calls must checkpoint as failures
                if len(inner_batch) > 1 and _batch_error_can_split(exc):
                    did_split = True
                    if progress:
                        progress(
                            {
                                "event": "criterion_batch_split",
                                "criterion_ids": [criterion.get("id") for criterion in inner_batch],
                                "error": str(exc),
                            }
                        )
                    midpoint = max(1, len(inner_batch) // 2)
                    return score_batch_inner(inner_batch[:midpoint]) + score_batch_inner(inner_batch[midpoint:])
                if progress:
                    progress(
                        {
                            "event": "criterion_batch_error",
                            "criterion_ids": [criterion.get("id") for criterion in inner_batch],
                            "error": str(exc),
                        }
                    )
                raise RuntimeError(f"criterion batch judge_error: {exc}") from exc
            try:
                normalized = _normalize_batch_results(raw_result, inner_batch)
            except RuntimeError as exc:
                if len(inner_batch) > 1 and _batch_error_can_split(exc):
                    did_split = True
                    if progress:
                        progress(
                            {
                                "event": "criterion_batch_split",
                                "criterion_ids": [criterion.get("id") for criterion in inner_batch],
                                "error": str(exc),
                            }
                        )
                    midpoint = max(1, len(inner_batch) // 2)
                    return score_batch_inner(inner_batch[:midpoint]) + score_batch_inner(inner_batch[midpoint:])
                raise
            elapsed = round(time.time() - started, 3)
            results = []
            for criterion in inner_batch:
                criterion_id = str(criterion["id"])
                raw_criterion = normalized[criterion_id]
                result = {
                    "id": criterion["id"],
                    "title": criterion["title"],
                    "verdict": _normalize_verdict(_verdict_value(raw_criterion)),
                    "reasoning": str(_reasoning_value(raw_criterion) or ""),
                    "deliverables": criterion.get("deliverables", []),
                    "elapsed_seconds": elapsed,
                    "judge": _judge_metadata(raw_result),
                    "raw_judge_result": raw_criterion,
                }
                write_json(cache_dir / f"{_safe_criterion_id(criterion)}.json", result)
                if progress:
                    progress({"event": "criterion_done", "criterion_id": criterion_id, "verdict": result["verdict"]})
                results.append(result)
            if progress:
                progress({"event": "criterion_batch_done", "criterion_count": len(inner_batch)})
            return results

        return score_batch_inner(batch), did_split

    max_workers = max(1, parallel)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_group_index = {}
        pending = set()

        def submit_next_batch():
            next_batch = pop_next_batch()
            if next_batch is None:
                return None
            group_index, batch = next_batch
            future = executor.submit(score_batch, batch)
            future_to_group_index[future] = group_index
            return future

        for _ in range(max_workers):
            future = submit_next_batch()
            if future is not None:
                pending.add(future)

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                group_index = future_to_group_index.pop(future)
                batch_results, did_split = future.result()
                if did_split and int(group_states[group_index]["batch_size"]) > fallback_batch_size:
                    group_states[group_index]["batch_size"] = fallback_batch_size
                    if progress:
                        progress(
                            {
                                "event": "criterion_batch_size_degrade",
                                "batch_size": fallback_batch_size,
                            }
                        )
                for result in batch_results:
                    criteria_results[str(result["id"])] = result
                next_future = submit_next_batch()
                if next_future is not None:
                    pending.add(next_future)

    missing_ids = [str(criterion["id"]) for criterion in criteria if str(criterion["id"]) not in criteria_results]
    if missing_ids:
        raise RuntimeError(f"criterion batch missing results: {missing_ids[:10]}")
    return [criteria_results[str(criterion["id"])] for criterion in criteria]


def _normalize_batch_results(raw_result: dict[str, Any], criteria: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    expected_ids = [str(criterion["id"]) for criterion in criteria]
    expected_by_canonical = {_canonical_criterion_id(criterion_id): criterion_id for criterion_id in expected_ids}
    if len(expected_ids) == 1 and "verdict" in raw_result:
        return {expected_ids[0]: raw_result}

    id_map_values = {criterion_id: raw_result.get(criterion_id) for criterion_id in expected_ids}
    if all(isinstance(value, dict) for value in id_map_values.values()):
        return {criterion_id: id_map_values[criterion_id] for criterion_id in expected_ids}  # type: ignore[return-value]
    canonical_map_values: dict[str, Any] = {}
    for key, value in raw_result.items():
        canonical_id = _canonical_criterion_id(key)
        if canonical_id in expected_by_canonical:
            canonical_map_values[expected_by_canonical[canonical_id]] = value
    if all(isinstance(canonical_map_values.get(criterion_id), dict) for criterion_id in expected_ids):
        return {criterion_id: canonical_map_values[criterion_id] for criterion_id in expected_ids}

    results = (
        raw_result.get("results")
        or raw_result.get("criteria")
        or raw_result.get("verdicts")
        or raw_result.get("evaluations")
        or raw_result.get("criteria_results")
        or raw_result.get("scores")
        or raw_result.get("items")
    )
    if not isinstance(results, list):
        raise RuntimeError(f"criterion batch judge response missing results list; keys={sorted(raw_result.keys())}")
    result_items = [item for item in results if isinstance(item, dict)]
    for index, item in enumerate(result_items):
        if not isinstance(item, dict):
            continue
        raw_criterion_id = str(
            item.get("id")
            or item.get("criterion_id")
            or item.get("criterionId")
            or item.get("criterion")
            or ""
        )
        criterion_id = raw_criterion_id
        canonical_id = _canonical_criterion_id(raw_criterion_id)
        if canonical_id in expected_by_canonical:
            criterion_id = expected_by_canonical[canonical_id]
        elif not criterion_id and len(result_items) == len(expected_ids):
            criterion_id = expected_ids[index]
        if criterion_id:
            by_id[criterion_id] = item
    missing = [criterion_id for criterion_id in expected_ids if criterion_id not in by_id]
    if missing and len(result_items) == len(expected_ids):
        return {criterion_id: result_items[index] for index, criterion_id in enumerate(expected_ids)}
    if missing:
        raise RuntimeError(f"criterion batch judge response missing ids: {missing}")
    return {criterion_id: by_id[criterion_id] for criterion_id in expected_ids}


def _parse_judge_response_content(content: str) -> dict[str, Any]:
    """Parse judge JSON while tolerating batch-oriented provider shapes."""

    cleaned = strip_code_fences(strip_think_blocks(content)).strip()
    for candidate in _judge_json_variants(cleaned):
        parsed = _loads_judge_json(candidate)
        if parsed is not None:
            return parsed

    parsed_values: list[Any] = []
    for candidate in _balanced_json_values(cleaned):
        parsed = _loads_any_judge_json(candidate)
        if parsed is not None:
            parsed_values.append(parsed)
    if len(parsed_values) == 1:
        return _coerce_judge_json_value(parsed_values[0])
    if len(parsed_values) > 1 and all(isinstance(item, dict) for item in parsed_values):
        return {"results": parsed_values}

    return extract_json_object(cleaned)


def _judge_json_variants(raw: str | None) -> list[str]:
    variants = [
        raw,
        repair_minimax_doubled_inner_quote_escapes(raw),
        repair_invalid_backslash_escapes_inside_strings(raw),
        repair_invalid_backslash_escapes_inside_strings(repair_minimax_doubled_inner_quote_escapes(raw)),
        repair_common_json(raw),
        repair_common_json(repair_minimax_doubled_inner_quote_escapes(raw)),
        repair_common_json(repair_invalid_backslash_escapes_inside_strings(raw)),
    ]
    seen: set[str] = set()
    compact: list[str] = []
    for variant in variants:
        if not variant or variant in seen:
            continue
        seen.add(variant)
        compact.append(variant)
    return compact


def _loads_judge_json(raw: str) -> dict[str, Any] | None:
    parsed = _loads_any_judge_json(raw)
    if parsed is None:
        return None
    return _coerce_judge_json_value(parsed)


def _loads_any_judge_json(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _coerce_judge_json_value(parsed: Any) -> dict[str, Any]:
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        return {"results": parsed}
    raise ValueError("json_parse_failed")


def _balanced_json_values(text: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(text):
        if text[index] not in "{[":
            index += 1
            continue
        value = _balanced_json_value_at(text, index)
        if value is None:
            index += 1
            continue
        raw, end_index = value
        values.append(raw)
        index = end_index
    return values


def _balanced_json_value_at(text: str, start: int) -> tuple[str, int] | None:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    stack = [closer]
    in_string = False
    escape = False
    for index in range(start + 1, len(text)):
        ch = text[index]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack or ch != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return text[start : index + 1], index + 1
    return None


def _canonical_criterion_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"C[-_ ]?0*([0-9]+)", text)
    if match:
        return f"C-{int(match.group(1)):03d}"
    return text


def _verdict_value(result: dict[str, Any]) -> Any:
    for key in ("verdict", "result", "decision", "label", "status"):
        if key in result:
            return result.get(key)
    for key in ("passed", "pass", "satisfied", "meets_criterion", "meetsCriterion"):
        if key in result:
            return result.get(key)
    return None


def _reasoning_value(result: dict[str, Any]) -> Any:
    for key in ("reasoning", "explanation", "rationale", "reason", "justification"):
        if key in result:
            return result.get(key)
    return None


def _raw_judge_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    parsed = raw_result.get("_parsed_result")
    if isinstance(parsed, dict):
        return parsed
    return {key: value for key, value in raw_result.items() if not key.startswith("judge_")}


def _batch_error_can_split(exc: Exception) -> bool:
    text = str(exc).lower()
    return "json_parse_failed" in text or "missing ids" in text or "missing results list" in text


def _fallback_criteria_batch_size(batch_size: int) -> int:
    configured = os.environ.get("SAGE_LAW_FALLBACK_CRITERIA_BATCH_SIZE", "").strip()
    if configured:
        try:
            return max(1, min(max(1, batch_size), int(configured)))
        except ValueError:
            pass
    return max(1, min(max(1, batch_size), 4))


def score_discovered_runs(
    run_dir: Path,
    lab_dir: Path,
    judge: JudgeFn,
    judge_model: str,
    parallel_runs: int = 1,
    parallel_criteria: int = 6,
    run_limit: int | None = None,
    max_output_chars: int = 120_000,
    resume: bool = True,
    progress: ProgressFn | None = None,
    context_modes: tuple[str, ...] | None = None,
    models: tuple[str, ...] | None = None,
    wrappers: tuple[str, ...] | None = None,
    statuses: tuple[str, ...] | None = ("completed",),
    task_ids: set[str] | None = None,
    output_mode: str = "released",
    criteria_batch_size: int = 1,
    score_namespace: str | None = None,
) -> dict[str, Any]:
    """Score discovered leaf runs and return an aggregate summary."""

    leaves = discover_scoreable_runs(
        Path(run_dir),
        context_modes=context_modes,
        models=models,
        wrappers=wrappers,
        statuses=statuses,
        task_ids=task_ids,
        output_mode=output_mode,
    )
    if run_limit is not None:
        leaves = leaves[:run_limit]
    total = len(leaves)
    started_at = time.time()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if progress:
        progress(
            {
                "event": "score_run_start",
                "leaf_run_count": total,
                "parallel_runs": parallel_runs,
                "context_modes": list(context_modes or []),
                "models": list(models or []),
                "wrappers": list(wrappers or []),
                "statuses": list(statuses or []),
                "output_mode": output_mode,
                "score_namespace": _score_namespace_value(score_namespace),
            }
        )

    def score_leaf(leaf: Path) -> dict[str, Any]:
        scores_path = leaf / _scores_file_name(output_mode, score_namespace)
        if resume and scores_path.exists():
            existing = _read_json(scores_path)
            if existing:
                if progress:
                    progress({"event": "score_leaf_skip", "leaf": str(leaf)})
                return existing
        if progress:
            progress({"event": "score_leaf_start", "leaf": str(leaf)})
        return score_run_with_judge(
            run_dir=leaf,
            lab_dir=lab_dir,
            judge_model=judge_model,
            judge=judge,
            parallel=parallel_criteria,
            max_output_chars=max_output_chars,
            resume=resume,
            output_mode=output_mode,
            criteria_batch_size=criteria_batch_size,
            score_namespace=score_namespace,
        )

    max_parallel_runs = max(1, parallel_runs)
    with ThreadPoolExecutor(max_workers=max_parallel_runs) as executor:
        future_to_leaf = {}
        next_leaf_index = 0

        def submit_next_leaf():
            nonlocal next_leaf_index
            if next_leaf_index >= total:
                return None
            leaf = leaves[next_leaf_index]
            next_leaf_index += 1
            future = executor.submit(score_leaf, leaf)
            future_to_leaf[future] = leaf
            return future

        pending = {
            future
            for future in (submit_next_leaf() for _ in range(min(max_parallel_runs, total)))
            if future is not None
        }
        completed = 0
        last_heartbeat = time.time()
        while pending:
            done, pending = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            now = time.time()
            if not done and progress and now - last_heartbeat >= 30:
                progress(
                    {
                        "event": "score_heartbeat",
                        "completed": completed,
                        "in_flight": len(pending),
                        "queued": total - completed - len(pending),
                        "running": len(pending),
                        "total": total,
                        "elapsed_seconds": round(now - started_at, 1),
                    }
                )
                last_heartbeat = now
                continue
            for future in done:
                leaf = future_to_leaf[future]
                del future_to_leaf[future]
                completed += 1
                try:
                    result = future.result()
                    results.append(result)
                    if progress:
                        progress(
                            {
                                "event": "score_leaf_done",
                                "completed": completed,
                                "total": total,
                                "leaf": str(leaf),
                                "all_pass": result.get("all_pass"),
                                "n_passed": result.get("n_passed"),
                                "n_criteria": result.get("n_criteria"),
                            }
                        )
                except Exception as exc:  # noqa: BLE001 - aggregate should continue over bad leaves
                    error = {"leaf": str(leaf), "error": str(exc)}
                    errors.append(error)
                    if progress:
                        progress({"event": "score_leaf_error", "completed": completed, "total": total, **error})
                next_future = submit_next_leaf()
                if next_future is not None:
                    pending.add(next_future)

    aggregate = _score_summary(
        Path(run_dir),
        results,
        errors,
        output_mode=output_mode,
        judge_model=judge_model,
        score_namespace=score_namespace,
    )
    write_json(Path(run_dir) / _scores_summary_file_name(output_mode, score_namespace), aggregate)
    return aggregate


def json_progress(event: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"event_time": datetime.now(timezone.utc).isoformat(), **event},
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def _score_summary(
    run_dir: Path,
    results: list[dict[str, Any]],
    errors: list[dict[str, str]],
    output_mode: str = "released",
    judge_model: str | None = None,
    score_namespace: str | None = None,
) -> dict[str, Any]:
    n_runs = len(results)
    all_pass_count = sum(1 for result in results if result.get("all_pass"))
    total_criteria = sum(int(result.get("n_criteria") or 0) for result in results)
    total_passed = sum(int(result.get("n_passed") or 0) for result in results)
    by_context_model_wrapper: dict[str, Any] = {}
    for result in results:
        meta = result.get("run_metadata") or {}
        context = meta.get("context_mode") or "unknown"
        model = meta.get("model") or "unknown"
        wrapper = meta.get("wrapper") or "unknown"
        bucket = by_context_model_wrapper.setdefault(context, {}).setdefault(model, {}).setdefault(
            wrapper,
            {"runs": 0, "all_pass": 0, "criteria": 0, "passed": 0},
        )
        bucket["runs"] += 1
        bucket["all_pass"] += 1 if result.get("all_pass") else 0
        bucket["criteria"] += int(result.get("n_criteria") or 0)
        bucket["passed"] += int(result.get("n_passed") or 0)
    return {
        "schema_version": "sage-law.harvey-score-summary.v1",
        "run_dir": str(run_dir),
        "output_mode": output_mode,
        "judge_model": judge_model or "",
        "score_namespace": _score_namespace_value(score_namespace),
        "scored_run_count": n_runs,
        "error_count": len(errors),
        "all_pass_count": all_pass_count,
        "all_pass_rate": all_pass_count / n_runs if n_runs else 0.0,
        "criterion_pass_count": total_passed,
        "criterion_count": total_criteria,
        "criterion_pass_rate": total_passed / total_criteria if total_criteria else 0.0,
        "by_context_model_wrapper": by_context_model_wrapper,
        "errors": errors,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_task_config(lab_dir: Path, task_id: str) -> dict[str, Any]:
    task_path = lab_dir / "tasks" / Path(*task_id.split("/")) / "task.json"
    if not task_path.exists():
        raise FileNotFoundError(f"task.json not found for {task_id}: {task_path}")
    task = json.loads(task_path.read_text())
    if not isinstance(task.get("criteria"), list) or not task["criteria"]:
        raise ValueError(f"{task_path}: criteria must be a non-empty list")
    for index, criterion in enumerate(task["criteria"]):
        for key in ("id", "title", "match_criteria"):
            if key not in criterion:
                raise ValueError(f"{task_path}: criterion {index} missing {key}")
    return task


def _task_id_for_run(run_dir: Path) -> str:
    status = _read_json(run_dir / "status.json")
    if status and status.get("task_id"):
        return str(status["task_id"])
    candidate = _read_json(run_dir / "candidate.json")
    if candidate and candidate.get("task_id"):
        return str(candidate["task_id"])
    raise ValueError(f"Cannot infer task_id for run leaf: {run_dir}")


def _run_metadata(run_dir: Path, output_mode: str = "released") -> dict[str, Any]:
    status = _read_json(run_dir / "status.json") or {}
    gate = _read_json(run_dir / "gate_decision.json") or {}
    return {
        "task_id": status.get("task_id"),
        "model": status.get("model"),
        "wrapper": status.get("wrapper"),
        "context_mode": status.get("context_mode"),
        "status": status.get("status"),
        "finish_reason": status.get("finish_reason"),
        "gate_decision": gate.get("decision"),
        "output_mode": output_mode,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _safe_criterion_id(criterion: dict[str, Any]) -> str:
    raw = str(criterion.get("id") or criterion.get("title") or "criterion")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "criterion"


def _output_dir_name(output_mode: str) -> str:
    if output_mode == "released":
        return "output"
    if output_mode == "review":
        return "review_output"
    raise ValueError(f"Unknown scoring output mode: {output_mode}")


def _output_dir_for_run(run_dir: Path, output_mode: str) -> Path:
    output_dir = Path(run_dir) / _output_dir_name(output_mode)
    if output_dir.exists():
        return output_dir
    if output_mode == "review":
        return Path(run_dir) / "output"
    return output_dir


def _score_cache_dir_name(output_mode: str, score_namespace: str | None = None) -> str:
    namespace = _safe_score_namespace(score_namespace)
    if output_mode == "released":
        return f"score_cache_{namespace}" if namespace else "score_cache"
    _output_dir_name(output_mode)
    base = f"score_cache_{output_mode}"
    return f"{base}_{namespace}" if namespace else base


def _scores_file_name(output_mode: str, score_namespace: str | None = None) -> str:
    namespace = _safe_score_namespace(score_namespace)
    if output_mode == "released":
        return f"scores_{namespace}.json" if namespace else "scores.json"
    _output_dir_name(output_mode)
    base = f"scores_{output_mode}"
    return f"{base}_{namespace}.json" if namespace else f"{base}.json"


def _scores_summary_file_name(output_mode: str, score_namespace: str | None = None) -> str:
    namespace = _safe_score_namespace(score_namespace)
    if output_mode == "released":
        return f"scores_summary_{namespace}.json" if namespace else "scores_summary.json"
    _output_dir_name(output_mode)
    base = f"scores_summary_{output_mode}"
    return f"{base}_{namespace}.json" if namespace else f"{base}.json"


def _safe_score_namespace(score_namespace: str | None) -> str:
    if not score_namespace:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", score_namespace).strip("_")


def _score_namespace_value(score_namespace: str | None) -> str:
    return _safe_score_namespace(score_namespace) or "default"


def _resolve_output_file(output_dir: Path, expected: str) -> Path | None:
    exact = output_dir / expected
    if exact.exists():
        return exact
    basename = Path(expected).name
    for candidate in sorted(output_dir.rglob(basename)):
        if candidate.is_file():
            return candidate
    stem = Path(expected).stem.lower().replace("-", " ").replace("_", " ")
    expected_words = set(stem.split())
    best: tuple[int, Path] | None = None
    for candidate in sorted(output_dir.rglob("*")):
        if not candidate.is_file() or candidate.name.lower().startswith("output."):
            continue
        if candidate.suffix.lower() != Path(expected).suffix.lower():
            continue
        candidate_words = set(candidate.stem.lower().replace("-", " ").replace("_", " ").split())
        score = len(expected_words & candidate_words)
        if score > 0 and (best is None or score > best[0]):
            best = (score, candidate)
    return best[1] if best else None


def _read_output_file(path: Path) -> str:
    text = read_document(path)
    if text and not text.startswith("(error extracting"):
        return text
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return text or f"(error reading {path.name})"
    if raw.strip():
        return raw
    return text or f"(empty file: {path.name})"


def _load_all_output(output_dir: Path) -> str:
    sections = []
    if output_dir.exists():
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(output_dir).parts):
                continue
            if path.suffix in SKIP_EXTENSIONS or path.name in SKIP_FILES:
                continue
            sections.append(f"## {path.relative_to(output_dir)}\n{_read_output_file(path)}")
    return "\n\n".join(sections) if sections else "(No agent output found)"


def _normalize_verdict(value: Any) -> str:
    if isinstance(value, bool):
        return "pass" if value else "fail"
    verdict = str(value or "").strip().lower()
    pass_values = {"pass", "passed", "true", "yes", "y", "satisfied", "met", "meets", "ok"}
    return "pass" if verdict in pass_values else "fail"


def _judge_metadata(raw_result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: raw_result[key]
        for key in (
            "judge_provider_status",
            "judge_elapsed_seconds",
            "judge_attempt",
            "judge_usage",
            "judge_finish_reason",
        )
        if key in raw_result
    }


def _extract_content(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def _finish_reason(body: dict[str, Any]) -> str | None:
    choices = body.get("choices") or []
    if not choices:
        return None
    finish_reason = choices[0].get("finish_reason")
    return str(finish_reason) if finish_reason else None
