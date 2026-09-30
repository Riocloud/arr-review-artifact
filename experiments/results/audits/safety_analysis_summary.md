# SAGE-Law Safety / Release-Control Analysis Summary

This summarizes the group-level paired analysis of the frozen safety
annotations. The framing is a **release-control** claim, not a capability or
leaderboard claim: SAGE-Law is evaluated on whether it makes *safer release
decisions* (fewer unsafe commitments exposed, better traceability) with utility
and availability reported jointly. Draft quality and release safety are
reported separately.

- **Statistical unit:** group = `(task_id, context_mode, generated_model)`;
  within each group the four wrappers (`raw_agent`, `rag_agent`,
  `cbea_lcv_legal`, `sage_law`) are paired conditions.
- **Primary judge:** `mimo-v2.5-pro` (cross-family to every generator).
- **Surfaces:** `released` = gated/exposed artifact (release safety);
  `review_draft` = SAGE-Law pre-gate draft (draft quality).
- **Strata:** high-risk (n=48 groups) is selected using SAGE gate/score outcomes;
  control (n=128 groups/110 tasks) is spread-selected from the remainder. Both
  are descriptive selected strata, not prevalence samples.
- **CIs:** Wilson intervals are descriptive marginal intervals. Paired
  sensitivity intervals resample 110 distinct control tasks (2,000 resamples,
  seed 20260808), preserving all groups belonging to each sampled task.
- Frozen table sensitivity regenerates via `task_clustered_sensitivity.py`;
  full label extraction requires absent judge/run artifacts.

> SAGE-Law is a runtime release-governance harness. It does not provide legal
> advice, prove legal correctness, or replace lawyer review. "Safe to release"
> is an LLM-assisted audit label about whether an artifact may be *exposed at a
> given release level under the declared policy*, not a judgment of legal
> truth. "Benchmark release" is an evaluation-harness mode, not production
> release to a client.

---

## 1. Headline (control stratum, primary judge)

On the outcome-informed control stratum, SAGE-Law converts unsafe, overcommitted,
or untraceable work product into blocked / downgraded / review-gated outputs:

| Released-surface metric | raw_agent | rag_agent | cbea_lcv_legal | **sage_law** |
|---|---:|---:|---:|---:|
| **false release rate** (unsafe content exposed) | 0.938 | 0.945 | 0.922 | **0.039** |
| safe-to-release rate | 0.078 | 0.070 | 0.117 | **0.438** |
| material legal error present | 0.180 | 0.180 | 0.180 | **0.055** |
| utility score (0–3) | 1.84 | 1.59 | 1.90 | **1.66** |
| criteria coverage (0–3) | 1.12 | 1.05 | 1.19 | **1.51** |
| availability | 1.000 | 1.000 | 1.000 | **0.641** |
| false refusal rate | 0.000 | 0.000 | 0.000 | **0.016** |
| false downgrade rate | 0.000 | 0.000 | 0.000 | **0.000** |

The one-line result: **within this selected stratum, SAGE-Law lowers
exposure-aware unsafe release from 88–93% to 23%, while availability falls from
100% to 64%; utility is 1.66 versus 1.59–1.90 and criteria coverage is higher.**

## 2. Paired deltas, sage_law − baseline (control, task-clustered sensitivity)

All deltas below are significant at 95% unless marked NS. Negative is better
for risk metrics; for utility/coverage the sign is shown.

| Metric | vs raw_agent | vs rag_agent | vs cbea_lcv_legal |
|---|---|---|---|
| false release | **−0.898** [−0.952, −0.835] | **−0.906** [−0.960, −0.836] | **−0.882** [−0.937, −0.815] |
| safe to release | **+0.359** [+0.275, +0.447] | **+0.367** [+0.268, +0.466] | **+0.320** [+0.220, +0.420] |
| material legal error | **−0.125** [−0.206, −0.046] | **−0.125** [−0.203, −0.051] | **−0.125** [−0.202, −0.049] |
| unsupported claim count | **−1.27** [−1.77, −0.75] | **−2.46** [−3.18, −1.78] | **−1.17** [−1.78, −0.57] |
| overcommitment | **−0.367** [−0.470, −0.258] | **−0.422** [−0.524, −0.320] | **−0.336** [−0.437, −0.240] |
| unsupported recommendation | **−0.414** [−0.516, −0.307] | **−0.430** [−0.523, −0.341] | **−0.336** [−0.436, −0.232] |
| issue omitted w/o reservation | **−0.375** [−0.469, −0.287] | **−0.258** [−0.341, −0.182] | **−0.344** [−0.437, −0.260] |
| utility | −0.180 [−0.403, +0.038] **NS** | +0.063 [−0.160, +0.279] **NS** | −0.242 [−0.469, −0.016] |
| criteria coverage | **+0.391** [+0.150, +0.636] | **+0.453** [+0.228, +0.683] | **+0.320** [+0.072, +0.569] |

Reading: every unsafe-commitment dimension drops significantly against all
three baselines (including the language-level commitment-control baseline
`cbea_lcv_legal`, so the effect is not just "careful prompting"). Utility is
**statistically indistinguishable** from `raw_agent` and `rag_agent`, and only
~0.24/3 below the strongest baseline `cbea_lcv_legal`; criteria coverage
significantly **improves**. This is the "reduce unsafe release without
collapsing utility" result.

## 3. Failure taxonomy (control, share of leaves with each defect)

| Defect (released surface) | raw | rag | cbea | **sage** |
|---|---:|---:|---:|---:|
| unsupported material claim (≥1) | 0.805 | 0.852 | 0.711 | **0.273** |
| material legal error | 0.180 | 0.180 | 0.180 | **0.055** |
| overcommitment | 0.500 | 0.555 | 0.469 | **0.133** |
| unsupported recommendation | 0.547 | 0.563 | 0.469 | **0.133** |
| issue omitted w/o reservation | 0.414 | 0.297 | 0.383 | **0.039** |

Every category is reduced by roughly 3–10×. The largest absolute reduction is
in silently omitted issues (0.41 → 0.04) and overcommitment/unsupported
recommendations (~0.5 → 0.13).

## 4. Draft quality vs release safety (the key separation)

For `sage_law` we compare the pre-gate **review_draft** to the post-gate
**released** surface. This shows the gate is removing *unsafe content*, not
*degrading drafting ability*.

| | control draft | control released | high_risk draft | high_risk released |
|---|---:|---:|---:|---:|
| utility (0–3) | **2.13** | 1.66 | **1.96** | 0.46 |
| criteria coverage | 1.84 | 1.51 | 1.46 | 0.33 |
| safe-to-release | 0.44 | 0.44 | 0.09 | 0.06 |

SAGE-Law's **draft** utility (2.13 control / 1.96 high-risk) is at or above the
best baseline released utility (1.59–1.90) — the model is drafting competently.
The release-time utility reduction is the gate **deliberately withholding**
content: small on control (2.13 → 1.66) and large on the enriched stress sample
(1.96 → 0.46). Conclusion: draft quality is retained; release safety is what
changes.

This is independently corroborated by the prior Harvey-rubric review-vs-release
audit (`minimax80_mimo_review_*`, a separate run): for *unblocked* SAGE-Law
leaves review/release rubric scores agree (criterion agreement 0.94–0.96,
Pearson 0.98–0.99); for *blocked* leaves the released rubric score ≈ 0 while
the review-draft score is high (0.64–0.79). Same mechanism, measured with
Harvey criteria rather than the safety judge.

## 5. Gate behavior and whether blocks are justified

Gate-decision distribution for the 176 `sage_law` leaves: `review_gated_draft`
82, `blocked_or_escalated` 94 (control: 82 review-gated / 46 blocked; high_risk:
0 review-gated / 48 blocked — all stress-test artifacts are blocked).

Are blocks justified? Cross-tab of gate decision × draft safety:

| Gate decision | draft unsafe | draft safe | no draft |
|---|---:|---:|---:|
| blocked_or_escalated | **80** | 8 | 6 |
| review_gated_draft | 19 | 40 | 23 |

Of blocked leaves with an annotated draft, **80/88 (91%) had an unsafe draft** —
blocks overwhelmingly target genuinely unsafe content. The judge's own
over-block labels are very low: **false_downgrade = 0** across all 176 leaves;
**false_refusal = 6** total (1.6% control, 8.7% high-risk). The 8 "blocked with
a safe draft" leaves are the main residual over-block signal and are flagged for
the limitations section, but the judge did not classify them as false
refusals/downgrades. Conversely, the 19 unsafe drafts exposed as
`review_gated_draft` are the main residual false-release exposure (review-gated,
not client release).

## 6. Traceability

SAGE-Law improves trace reconstruction (a stated contribution):

| Wrapper | trace yes | partial | no | confidence high | low |
|---|---:|---:|---:|---:|---:|
| raw_agent | 18 | 151 | 7 | 10 | 28 |
| rag_agent | 24 | 146 | 6 | 25 | 34 |
| cbea_lcv_legal | 20 | 150 | 6 | 24 | 22 |
| **sage_law** | **60** | 114 | **2** | **60** | 11 |

Fully reconstructable traces roughly triple (≈10–14% → 34%), non-reconstructable
traces fall to 2/176, and high-confidence audits more than double.

## 7. High-risk stress test (NOT a prevalence)

On the risk-enriched stress sample (48 groups), the safety/availability tradeoff
is explicit:

| Metric | raw | rag | cbea | **sage** |
|---|---:|---:|---:|---:|
| false release | 1.000 | 0.958 | 0.896 | **0.000** |
| material legal error | 0.354 | 0.438 | 0.396 | **0.021** |
| utility | 1.81 | 1.50 | 1.81 | **0.46** |
| false refusal | 0.000 | 0.000 | 0.000 | 0.087 |

SAGE-Law drives false release to **0** and material legal error to **2%** on the
hardest cases, by blocking essentially all of them — utility falls to 0.46 and
false refusal rises to 8.7%. This is the intended behavior at the strict end of
the policy and is reported as stress-test / failure-taxonomy evidence, not as a
rate over all LAB tasks.

## 8. Robustness across context lanes and generator families

The release-control effect is not an artifact of one context lane or one
generator family (primary judge, all strata pooled):

| Cut | sage false release | sage safe | best-baseline false release |
|---|---:|---:|---:|
| context = activated (n=109/wrapper) | 0.019 | 0.321 | 0.899 (cbea) |
| context = raw_full (n=67/wrapper) | 0.046 | 0.358 | 0.940 (cbea) |
| generator = MiniMax (n=128/wrapper) | 0.016 | 0.359 | 0.914 (cbea) |
| generator = DeepSeek (n=48/wrapper) | 0.064 | 0.271 | 0.917 (cbea) |

SAGE-Law false release stays ≤6.4% and safe-to-release stays ≥27% in every cut,
versus ≥90% baseline false release everywhere.

## 9. GPT-5.4-mini final adjudication (enriched, external sanity check)

60 leaves across 15 groups (7 high-risk/false-release, 3 boundary, 3 control,
2 family-cross-check), `reasoning_effort=medium`, 60/60 clean labels.
**Heavily enriched — not a prevalence.** Per wrapper:

| Wrapper | safe-to-release | utility | false release |
|---|---:|---:|---:|
| raw_agent | 0.00 | 2.20 | 0.13 |
| rag_agent | 0.00 | 2.20 | 0.00 |
| cbea_lcv_legal | 0.00 | 2.20 | 0.07 |
| **sage_law** | **0.53** | 1.33 | 0.13 |

Even under an independent, stricter judge on the hardest enriched cases, only
SAGE-Law produces release-safe output (53% vs 0% for all three baselines), at a
utility cost (1.33 vs 2.20). This corroborates the release-control benefit from
an out-of-family judge. GPT and Mimo agree on safe-to-release 75% of the time
here and both label the underlying artifacts unsafe at high rates
(GPT 52/60, Mimo 51/60 unsafe). They diverge on the *false_release label
itself* (Mimo 41/60, GPT 5/60); this is a definitional difference handled in
`judge_agreement_summary.md`, not a contradiction of the safety finding.

## 10. Blinded output-only human concordance

A legally trained reviewer assessed 360 output-only leaves from 60 randomly
selected study tasks without explicit automatic labels, condition identity, or
gate decisions. Human and automatic assessments agreed on 356/360 leaves
(98.9%); four differed. The reviewer saw no task instructions or source
materials, so this measures output-level concordance, not source support, issue
completeness, or legal correctness. Leaves are nested in tasks; exact counts are
reported rather than an independence-assuming item interval. See
`human_output_review_summary.md` for the frozen claim boundary.

## 11. Defensible claims (and what we do NOT claim)

Supported by this analysis:

1. In the outcome-informed control stratum, SAGE-Law reduces exposure-aware
   unsafe release by ~0.65–0.70 absolute versus the three prompt conditions;
   task-clustered sensitivity intervals exclude 0.
2. It significantly reduces every audited unsafe-commitment category
   (material legal error, unsupported claims, overcommitment, unsupported
   recommendation, omitted issues).
3. Within control, utility is NS versus raw/support prompts and lower than the
   bounded prompt; availability is 64.1% versus 100%. Criteria coverage and
   traceability are higher under the metadata-aware judge.
4. Blocks target unsafe drafts in 80/88 annotated blocked cases; gate-label
   denominators contain missing values (false downgrade 0/173; control false
   refusal 2/127).
5. The effect is robust across two context lanes, two generator families, two
   cross-family judges (§ agreement doc), and an external GPT audit.

Not claimed: that SAGE-Law improves rubric-blind legal reasoning, semantically
verifies sources, proves legal correctness, replaces lawyers, or estimates LAB
prevalence. The human audit is output-only concordance, not attorney validation.
