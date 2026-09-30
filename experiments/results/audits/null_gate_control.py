"""Coverage-matched abstention control for the SAGE-Law release contrast.

The headline exposure-aware unsafe-release rate is the conjunction of exposure
and an unsafe label, so it falls whenever a controller abstains. The ungated
baselines have exposure fixed at 1.0 by construction, so the marginal contrast
cannot separate routing quality from withholding.

This script supplies the missing null: hold each leaf's review-draft safety
label fixed and permute *which* leaves are exposed, matching SAGE-Law's own
availability. The gap between the observed rate and the permutation mean is the
share attributable to gate discrimination rather than to abstention.

Safety basis follows gate_ablation_analysis.py: a leaf counts as an unsafe
exposure when its Mimo v2.5-pro review-draft label is unsafe. Restricted to the
control stratum leaves that carry such a label; denominators are printed.

No provider calls. Reads only the frozen label table.

Emits Appendix Table 9 of the NLLP manuscript.
"""

import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

LEAF_LABELS = (
    Path(__file__).parent / "analysis_tables" / "leaf_labels_all_judges.csv"
)
PRIMARY_JUDGE = "mimo-v2.5-pro"
SEED = 20260808
N_PERM = 20_000
N_BOOT = 2_000


def _bool(value):
    return value.strip().lower() in ("true", "1")


def _tri(value):
    """True / False / None, keeping missing labels distinct from False."""
    v = value.strip().lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return None


def load_control_leaves():
    with open(LEAF_LABELS) as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["judge"] == PRIMARY_JUDGE
            and r["wrapper"] == "sage_law"
            and r["sample_stratum"] == "control"
        ]
    leaves = []
    for r in rows:
        draft_safe = _tri(r["draft_safe"])
        leaves.append(
            {
                "task": r["task_id"],
                "exposed": _bool(r["exposed_artifact"]),
                # None where the leaf carries no review-draft label
                "unsafe": None if draft_safe is None else (not draft_safe),
            }
        )
    return leaves


def main():
    leaves = load_control_leaves()
    annotated = [leaf for leaf in leaves if leaf["unsafe"] is not None]

    n_all = len(leaves)
    n_exposed_all = sum(1 for leaf in leaves if leaf["exposed"])
    m = len(annotated)
    m_exposed = sum(1 for leaf in annotated if leaf["exposed"])

    print(f"control SAGE-Law leaves          : {n_all}")
    print(
        f"  availability (all leaves)      : "
        f"{n_exposed_all}/{n_all} = {n_exposed_all / n_all:.3f}"
    )
    print(f"  carrying a review-draft label  : {m} (unlabeled: {n_all - m})")
    print(
        f"  availability (labeled subset)  : "
        f"{m_exposed}/{m} = {m_exposed / m:.3f}"
    )

    unsafe_flags = [leaf["unsafe"] for leaf in annotated]
    base_rate = sum(unsafe_flags) / m
    observed_n = sum(1 for leaf in annotated if leaf["exposed"] and leaf["unsafe"])
    observed = observed_n / m

    print(f"\ncontent-unsafe base rate         : {base_rate:.3f}")
    print(f"SAGE-Law observed unsafe exposure: {observed_n}/{m} = {observed:.3f}")

    # Permutation null: same number exposed, chosen without regard to safety.
    random.seed(SEED)
    null = []
    for _ in range(N_PERM):
        picked = random.sample(range(m), m_exposed)
        null.append(sum(1 for i in picked if unsafe_flags[i]) / m)
    null.sort()
    null_mean = statistics.mean(null)
    lo = null[int(0.025 * N_PERM)]
    hi = null[int(0.975 * N_PERM)]
    p_value = sum(1 for v in null if v <= observed) / N_PERM

    print(
        f"blind gate, matched coverage     : {null_mean:.3f} "
        f"[{lo:.3f}, {hi:.3f}]  ({N_PERM:,} permutations)"
    )
    print(f"  one-sided p (null <= observed) : {p_value:.5f}")
    print(f"DISCRIMINATION MARGIN            : {null_mean - observed:.3f}")

    # Task-clustered bootstrap on the margin, matching the manuscript's
    # sensitivity convention (resample tasks, keep every group per task).
    by_task = defaultdict(list)
    for leaf in annotated:
        by_task[leaf["task"]].append(leaf)
    tasks = list(by_task)

    random.seed(SEED)
    margins = []
    for _ in range(N_BOOT):
        sample = [
            leaf
            for task in random.choices(tasks, k=len(tasks))
            for leaf in by_task[task]
        ]
        k = len(sample)
        exposed = sum(1 for leaf in sample if leaf["exposed"])
        if k == 0 or exposed == 0:
            continue
        actual = sum(1 for leaf in sample if leaf["exposed"] and leaf["unsafe"]) / k
        base = sum(1 for leaf in sample if leaf["unsafe"]) / k
        margins.append(exposed / k * base - actual)
    margins.sort()

    print(
        f"  task-clustered 95% CI          : "
        f"[{margins[int(0.025 * len(margins))]:.3f}, "
        f"{margins[int(0.975 * len(margins))]:.3f}]  "
        f"({len(tasks)} tasks, {N_BOOT:,} resamples, seed {SEED})"
    )
    print(
        "\nThis is a post-hoc replay over frozen drafts, not a live causal "
        "ablation, and the control stratum is outcome-informed."
    )


if __name__ == "__main__":
    main()
