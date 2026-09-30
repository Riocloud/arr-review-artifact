"""Dry-run artifact writer for the SAGE-Law Harvey grid."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .authority import WRAPPERS, make_artifact_bundle
from .harvey import write_json


def safe_task_path(task_id: str) -> str:
    return task_id.replace("/", "__")


def write_trace(path: Path, task: dict[str, Any], wrapper: str, bundle: dict[str, Any]) -> None:
    debt = bundle["coverage_debt"]
    gate = bundle["gate_decision"]
    lines = [
        f"# Trace: {task['task_id']} / {wrapper}",
        "",
        f"- practice_area: `{task['practice_area']}`",
        f"- work_type: `{task['work_type']}`",
        f"- failure_modes: `{', '.join(task['failure_modes'])}`",
        f"- criteria_count: `{task['criteria_count']}`",
        f"- document_count: `{task['document_count']}`",
        "",
        "## Gate Decision",
        "",
        f"- decision: `{gate['decision']}`",
        f"- blocking_debt: `{gate['blocking_debt']}`",
        f"- receipt_count: `{gate['receipt_count']}`",
        "",
        "## Coverage Debt",
        "",
    ]
    if debt["unsatisfied_predicates"]:
        for predicate in debt["unsatisfied_predicates"]:
            lines.append(f"- `{predicate}`")
    else:
        lines.append("- none in dry run")
    lines.extend(
        [
            "",
            "## Reconstruction",
            "",
            "claim -> candidate field -> witness -> validator -> debt -> receipt -> gate",
            "",
            "This trace is a structural dry-run artifact. It does not score legal correctness.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def write_final_work_product(path: Path, task: dict[str, Any], wrapper: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# Dry Run Work Product: {task['title']}",
                "",
                f"Task: `{task['task_id']}`",
                f"Wrapper: `{wrapper}`",
                "",
                "This is not model output. It is a placeholder used to verify the SAGE-Law",
                "artifact contract before provider APIs and Harvey LAB judging are connected.",
            ]
        )
        + "\n"
    )


def run_dry_manifest(
    manifest_path: Path,
    out_dir: Path,
    wrappers: tuple[str, ...] = WRAPPERS,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    root = out_dir / run_id
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    for task in manifest["tasks"]:
        for wrapper in wrappers:
            if wrapper not in WRAPPERS:
                raise SystemExit(f"Unknown wrapper: {wrapper}")
            run_dir = root / safe_task_path(task["task_id"]) / wrapper
            run_dir.mkdir(parents=True, exist_ok=True)
            bundle = make_artifact_bundle(task, wrapper)
            write_final_work_product(run_dir / "final_work_product.md", task, wrapper)
            for name, obj in bundle.items():
                write_json(run_dir / f"{name}.json", obj)
            write_trace(run_dir / "trace.md", task, wrapper, bundle)
            count += 1
    summary = {
        "schema_version": "sage-law.dry-run-summary.v1",
        "run_id": run_id,
        "manifest": str(manifest_path),
        "out_dir": str(root),
        "task_count": len(manifest["tasks"]),
        "wrappers": list(wrappers),
        "artifact_run_count": count,
    }
    write_json(root / "summary.json", summary)
    return summary
