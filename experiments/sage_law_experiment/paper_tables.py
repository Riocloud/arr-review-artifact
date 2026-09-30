"""Paper-ready CSV and Markdown table exports for SAGE-Law experiments."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .harvey import write_json
from .run_status import summarize_run_status


def write_paper_tables(run_dir: Path, out_dir: Path, task_ids: set[str] | None = None) -> dict[str, Any]:
    """Write generation and Harvey-score summaries for paper tables."""

    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    status_summary = summarize_run_status(run_dir, task_ids=task_ids)
    score_summaries = _load_score_summaries(run_dir)

    generation_rows = generation_status_rows(status_summary)
    score_rows = harvey_score_rows(score_summaries)
    _write_csv(
        out_dir / "generation_status_by_context_model_wrapper.csv",
        [
            "context_mode",
            "model",
            "wrapper",
            "runs",
            "completed",
            "scoreable_completed",
            "non_scoreable_completed",
            "retryable_error",
            "skipped",
            "prompt_tokens",
            "completion_tokens",
            "finish_reasons",
            "gate_decisions",
            "deliverable_error_counts",
            "non_scoreable_completed_reasons",
            "completed_gate_blocked",
        ],
        generation_rows,
    )
    _write_csv(
        out_dir / "harvey_scores_by_context_model_wrapper.csv",
        [
            "score_output_mode",
            "score_namespace",
            "judge_model",
            "context_mode",
            "model",
            "wrapper",
            "runs",
            "all_pass",
            "all_pass_rate",
            "criteria",
            "passed",
            "criterion_pass_rate",
        ],
        score_rows,
    )
    (out_dir / "paper_tables.md").write_text(_markdown_tables(generation_rows, score_rows))
    summary = {
        "schema_version": "sage-law.paper-tables.v1",
        "run_dir": str(run_dir),
        "out_dir": str(out_dir),
        "task_filter_count": len(task_ids or []),
        "generation_rows": len(generation_rows),
        "score_rows": len(score_rows),
    }
    write_json(out_dir / "paper_tables_summary.json", summary)
    return summary


def generation_status_rows(status_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_cmw = status_summary.get("by_context_model_wrapper") or {}
    for context_mode, models in sorted(by_cmw.items()):
        for model, wrappers in sorted((models or {}).items()):
            for wrapper, bucket in sorted((wrappers or {}).items()):
                rows.append(
                    {
                        "context_mode": context_mode,
                        "model": model,
                        "wrapper": wrapper,
                        "runs": int(bucket.get("runs") or 0),
                        "completed": int(bucket.get("completed") or 0),
                        "scoreable_completed": int(bucket.get("scoreable_completed") or 0),
                        "non_scoreable_completed": int(bucket.get("non_scoreable_completed") or 0),
                        "retryable_error": int(bucket.get("retryable_error") or 0),
                        "skipped": int(bucket.get("skipped") or 0),
                        "prompt_tokens": int(bucket.get("prompt_tokens") or 0),
                        "completion_tokens": int(bucket.get("completion_tokens") or 0),
                        "finish_reasons": _compact_counts(bucket.get("finish_reasons") or {}),
                        "gate_decisions": _compact_counts(bucket.get("gate_decisions") or {}),
                        "deliverable_error_counts": _compact_counts(bucket.get("deliverable_error_counts") or {}),
                        "non_scoreable_completed_reasons": _compact_counts(
                            bucket.get("non_scoreable_completed_reasons") or {}
                        ),
                        "completed_gate_blocked": int(bucket.get("completed_gate_blocked") or 0),
                    }
                )
    return rows


def harvey_score_rows(score_summaries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for score_summary in score_summaries or []:
        score_output_mode = score_summary.get("output_mode") or "released"
        score_namespace = score_summary.get("score_namespace") or "default"
        judge_model = score_summary.get("judge_model") or ""
        by_cmw = score_summary.get("by_context_model_wrapper") or {}
        for context_mode, models in sorted(by_cmw.items()):
            for model, wrappers in sorted((models or {}).items()):
                for wrapper, bucket in sorted((wrappers or {}).items()):
                    runs = int(bucket.get("runs") or 0)
                    all_pass = int(bucket.get("all_pass") or 0)
                    criteria = int(bucket.get("criteria") or 0)
                    passed = int(bucket.get("passed") or 0)
                    rows.append(
                        {
                            "score_output_mode": score_output_mode,
                            "score_namespace": score_namespace,
                            "judge_model": judge_model,
                            "context_mode": context_mode,
                            "model": model,
                            "wrapper": wrapper,
                            "runs": runs,
                            "all_pass": all_pass,
                            "all_pass_rate": _rate(all_pass, runs),
                            "criteria": criteria,
                            "passed": passed,
                            "criterion_pass_rate": _rate(passed, criteria),
                        }
                    )
    return rows


def _load_score_summaries(run_dir: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    paths: list[Path] = []
    for filename in ("scores_summary.json", "scores_summary_review.json"):
        path = run_dir / filename
        if path.exists():
            paths.append(path)
    for path in sorted(run_dir.glob("scores_summary*.json")):
        if path not in paths:
            paths.append(path)
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data.setdefault("output_mode", _infer_output_mode_from_summary_path(path))
            data.setdefault("score_namespace", _infer_score_namespace_from_summary_path(path))
            data.setdefault("judge_model", "")
            summaries.append(data)
    return summaries


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _markdown_tables(generation_rows: list[dict[str, Any]], score_rows: list[dict[str, Any]]) -> str:
    parts = ["# SAGE-Law Experiment Tables", "", "## Generation Status", ""]
    parts.extend(
        _markdown_table(
            generation_rows[:32],
            [
                "context_mode",
                "model",
                "wrapper",
                "runs",
                "completed",
                "scoreable_completed",
                "non_scoreable_completed",
                "retryable_error",
            ],
        )
    )
    parts.extend(["", "## Harvey Criteria Scores", ""])
    parts.extend(
        _markdown_table(
            score_rows[:32],
            [
                "score_output_mode",
                "score_namespace",
                "judge_model",
                "context_mode",
                "model",
                "wrapper",
                "runs",
                "all_pass",
                "all_pass_rate",
                "criterion_pass_rate",
            ],
        )
    )
    return "\n".join(parts).strip() + "\n"


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["No rows available."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def _compact_counts(counts: dict[str, Any]) -> str:
    return ";".join(f"{key}:{counts[key]}" for key in sorted(counts))


def _rate(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator):.4f}" if denominator else "0.0000"


def _infer_output_mode_from_summary_path(path: Path) -> str:
    return "review" if path.name.startswith("scores_summary_review") else "released"


def _infer_score_namespace_from_summary_path(path: Path) -> str:
    stem = path.stem
    if stem in {"scores_summary", "scores_summary_review"}:
        return "default"
    if stem.startswith("scores_summary_review_"):
        return stem[len("scores_summary_review_") :] or "default"
    if stem.startswith("scores_summary_"):
        return stem[len("scores_summary_") :] or "default"
    return "default"
