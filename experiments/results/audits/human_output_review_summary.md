# Blinded Output-Only Human Concordance Audit

Status: author-confirmed protocol/result summary for the NLLP manuscript. Raw
human annotations and the leaf-to-task mapping are not included in this
checkout; this file must not be treated as a sealed reproduction artifact.

## Protocol

- Reviewer: one legally trained human reviewer; no licensed-attorney status is
  claimed.
- Sampling: 60 randomly selected study tasks. The randomization frame and seed
  are not included in this checkout.
- Reviewed units: 360 associated output leaves.
- Metadata blinding: the reviewer did not see automatic labels,
  wrapper/condition identity, or gate decisions.
- Information boundary: the reviewer did not receive task instructions or
  source materials.
- Output presentation: the checked-in summary does not establish that output
  text was standardized to remove every condition-specific textual cue.

## Result

- Agreement with the automatic output-level assessments: 356/360 leaves
  (98.9%).
- Disagreement: 4/360 leaves (1.1%).

The 360 leaves are nested in 60 tasks. Because the checked-in summary lacks the
leaf-to-task mapping and the distribution of the four disagreements across
tasks, the manuscript reports exact counts and does not present a leaf-level
confidence interval as if all 360 leaves were independent.

## Claim boundary

This audit supports metadata-blind, output-level judgment concordance. It is not
a treatment-blind comparison unless removal of condition-specific output cues
can also be documented. It does not
validate task-instruction compliance, source alignment, issue completeness,
citation or jurisdiction accuracy, substantive legal correctness, gate-error
labels, or trace reconstruction. It is not an attorney validation or a human
inter-rater-reliability study.
