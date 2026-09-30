#!/usr/bin/env python3
"""Read-only checks of the frozen counts used by the 2026-09-20 ARR revision.

No provider calls, regeneration, relabeling, or file writes. This checks numeric
lineage, not the validity of the judge labels or the unavailable human records.
Run null_gate_control.py separately to reproduce the seeded intervals.
"""
import csv
import hashlib
import json
from pathlib import Path


def check(name, actual, expected):
    if actual != expected:
        raise ValueError(f"{name}: got {actual!r}, expected {expected!r}")


def main():
    source = Path(__file__).resolve().parents[1] / "experiments/results/audits"
    labels = source / "analysis_tables/leaf_labels_all_judges.csv"
    digest = hashlib.sha256(labels.read_bytes()).hexdigest()
    check("frozen label table", digest,
          "29a2d5cf404c18392878cfca758b6b875ff73a0801b66056f3658b3192189893")
    with labels.open() as handle:
        rows = list(csv.DictReader(handle))
    keys = [tuple(r[k] for k in ("judge", "task_id", "context_mode",
                                "generated_model", "wrapper")) for r in rows]
    check("unique judge/leaf rows", len(set(keys)), len(keys))
    primary = [r for r in rows if r["judge"] == "mimo-v2.5-pro"]
    check("primary leaves", len(primary), 704)
    check("primary tasks", len({r["task_id"] for r in primary}), 132)
    control = [r for r in primary if r["sample_stratum"] == "control"]
    check("control tasks", len({r["task_id"] for r in control}), 110)
    for wrapper, safe in (("raw_agent", 10), ("rag_agent", 9),
                          ("cbea_lcv_legal", 15), ("sage_law", 56)):
        arm = [r for r in control if r["wrapper"] == wrapper]
        check(f"{wrapper} control n", len(arm), 128)
        check(f"{wrapper} post-gate safe", sum(r["rel_safe"] == "1" for r in arm), safe)
    sage = [r for r in control if r["wrapper"] == "sage_law"]
    exposed = [r for r in sage if r["exposed_artifact"] == "1"]
    check("exposed control", len(exposed), 82)
    check("post-gate exposed unsafe", sum(r["rel_safe"] == "0" for r in exposed), 30)
    check("safe blocked status outputs", sum(r["exposed_artifact"] == "0" and
          r["rel_safe"] == "1" for r in sage), 4)
    draft = [r for r in sage if r["draft_safe"] in {"0", "1"}]
    check("draft-labeled n", len(draft), 101)
    check("draft-labeled tasks", len({r["task_id"] for r in draft}), 89)
    check("draft safe", sum(r["draft_safe"] == "1" for r in draft), 44)
    check("draft exposed", sum(r["exposed_artifact"] == "1" for r in draft), 59)
    check("draft unsafe exposed", sum(r["exposed_artifact"] == "1" and
          r["draft_safe"] == "0" for r in draft), 19)
    for judge, total, n, unsafe in (("mimo-v2.5-pro", 176, 82, 30),
                                   ("deepseek-v4-pro", 40, 19, 5),
                                   ("MiniMax-M3", 32, 14, 4)):
        arm = [r for r in rows if r["judge"] == judge and r["wrapper"] == "sage_law"]
        exp = [r for r in arm if r["exposed_artifact"] == "1"]
        check(f"{judge} total/exposed/unsafe", (len(arm), len(exp),
              sum(r["rel_safe"] == "0" for r in exp)), (total, n, unsafe))
        check(f"{judge} exposed strata", {r["sample_stratum"] for r in exp}, {"control"})
    ablation = json.loads((source / "gate_ablation_stats.json").read_text())
    for name, newly, unsafe in (("no_recommendation_gate", 37, 33),
                               ("no_authority_status_gate", 1, 1),
                               ("no_citation_source_gate", 0, 0),
                               ("no_issue_coverage_gate", 0, 0)):
        matches = [r for r in ablation["gate_ablation"]
                   if r["condition"] == name and r["stratum"] == "all"]
        check(f"{name} single summary", len(matches), 1)
        r = matches[0]
        check(name, (r["newly_exposed_from_full_block_n"],
                     r["newly_exposed_unsafe_n"]), (newly, unsafe))
    print(json.dumps({
        "status": "frozen-count checks passed",
        "source_sha256": digest,
        "post_gate_safe": "56/128 (52 exposed + 4 blocked status outputs)",
        "draft_safe": "44/101 (27 control leaves lack draft labels)",
        "post_gate_unsafe_exposure": "30/128; conditional 30/82",
        "matched_draft_exposure": "59/101; unsafe 19/101; 89 tasks",
        "random_gate_exact_expectation": (59 / 101) * (57 / 101),
        "limits": "No independent validation of judge labels or human audit records."
    }, indent=2))


if __name__ == "__main__":
    main()
