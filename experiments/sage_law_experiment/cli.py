"""CLI for SAGE-Law Harvey LAB experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .authority import WRAPPERS
from .dry_run import run_dry_manifest
from .grid import build_run_plan, parse_csv, write_jsonl
from .harvey import build_manifest, discover_tasks, resolve_lab_dir, summarize, write_json
from .harvey_scoring import MiniMaxJudge, json_progress, score_discovered_runs
from .metrics import summarize_artifacts, summarize_provider_responses
from .minimax import DEFAULT_MINIMAX_MODELS, DEFAULT_REQUEST_TIMEOUT_SECONDS, run_minimax_smoke
from .paper_tables import write_paper_tables
from .run_status import summarize_run_status


def manifest_task_ids(manifest_path: str | None, task_limit: int | None = None) -> set[str] | None:
    if not manifest_path:
        return None
    manifest = json.loads(Path(manifest_path).read_text())
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"{manifest_path}: expected manifest with a tasks list")
    if task_limit is not None:
        tasks = tasks[:task_limit]
    task_ids = {str(task.get("task_id") or "") for task in tasks if isinstance(task, dict)}
    task_ids.discard("")
    return task_ids


def cmd_inspect(args: argparse.Namespace) -> None:
    lab_dir = resolve_lab_dir(args.lab_dir)
    tasks = discover_tasks(lab_dir)
    print(json.dumps(summarize(lab_dir, tasks), indent=2, sort_keys=True))


def cmd_build_manifest(args: argparse.Namespace) -> None:
    lab_dir = resolve_lab_dir(args.lab_dir)
    manifest = build_manifest(lab_dir, args.limit)
    out = Path(args.out)
    write_json(out, manifest)
    print(json.dumps({
        "out": str(out),
        "task_count": len(manifest["tasks"]),
        "practice_area_counts": manifest["selection"]["practice_area_counts"],
        "failure_mode_counts": manifest["selection"]["failure_mode_counts"],
    }, indent=2, sort_keys=True))


def cmd_dry_run(args: argparse.Namespace) -> None:
    wrappers = tuple(args.wrappers.split(",")) if args.wrappers else WRAPPERS
    summary = run_dry_manifest(Path(args.manifest), Path(args.out), wrappers)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_plan_grid(args: argparse.Namespace) -> None:
    models = parse_csv(args.models)
    wrappers = parse_csv(args.wrappers) if args.wrappers else WRAPPERS
    rows = build_run_plan(Path(args.manifest), models, wrappers)
    out = Path(args.out)
    write_jsonl(out, rows)
    planned_models = list(dict.fromkeys(row["model"] for row in rows))
    print(json.dumps({
        "out": str(out),
        "task_count": len({row["task_id"] for row in rows}),
        "models": planned_models,
        "wrappers": list(wrappers),
        "planned_runs": len(rows),
    }, indent=2, sort_keys=True))


def cmd_summarize_artifacts(args: argparse.Namespace) -> None:
    summary = summarize_artifacts(Path(args.run_dir))
    if args.out:
        write_json(Path(args.out), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_summarize_provider(args: argparse.Namespace) -> None:
    summary = summarize_provider_responses(Path(args.run_dir))
    if args.out:
        write_json(Path(args.out), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_summarize_run_status(args: argparse.Namespace) -> None:
    summary = summarize_run_status(Path(args.run_dir), task_ids=manifest_task_ids(args.manifest, args.task_limit))
    if args.out:
        write_json(Path(args.out), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_minimax_smoke(args: argparse.Namespace) -> None:
    models = parse_csv(args.models)
    wrappers = parse_csv(args.wrappers)
    summary = run_minimax_smoke(
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out),
        models=models,
        wrappers=wrappers,
        task_limit=args.task_limit,
        max_completion_tokens=args.max_completion_tokens,
        temperature=args.temperature,
        concurrency=args.concurrency,
        retry_on_length=not args.no_retry_on_length,
        length_retry_tokens=args.length_retry_tokens,
        request_timeout=args.request_timeout,
        lab_dir=resolve_lab_dir(args.lab_dir) if args.lab_dir or args.use_lab_context else None,
        max_documents=args.max_documents,
        max_document_chars=args.max_document_chars,
        max_context_chars=args.max_context_chars,
        run_id=args.run_id,
        resume=args.resume,
        context_mode=args.context_mode,
        max_activated_chunks=args.max_activated_chunks,
        chunk_chars=args.chunk_chars,
        leaf_timeout=args.leaf_timeout,
        split_first=args.split_first,
    )
    if args.summary_out:
        write_json(Path(args.summary_out), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_score_minimax(args: argparse.Namespace) -> None:
    judge = MiniMaxJudge(
        model=args.judge_model,
        max_completion_tokens=args.max_completion_tokens,
        temperature=args.temperature,
        request_timeout=args.request_timeout,
        retries=args.retries,
        retry_sleep_seconds=args.retry_sleep_seconds,
        reasoning_split=args.reasoning_split,
    )
    summary = score_discovered_runs(
        run_dir=Path(args.run_dir),
        lab_dir=resolve_lab_dir(args.lab_dir),
        judge=judge,
        judge_model=args.judge_model,
        parallel_runs=args.parallel_runs,
        parallel_criteria=args.parallel_criteria,
        run_limit=args.run_limit,
        max_output_chars=args.max_output_chars,
        resume=not args.no_resume,
        progress=json_progress,
        context_modes=parse_csv(args.context_modes) if args.context_modes else None,
        models=parse_csv(args.score_models) if args.score_models else None,
        wrappers=parse_csv(args.score_wrappers) if args.score_wrappers else None,
        statuses=parse_csv(args.score_statuses) if args.score_statuses else None,
        task_ids=manifest_task_ids(args.manifest, args.task_limit),
        output_mode=args.scoring_output_mode,
        criteria_batch_size=args.criteria_batch_size,
        score_namespace=args.score_namespace,
    )
    if args.out:
        write_json(Path(args.out), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_write_paper_tables(args: argparse.Namespace) -> None:
    summary = write_paper_tables(
        Path(args.run_dir),
        Path(args.out_dir),
        task_ids=manifest_task_ids(args.manifest, args.task_limit),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sage-law-exp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    inspect = sub.add_parser("inspect", help="Inspect Harvey LAB task corpus")
    inspect.add_argument("--lab-dir", default=None)
    inspect.set_defaults(func=cmd_inspect)

    manifest = sub.add_parser("build-manifest", help="Build a stratified task manifest")
    manifest.add_argument("--lab-dir", default=None)
    manifest.add_argument("--limit", type=int, default=80)
    manifest.add_argument("--out", required=True)
    manifest.set_defaults(func=cmd_build_manifest)

    dry = sub.add_parser("dry-run", help="Write structural SAGE-Law artifacts without model calls")
    dry.add_argument("--manifest", required=True)
    dry.add_argument("--out", required=True)
    dry.add_argument(
        "--wrappers",
        default=",".join(WRAPPERS),
        help=f"Comma-separated wrappers. Valid: {','.join(WRAPPERS)}",
    )
    dry.set_defaults(func=cmd_dry_run)

    plan = sub.add_parser("plan-grid", help="Write the task x model x wrapper run grid")
    plan.add_argument("--manifest", required=True)
    plan.add_argument("--models", required=True, help="Comma-separated model labels")
    plan.add_argument("--wrappers", default=",".join(WRAPPERS))
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=cmd_plan_grid)

    summarize_run = sub.add_parser("summarize-artifacts", help="Summarize artifact/gate/debt outputs")
    summarize_run.add_argument("--run-dir", required=True)
    summarize_run.add_argument("--out", default=None)
    summarize_run.set_defaults(func=cmd_summarize_artifacts)

    summarize_provider = sub.add_parser("summarize-provider", help="Summarize provider responses and token use")
    summarize_provider.add_argument("--run-dir", required=True)
    summarize_provider.add_argument("--out", default=None)
    summarize_provider.set_defaults(func=cmd_summarize_provider)

    summarize_status = sub.add_parser("summarize-run-status", help="Summarize status.json files in a run tree")
    summarize_status.add_argument("--run-dir", required=True)
    summarize_status.add_argument("--out", default=None)
    summarize_status.add_argument("--manifest", default=None, help="Optional manifest used to filter task ids")
    summarize_status.add_argument("--task-limit", type=int, default=None)
    summarize_status.set_defaults(func=cmd_summarize_run_status)

    minimax = sub.add_parser("minimax-smoke", help="Run live MiniMax generation with SAGE-Law artifacts")
    minimax.add_argument("--manifest", required=True)
    minimax.add_argument("--out", default="runs/minimax-smoke")
    minimax.add_argument("--models", default=",".join(DEFAULT_MINIMAX_MODELS))
    minimax.add_argument("--wrappers", default="raw_agent,sage_law")
    minimax.add_argument("--task-limit", type=int, default=1)
    minimax.add_argument("--max-completion-tokens", type=int, default=4096)
    minimax.add_argument("--temperature", type=float, default=0.2)
    minimax.add_argument("--concurrency", type=int, default=1)
    minimax.add_argument("--length-retry-tokens", type=int, default=8192)
    minimax.add_argument("--request-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    minimax.add_argument(
        "--leaf-timeout",
        type=float,
        default=None,
        help="Optional wall-clock timeout per leaf run; timed-out leaves are marked retryable.",
    )
    minimax.add_argument("--no-retry-on-length", action="store_true")
    minimax.add_argument("--lab-dir", default=None)
    minimax.add_argument("--use-lab-context", action="store_true")
    minimax.add_argument("--max-documents", type=int, default=12)
    minimax.add_argument("--max-document-chars", type=int, default=6000)
    minimax.add_argument("--max-context-chars", type=int, default=80000)
    minimax.add_argument("--context-mode", choices=("activated", "raw_full", "full"), default="activated")
    minimax.add_argument("--max-activated-chunks", type=int, default=16)
    minimax.add_argument("--chunk-chars", type=int, default=1200)
    minimax.add_argument("--run-id", default=None, help="Reuse a specific run id under --out")
    minimax.add_argument("--resume", action="store_true", help="Skip completed task/model/wrapper artifacts")
    minimax.add_argument(
        "--split-first",
        action="store_true",
        help="Generate each expected deliverable separately before attempting a bundled response.",
    )
    minimax.add_argument("--summary-out", default=None, help="Optional path for the machine-readable run summary")
    minimax.set_defaults(func=cmd_minimax_smoke)

    score = sub.add_parser("score-minimax", help="Score local run leaves with full Harvey criteria using MiniMax judge")
    score.add_argument("--run-dir", required=True)
    score.add_argument("--lab-dir", default=None)
    score.add_argument("--judge-model", default="MiniMax-M2.7-highspeed")
    score.add_argument("--parallel-runs", type=int, default=1)
    score.add_argument("--parallel-criteria", type=int, default=6)
    score.add_argument("--criteria-batch-size", type=int, default=1)
    score.add_argument(
        "--score-namespace",
        default=None,
        help="Optional namespace for judge-specific score/cache files, e.g. primary_external or same_family_sensitivity.",
    )
    score.add_argument("--run-limit", type=int, default=None)
    score.add_argument("--max-output-chars", type=int, default=120000)
    score.add_argument("--max-completion-tokens", type=int, default=2048)
    score.add_argument("--temperature", type=float, default=0.0)
    score.add_argument("--request-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    score.add_argument("--retries", type=int, default=3)
    score.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    score.add_argument("--reasoning-split", action="store_true")
    score.add_argument("--no-resume", action="store_true", help="Re-score criteria even if caches/scores exist")
    score.add_argument("--context-modes", default=None, help="Comma-separated context modes to score")
    score.add_argument("--score-models", default=None, help="Comma-separated generated model names to score")
    score.add_argument("--score-wrappers", default=None, help="Comma-separated wrappers to score")
    score.add_argument("--score-statuses", default="completed", help="Comma-separated run statuses to score")
    score.add_argument("--manifest", default=None, help="Optional manifest used to filter task ids")
    score.add_argument("--task-limit", type=int, default=None)
    score.add_argument(
        "--scoring-output-mode",
        choices=("released", "review"),
        default="released",
        help="Score release-gated output/ or review_output/ drafts.",
    )
    score.add_argument("--out", default=None)
    score.set_defaults(func=cmd_score_minimax)

    tables = sub.add_parser("write-paper-tables", help="Write CSV/Markdown tables from run status and scores")
    tables.add_argument("--run-dir", required=True)
    tables.add_argument("--out-dir", required=True)
    tables.add_argument("--manifest", default=None, help="Optional manifest used to filter generation rows")
    tables.add_argument("--task-limit", type=int, default=None)
    tables.set_defaults(func=cmd_write_paper_tables)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
