"""Reaggregate archived outcomes, without reconstructing absent raw inputs."""
import csv
import json
from collections import defaultdict
from pathlib import Path
from gate_ablation_analysis import summarize_effects

HERE = Path(__file__).resolve().parent
TABLES = HERE / "analysis_tables"


def main():
    effects = list(csv.DictReader((TABLES / "gate_ablation_leaf_effects.csv").open()))
    integer_fields = {"actual_exposed", "counterfactual_exposed", "newly_exposed_from_full_block",
                      "safety_known", "unsafe_exposure", "newly_exposed_safe", "newly_exposed_unsafe"}
    for row in effects:
        for field in integer_fields:
            if row[field] != "":
                row[field] = int(row[field])
    summary = summarize_effects(effects)
    frozen = json.loads((HERE / "gate_ablation_stats.json").read_text())
    if summary != frozen["gate_ablation"]:
        raise ValueError("Archived ablation effects do not match supplied aggregate statistics")
    grouped = defaultdict(list)
    for row in csv.DictReader((TABLES / "receipt_replay_type_confusion.csv").open()):
        grouped[row["test"]].append(row)
    replay = []
    for name, rows in sorted(grouped.items()):
        n = len(rows)
        passed = sum(int(r["passed"]) for r in rows)
        replay.append({"test": name, "n": n,
                       "expected_accept_n": sum(int(r["expected_accept"]) for r in rows),
                       "actual_accept_n": sum(int(r["actual_accept"]) for r in rows),
                       "passed_n": passed, "pass_rate": round(passed / n, 4)})
    if replay != frozen["receipt_replay_type_confusion"]:
        raise ValueError("Archived receipt outcomes do not match supplied aggregate statistics")
    for name, rows in [("gate_ablation_reaggregated.csv", summary),
                       ("receipt_replay_reaggregated.csv", replay)]:
        with (TABLES / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"status": "archived outcome aggregates match", "ablation_rows": len(effects),
                      "receipt_rows": sum(len(v) for v in grouped.values()),
                      "limit": "No rerun of original gate decisions, receipt validators, or legal annotations."}, indent=2))


if __name__ == "__main__":
    main()
