"""Artifact-level smoke metrics for SAGE-Law experiment runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    return json.loads(path.read_text())


def summarize_artifacts(run_dir: Path) -> dict[str, Any]:
    gate_files = sorted(run_dir.rglob("gate_decision.json"))
    by_wrapper: dict[str, Counter[str]] = defaultdict(Counter)
    decisions: dict[str, Counter[str]] = defaultdict(Counter)
    missing_artifacts: list[str] = []

    expected = (
        "final_work_product.md",
        "candidate.json",
        "matter_state.json",
        "witnesses.json",
        "validators.json",
        "coverage_debt.json",
        "receipts.json",
        "gate_decision.json",
        "trace.md",
    )

    for gate_file in gate_files:
        run_leaf = gate_file.parent
        gate = _load_json(gate_file)
        if not isinstance(gate, dict):
            raise SystemExit(f"Gate file is not an object: {gate_file}")
        wrapper = str(gate.get("wrapper") or run_leaf.name)
        by_wrapper[wrapper]["runs"] += 1
        by_wrapper[wrapper]["receipt_count"] += int(gate.get("receipt_count") or 0)
        if gate.get("blocking_debt"):
            by_wrapper[wrapper]["blocking_debt_runs"] += 1
        decisions[wrapper][str(gate.get("decision"))] += 1
        for name in expected:
            if not (run_leaf / name).exists():
                missing_artifacts.append(str(run_leaf / name))

    return {
        "schema_version": "sage-law.artifact-summary.v1",
        "run_dir": str(run_dir),
        "artifact_run_count": len(gate_files),
        "by_wrapper": {
            wrapper: {
                **dict(counts),
                "decisions": dict(sorted(decisions[wrapper].items())),
            }
            for wrapper, counts in sorted(by_wrapper.items())
        },
        "missing_artifacts": missing_artifacts,
    }


def summarize_provider_responses(run_dir: Path) -> dict[str, Any]:
    response_files = sorted(run_dir.rglob("provider_response.json"))
    by_wrapper: dict[str, Counter[str]] = defaultdict(Counter)
    by_model: dict[str, Counter[str]] = defaultdict(Counter)
    finish_reasons: Counter[str] = Counter()
    retries = len(list(run_dir.rglob("provider_response_attempt_2.json")))
    for response_file in response_files:
        response = _load_json(response_file)
        if not isinstance(response, dict):
            continue
        parts = response_file.relative_to(run_dir).parts
        wrapper = parts[-2] if len(parts) >= 2 else "unknown"
        body = response.get("response") or {}
        model = str(body.get("model") or "unknown")
        choices = body.get("choices") or []
        finish = str((choices[0] if choices else {}).get("finish_reason") or "missing")
        usage = body.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        elapsed_ms = int(float(response.get("elapsed_seconds") or 0) * 1000)
        for bucket in (by_wrapper[wrapper], by_model[model]):
            bucket["runs"] += 1
            bucket["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            bucket["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            bucket["reasoning_tokens"] += int(reasoning)
            bucket["total_tokens"] += int(usage.get("total_tokens") or 0)
            bucket["elapsed_ms"] += elapsed_ms
            bucket[f"finish_{finish}"] += 1
        finish_reasons[finish] += 1
    return {
        "schema_version": "sage-law.provider-summary.v1",
        "run_dir": str(run_dir),
        "response_count": len(response_files),
        "retry_count": retries,
        "finish_reasons": dict(sorted(finish_reasons.items())),
        "by_model": {
            model: _counter_with_avg_elapsed(counter)
            for model, counter in sorted(by_model.items())
        },
        "by_wrapper": {
            wrapper: _counter_with_avg_elapsed(counter)
            for wrapper, counter in sorted(by_wrapper.items())
        },
    }


def _counter_with_avg_elapsed(counter: Counter[str]) -> dict[str, Any]:
    data = dict(counter)
    runs = data.get("runs", 0)
    data["avg_elapsed_seconds"] = round((data.pop("elapsed_ms", 0) / 1000) / runs, 3) if runs else 0
    return data
