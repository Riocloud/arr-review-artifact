"""Run-grid planning helpers for SAGE-Law experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .authority import WRAPPERS
from .models import canonical_model_names

EXPECTED_ARTIFACTS = (
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


def parse_csv(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        raise SystemExit("Expected at least one comma-separated value")
    return items


def build_run_plan(
    manifest_path: Path,
    models: tuple[str, ...],
    wrappers: tuple[str, ...] = WRAPPERS,
) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    models = canonical_model_names(models)
    rows: list[dict[str, Any]] = []
    for task in manifest["tasks"]:
        for model in models:
            for wrapper in wrappers:
                if wrapper not in WRAPPERS:
                    raise SystemExit(f"Unknown wrapper: {wrapper}")
                rows.append(
                    {
                        "schema_version": "sage-law.run-plan-row.v1",
                        "status": "planned",
                        "manifest": str(manifest_path),
                        "task_id": task["task_id"],
                        "practice_area": task["practice_area"],
                        "failure_modes": task["failure_modes"],
                        "criteria_count": task["criteria_count"],
                        "document_count": task["document_count"],
                        "model": model,
                        "wrapper": wrapper,
                        "expected_artifacts": list(EXPECTED_ARTIFACTS),
                    }
                )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
