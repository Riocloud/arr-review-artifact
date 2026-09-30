"""Filesystem helpers for Harvey LAB task discovery and MVP manifests."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FAILURE_MODES = (
    "source_support",
    "jurisdiction_governing_law",
    "authority_status",
    "issue_coverage",
    "recommendation_authority",
    "privilege_release_review",
)

MODE_PATTERNS = {
    "source_support": re.compile(
        r"\b(cite|cites|citation|source|document|clause|section|span|"
        r"cross-reference|reference|supporting)\b",
        re.I,
    ),
    "jurisdiction_governing_law": re.compile(
        r"\b(jurisdiction|governing law|forum|venue|delaware|new york|"
        r"california|texas|virginia|federal|state law|regulation|irs|far|"
        r"usc|cfr|court|agency)\b",
        re.I,
    ),
    "authority_status": re.compile(
        r"\b(controlling|persuasive|authority|precedent|case law|statute|"
        r"regulation|overruled|superseded|binding|nonbinding|legal standard)\b",
        re.I,
    ),
    "issue_coverage": re.compile(
        r"\b(issue|issues|red flag|risk|deficien|gap|omitted|identify|"
        r"review|diligence|non-compliance|violation)\b",
        re.I,
    ),
    "recommendation_authority": re.compile(
        r"\b(recommend|recommendation|should|action|closing condition|"
        r"remedy|mitigate|response|appeal|motion|brief|letter)\b",
        re.I,
    ),
    "privilege_release_review": re.compile(
        r"\b(client|memo|memorandum|draft|filing|brief|letter|response|"
        r"confidential|privilege|redact|release|deliverable)\b",
        re.I,
    ),
}


@dataclass(frozen=True)
class HarveyTask:
    task_id: str
    practice_area: str
    title: str
    work_type: str
    tags: list[str]
    deliverables: list[str]
    criteria_count: int
    document_count: int
    document_ext_counts: dict[str, int]
    failure_modes: list[str]


def resolve_lab_dir(lab_dir: str | None = None) -> Path:
    candidate = Path(lab_dir or os.environ.get("HARVEY_LAB_DIR", "")).expanduser()
    if not str(candidate):
        raise SystemExit("Set HARVEY_LAB_DIR or pass --lab-dir")
    if not (candidate / "tasks").is_dir():
        raise SystemExit(f"Harvey LAB tasks directory not found: {candidate / 'tasks'}")
    return candidate.resolve()


def task_id_from_file(tasks_dir: Path, task_json: Path) -> str:
    return str(task_json.parent.relative_to(tasks_dir))


def load_task(task_json: Path, tasks_dir: Path) -> HarveyTask:
    data = json.loads(task_json.read_text())
    task_dir = task_json.parent
    docs = [p for p in (task_dir / "documents").rglob("*") if p.is_file()]
    ext_counts = Counter(p.suffix.lower().lstrip(".") or "no_ext" for p in docs)
    task_id = task_id_from_file(tasks_dir, task_json)
    practice_area = task_id.split("/", 1)[0]
    criteria = data.get("criteria") or []
    deliverables = data.get("deliverables") or {}
    if isinstance(deliverables, dict):
        deliverable_names = list(deliverables.keys())
    else:
        deliverable_names = list(deliverables)
    text = "\n".join(
        [
            data.get("title", ""),
            data.get("work_type", ""),
            " ".join(data.get("tags") or []),
            data.get("instructions", ""),
            " ".join(c.get("title", "") + " " + c.get("match_criteria", "") for c in criteria),
        ]
    )
    modes = [mode for mode, pattern in MODE_PATTERNS.items() if pattern.search(text)]
    if not modes:
        modes = ["issue_coverage"]
    return HarveyTask(
        task_id=task_id,
        practice_area=practice_area,
        title=data.get("title", ""),
        work_type=data.get("work_type", ""),
        tags=list(data.get("tags") or []),
        deliverables=deliverable_names,
        criteria_count=len(criteria),
        document_count=len(docs),
        document_ext_counts=dict(sorted(ext_counts.items())),
        failure_modes=modes,
    )


def discover_tasks(lab_dir: Path) -> list[HarveyTask]:
    tasks_dir = lab_dir / "tasks"
    return [
        load_task(task_json, tasks_dir)
        for task_json in sorted(tasks_dir.rglob("task.json"))
    ]


def summarize(lab_dir: Path, tasks: list[HarveyTask]) -> dict[str, Any]:
    practice_areas = Counter(t.practice_area for t in tasks)
    work_types = Counter(t.work_type for t in tasks)
    failure_modes = Counter(mode for t in tasks for mode in t.failure_modes)
    ext_counts: Counter[str] = Counter()
    for task in tasks:
        ext_counts.update(task.document_ext_counts)
    return {
        "lab_dir": str(lab_dir),
        "task_count": len(tasks),
        "practice_area_count": len(practice_areas),
        "practice_areas": dict(sorted(practice_areas.items())),
        "work_types": dict(sorted(work_types.items())),
        "failure_modes": dict(sorted(failure_modes.items())),
        "document_ext_counts": dict(sorted(ext_counts.items())),
        "total_documents": sum(t.document_count for t in tasks),
        "total_criteria": sum(t.criteria_count for t in tasks),
    }


def build_manifest(lab_dir: Path, limit: int) -> dict[str, Any]:
    tasks = discover_tasks(lab_dir)
    selected: list[HarveyTask] = []
    practice_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    candidates = sorted(
        tasks,
        key=lambda t: (
            -len(t.failure_modes),
            -t.criteria_count,
            -t.document_count,
            t.practice_area,
            t.task_id,
        ),
    )
    while len(selected) < limit and candidates:
        best_idx = 0
        best_score = -10**9
        for idx, task in enumerate(candidates):
            new_modes = sum(1 for mode in task.failure_modes if mode_counts[mode] == 0)
            rare_modes = sum(max(0, 3 - mode_counts[mode]) for mode in task.failure_modes)
            practice_penalty = practice_counts[task.practice_area] * 3
            criteria_bonus = min(task.criteria_count, 80) / 80
            doc_bonus = min(task.document_count, 50) / 100
            score = new_modes * 100 + rare_modes * 10 + criteria_bonus + doc_bonus - practice_penalty
            if score > best_score:
                best_idx = idx
                best_score = score
        task = candidates.pop(best_idx)
        selected.append(task)
        practice_counts[task.practice_area] += 1
        mode_counts.update(task.failure_modes)

    return {
        "schema_version": "sage-law.harvey-manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "repo": "https://github.com/harveyai/harvey-labs",
            "lab_dir": "external_checkout_configured_by_HARVEY_LAB_DIR",
            "task_count_available": len(tasks),
        },
        "selection": {
            "limit": limit,
            "strategy": "greedy_failure_mode_and_practice_area_stratification",
            "practice_area_counts": dict(sorted(practice_counts.items())),
            "failure_mode_counts": dict(sorted(mode_counts.items())),
        },
        "tasks": [asdict(t) for t in selected],
    }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
