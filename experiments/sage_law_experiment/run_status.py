"""Aggregate status summaries for SAGE-Law experiment runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATUS_KEYS = ("completed", "retryable_error", "skipped")


def summarize_run_status(run_dir: Path, task_ids: set[str] | None = None) -> dict:
    """Summarize leaf run status files under an experiment run directory."""

    task_filter = set(task_ids or ())
    summary = _new_bucket()
    summary.update(
        {
            "schema_version": "sage-law.run-status-summary.v1",
            "run_dir": str(run_dir),
            "leaf_run_count": 0,
            "by_context_mode": {},
            "by_model": {},
            "by_wrapper": {},
            "by_context_model_wrapper": {},
            "missing_files": {},
            "invalid_json": {},
        }
    )

    for status_path in sorted(run_dir.rglob("status.json")):
        leaf_dir = status_path.parent
        status = _read_json(status_path, summary, "status.json") or {}
        if task_filter and str(status.get("task_id") or "") not in task_filter:
            continue
        provider_response = _read_optional_json(leaf_dir / "provider_response.json", summary)
        gate_decision = _read_optional_json(leaf_dir / "gate_decision.json", summary)
        coverage_debt = _read_optional_json(leaf_dir / "coverage_debt.json", summary)
        row = _leaf_row(leaf_dir, status, provider_response, gate_decision, coverage_debt)

        _add_row(summary, row)
        _add_row(_bucket_for(summary["by_context_mode"], row["context_mode"]), row)
        _add_row(_bucket_for(summary["by_model"], row["model"]), row)
        _add_row(_bucket_for(summary["by_wrapper"], row["wrapper"]), row)
        context_bucket = summary["by_context_model_wrapper"].setdefault(row["context_mode"], {})
        model_bucket = context_bucket.setdefault(row["model"], {})
        _add_row(_bucket_for(model_bucket, row["wrapper"]), row)

    _finalize_bucket(summary)
    for bucket in summary["by_context_mode"].values():
        _finalize_bucket(bucket)
    for bucket in summary["by_model"].values():
        _finalize_bucket(bucket)
    for bucket in summary["by_wrapper"].values():
        _finalize_bucket(bucket)
    for context_bucket in summary["by_context_model_wrapper"].values():
        for model_bucket in context_bucket.values():
            for bucket in model_bucket.values():
                _finalize_bucket(bucket)
    return summary


def _new_bucket() -> dict[str, Any]:
    return {
        "runs": 0,
        "status_counts": {},
        "completed": 0,
        "retryable_error": 0,
        "skipped": 0,
        "finish_reasons": {},
        "error_kinds": {},
        "deliverable_error_counts": {},
        "completed_deliverable_error_counts": {},
        "scoreable_completed": 0,
        "non_scoreable_completed": 0,
        "non_scoreable_completed_reasons": {},
        "completed_gate_blocked": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "context_chars": 0,
        "gate_decisions": {},
        "coverage_blocking": 0,
        "coverage_predicates": {},
    }


def _bucket_for(parent: dict[str, Any], key: str) -> dict[str, Any]:
    return parent.setdefault(key, _new_bucket())


def _add_row(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    bucket["runs"] += 1
    bucket["status_counts"][row["status"]] = bucket["status_counts"].get(row["status"], 0) + 1
    if row["status"] in STATUS_KEYS:
        bucket[row["status"]] += 1
    if row["finish_reason"]:
        _increment(bucket["finish_reasons"], row["finish_reason"])
    if row["error_kind"]:
        _increment(bucket["error_kinds"], row["error_kind"])
    if row["deliverable_error"]:
        _increment(bucket["deliverable_error_counts"], row["deliverable_error"])
        if row["status"] == "completed":
            _increment(bucket["completed_deliverable_error_counts"], row["deliverable_error"])
    if row["status"] == "completed":
        reasons = row["non_scoreable_completed_reasons"]
        if reasons:
            bucket["non_scoreable_completed"] += 1
            for reason in reasons:
                _increment(bucket["non_scoreable_completed_reasons"], reason)
        else:
            bucket["scoreable_completed"] += 1
        if row["gate_decision"] == "blocked_or_escalated":
            bucket["completed_gate_blocked"] += 1
    bucket["prompt_tokens"] += row["prompt_tokens"]
    bucket["completion_tokens"] += row["completion_tokens"]
    bucket["context_chars"] += row["context_chars"]
    if row["gate_decision"]:
        _increment(bucket["gate_decisions"], row["gate_decision"])
    if row["coverage_blocking"]:
        bucket["coverage_blocking"] += 1
    for predicate in row["coverage_predicates"]:
        _increment(bucket["coverage_predicates"], predicate)
    if "leaf_run_count" in bucket:
        bucket["leaf_run_count"] += 1


def _finalize_bucket(bucket: dict[str, Any]) -> None:
    for key in (
        "status_counts",
        "finish_reasons",
        "error_kinds",
        "deliverable_error_counts",
        "completed_deliverable_error_counts",
        "non_scoreable_completed_reasons",
        "gate_decisions",
        "coverage_predicates",
    ):
        bucket[key] = dict(sorted(bucket[key].items()))


def _leaf_row(
    leaf_dir: Path,
    status: dict[str, Any],
    provider_response: dict[str, Any] | None,
    gate_decision: dict[str, Any] | None,
    coverage_debt: dict[str, Any] | None,
) -> dict[str, Any]:
    usage = _usage(status, provider_response)
    finish_reason = _finish_reason(status, provider_response)
    error_kind = _error_kind(status.get("error"))
    deliverable_error = _deliverable_error(status)
    return {
        "path": str(leaf_dir),
        "status": str(status.get("status") or "unknown"),
        "context_mode": str(status.get("context_mode") or "unknown"),
        "model": str(status.get("model") or "unknown"),
        "wrapper": str(status.get("wrapper") or "unknown"),
        "finish_reason": finish_reason,
        "error_kind": error_kind,
        "deliverable_error": deliverable_error,
        "non_scoreable_completed_reasons": _non_scoreable_completed_reasons(
            str(status.get("status") or "unknown"),
            finish_reason,
            error_kind,
            deliverable_error,
        ),
        "prompt_tokens": _int_value(usage.get("prompt_tokens")),
        "completion_tokens": _int_value(usage.get("completion_tokens")),
        "context_chars": _int_value(status.get("context_chars")),
        "gate_decision": _gate_decision(gate_decision),
        "coverage_blocking": bool((coverage_debt or {}).get("blocking")),
        "coverage_predicates": _coverage_predicates(coverage_debt),
    }


def _usage(status: dict[str, Any], provider_response: dict[str, Any] | None) -> dict[str, Any]:
    status_usage = status.get("usage")
    if isinstance(status_usage, dict):
        return status_usage
    provider_usage = (provider_response or {}).get("response", {}).get("usage")
    if isinstance(provider_usage, dict):
        return provider_usage
    return {}


def _finish_reason(status: dict[str, Any], provider_response: dict[str, Any] | None) -> str | None:
    if status.get("finish_reason"):
        return str(status["finish_reason"])
    choices = (provider_response or {}).get("response", {}).get("choices") or []
    if not choices:
        return None
    finish_reason = choices[0].get("finish_reason")
    return str(finish_reason) if finish_reason else None


def _gate_decision(gate_decision: dict[str, Any] | None) -> str | None:
    decision = (gate_decision or {}).get("decision")
    return str(decision) if decision else None


def _deliverable_error(status: dict[str, Any]) -> str | None:
    deliverable_error = status.get("deliverable_error")
    return str(deliverable_error) if deliverable_error else None


def _non_scoreable_completed_reasons(
    status: str,
    finish_reason: str | None,
    error_kind: str | None,
    deliverable_error: str | None,
) -> list[str]:
    if status != "completed":
        return []
    reasons: list[str] = []
    if deliverable_error:
        reasons.append("deliverable_error")
    if error_kind:
        reasons.append("status_error")
    if finish_reason == "length":
        reasons.append("length_finish")
    return reasons


def _coverage_predicates(coverage_debt: dict[str, Any] | None) -> list[str]:
    if not coverage_debt:
        return []
    predicates: list[str] = []
    unsatisfied = coverage_debt.get("unsatisfied_predicates")
    if isinstance(unsatisfied, list):
        predicates.extend(str(predicate) for predicate in unsatisfied)
    debt_by_type = coverage_debt.get("debt_by_type")
    if isinstance(debt_by_type, dict):
        for values in debt_by_type.values():
            if isinstance(values, list):
                predicates.extend(str(predicate) for predicate in values)
    return sorted(set(predicates))


def _error_kind(error: Any) -> str | None:
    if not isinstance(error, dict):
        return None
    message = str(error.get("error") or "")
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
    )
    if any(marker in message for marker in network_markers):
        return "provider_or_network"
    return "other"


def _read_optional_json(path: Path, summary: dict[str, Any]) -> dict[str, Any] | None:
    if not path.exists():
        _increment(summary["missing_files"], path.name)
        return None
    return _read_json(path, summary, path.name)


def _read_json(path: Path, summary: dict[str, Any], key: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        _increment(summary["invalid_json"], key)
        return None
    return data if isinstance(data, dict) else {}


def _int_value(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
