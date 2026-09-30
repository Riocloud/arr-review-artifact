#!/usr/bin/env python3
"""Task-clustered paired sensitivity analysis over the frozen leaf table.

This script needs no provider payloads and makes no API calls. It reads the
tracked primary-judge leaf table, pairs conditions within task x model x
context groups, then resamples distinct tasks while retaining all groups that
belong to each sampled task. Point estimates remain group-weighted.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT = HERE / "analysis_tables" / "leaf_labels_all_judges.csv"
OUTPUT = HERE / "analysis_tables" / "paired_deltas_mimo_task_clustered.csv"
PRIMARY_JUDGE = "mimo-v2.5-pro"
SAGE = "sage_law"
BASELINES = ("raw_agent", "rag_agent", "cbea_lcv_legal")
METRICS = (
    "rel_safe",
    "unsafe_release",
    "false_release",
    "rel_mat_err",
    "rel_unsup_claims",
    "rel_overcommit",
    "rel_unsup_rec",
    "rel_issue_omit",
    "rel_util",
    "rel_cov",
    "exposed_artifact",
)
STRATA = ("control", "high_risk", "all")
SEED = 20260808
N_BOOT = 2000


def number(value: str) -> float | None:
    return None if value == "" else float(value)


def percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def main() -> int:
    rows = [
        row
        for row in csv.DictReader(INPUT.open())
        if row["judge"] == PRIMARY_JUDGE
    ]
    groups: dict[tuple[str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        key = (row["task_id"], row["context_mode"], row["generated_model"])
        groups[key][row["wrapper"]] = row

    rng = random.Random(SEED)
    output_rows = []
    for stratum in STRATA:
        for baseline in BASELINES:
            for metric in METRICS:
                by_task: dict[str, list[float]] = defaultdict(list)
                sage_values: list[float] = []
                base_values: list[float] = []
                for key, conditions in groups.items():
                    if SAGE not in conditions or baseline not in conditions:
                        continue
                    sage_row = conditions[SAGE]
                    if stratum != "all" and sage_row["sample_stratum"] != stratum:
                        continue
                    sage_value = number(sage_row[metric])
                    base_value = number(conditions[baseline][metric])
                    if sage_value is None or base_value is None:
                        continue
                    by_task[key[0]].append(sage_value - base_value)
                    sage_values.append(sage_value)
                    base_values.append(base_value)

                task_ids = sorted(by_task)
                n_groups = sum(len(values) for values in by_task.values())
                observed = (
                    sum(sum(values) for values in by_task.values()) / n_groups
                    if n_groups
                    else None
                )
                boots: list[float] = []
                if task_ids:
                    for _ in range(N_BOOT):
                        sampled_tasks = [
                            task_ids[rng.randrange(len(task_ids))] for _ in task_ids
                        ]
                        deltas = [
                            delta
                            for task_id in sampled_tasks
                            for delta in by_task[task_id]
                        ]
                        boots.append(sum(deltas) / len(deltas))
                    boots.sort()
                lo = percentile(boots, 0.025) if boots else None
                hi = percentile(boots, 0.975) if boots else None
                output_rows.append(
                    {
                        "stratum": stratum,
                        "metric": metric,
                        "baseline": baseline,
                        "n_groups": n_groups,
                        "n_tasks": len(task_ids),
                        "sage_law_mean": round(sum(sage_values) / len(sage_values), 4)
                        if sage_values
                        else None,
                        "baseline_mean": round(sum(base_values) / len(base_values), 4)
                        if base_values
                        else None,
                        "delta_sage_minus_base": round(observed, 4)
                        if observed is not None
                        else None,
                        "ci_lo": round(lo, 4) if lo is not None else None,
                        "ci_hi": round(hi, 4) if hi is not None else None,
                        "interval_excludes_zero": bool(
                            lo is not None and hi is not None and (lo > 0 or hi < 0)
                        ),
                        "bootstrap_cluster": "task_id",
                        "n_boot": N_BOOT,
                        "seed": SEED,
                    }
                )

    fields = list(output_rows[0])
    with OUTPUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"wrote {OUTPUT} ({len(output_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
