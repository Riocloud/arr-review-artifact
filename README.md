# SAGE-Law: anonymous review artifact

**Context Is Not Legal Authority: Rubric-Informed Release Control for Legal Work Product**

This artifact accompanies the anonymous submission. It includes
the experiment harness, judge prompt, frozen output-label tables, aggregate
results, and analysis scripts. It supports numerical
reanalysis of supplied labels. It does not support complete reconstruction of
the original provider calls or independent source-aware legal validation.

## Quick start: offline numerical reproduction

Python 3.10 or newer is required. The default analysis uses only the standard
library and needs neither API keys nor the Harvey LAB checkout.

```bash
python3 verify_integrity.py
python3 reproduce.py --output-dir reproduction
```

This checks frozen counts, reproduces the seeded coverage-matched withholding
comparison and task-clustered sensitivity, and reaggregates archived ablation
and receipt-replay outcomes. Logs and regenerated tables go to `reproduction/`;
the supplied evidence files are not overwritten. For an optional figure redraw,
install `requirements-figures.txt` and use `--figures`. The script emits analysis
figure masters; the manuscript uses supplied figure variants with revised
labels/layout, so a redraw is not a byte-identical manuscript-figure build.
The manuscript and its LaTeX sources are maintained separately on Overleaf
and are outside the requested code/data package.

## What is included

| Path | Contents |
| --- | --- |
| `experiments/sage_law_experiment/` | Current checkout snapshot of generation, context, gate, release, and criterion-scoring code |
| `experiments/safety_annotation_lab.py` | Output-only annotation prompt, schema, and collector |
| `experiments/manifests/` | Original 5/80/240-task generation manifests, not the selected audit sample |
| `experiments/results/audits/analysis_tables/` | Frozen per-leaf labels, clustered sensitivity, ablation effects, and receipt replay outcomes |
| `experiments/results/audits/*.json` | Frozen aggregate statistics; one local path was anonymized |
| `scripts/verify_frozen_counts.py` | Read-only numerical checks |
| `docs/` | Evidence boundaries, reproduction instructions, and data dictionary |
| `MANIFEST.json` | SHA-256 inventory for every supplied file except the manifest itself |

The primary automatic judge contributes **704 leaves / 176 complete paired
groups / 132 tasks**. Within the control stratum, the draft-label comparison
uses **101 groups / 89 tasks**: **59/101** exposed and **19/101** unsafe-labeled
exposures. The complete control stratum contains **128 groups / 110 tasks**,
with **82/128** exposed and **30/128** post-gate unsafe exposures; the conditional
rate is **30/82**. These denominators and label surfaces are distinct.

## Evidence boundaries

Sampling is outcome-informed. Automatic judges see condition and gate/trace
metadata and do not see task instructions or sources. The experiment evaluates
a public-rubric-informed lexical/structural proxy controller. It does not
validate the full typed legal-authority contract or establish a causal gate-only
effect. See `docs/EVIDENCE_BOUNDARIES.md` before interpreting the results.

Frozen raw generations, complete judge JSONL records, and source run gate/debt/
receipt artifacts are absent. The human result is an author-reported summary
(356/360 agreement from 60 tasks); raw human annotations, sampling seed/frame,
and leaf-to-task mapping are absent. No end-to-end reproduction is claimed.

## Optional new collection

The public benchmark is available at https://github.com/harveyai/harvey-labs.
Acquire it separately under its upstream terms and configure `HARVEY_LAB_DIR`.
New generation or judging requires provider credentials and may incur costs;
it is separate from frozen-table reproduction. See `docs/REPRODUCTION.md`.

The included runtime is a current source snapshot, not a certified historical
runtime version for the frozen study. The original raw-input analysis scripts
fail before writing when required inputs are absent. Packaging does not alter
the numeric label table, gate policy, or benchmark evaluation boundaries.
