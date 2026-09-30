# SAGE-Law Judge Agreement & Robustness

This document reports cross-judge agreement on the safety annotations and a
disagreement taxonomy. The goal is robustness: are the release-control
conclusions stable across judges, or artifacts of one judge model? We do **not**
declare one judge "correct"; we separate disagreement by metric and by cause.

Judge roles (see `data_inventory.md`): `mimo-v2.5-pro` is the primary,
cross-family judge. `deepseek-v4-pro` (on MiniMax-generated leaves) and
`MiniMax-M3` (on DeepSeek-generated leaves) are cross-family robustness checks.
`gpt-5.4-mini` is an enriched final-audit sample. Agreement is computed on the
leaf-key intersection; `n` is reported each time. Metrics: `safe_to_release`,
`material_legal_error`, `false_release` (Cohen's κ + % agreement); utility and
coverage (ordinal, 0–3) via exact / within-1 agreement and mean absolute diff.

## 1. Agreement table

| Pair (n overlap) | metric | % agree | Cohen's κ |
|---|---|---:|---:|
| **Mimo vs DeepSeek** — MiniMax-gen (84) | safe_to_release | 0.750 | 0.150 |
| | material_legal_error | 0.810 | 0.385 |
| | **false_release** | **0.917** | **0.788** |
| **Mimo vs MiniMax** — DeepSeek-gen (56) | safe_to_release | 0.714 | 0.051 |
| | material_legal_error | 0.661 | 0.342 |
| | **false_release** | **0.893** | **0.741** |
| **Mimo vs GPT** — enriched (60) | safe_to_release | 0.750 | −0.027 |
| | material_legal_error | 0.550 | 0.102 |
| | false_release | 0.367 | 0.030 |

Ordinal scores (0–3):

| Pair | utility within-1 | utility mean|Δ| | coverage within-1 | coverage mean|Δ| |
|---|---:|---:|---:|---:|
| Mimo vs DeepSeek (84) | 0.869 | 0.68 | 0.905 | 0.52 |
| Mimo vs MiniMax (56) | 0.946 | 0.45 | 0.911 | 0.52 |
| Mimo vs GPT (60) | 0.933 | 0.50 | 0.900 | 0.65 |

## 2. How to read the κ values (prevalence paradox)

Base rates are extreme: across these overlap samples ~85–98% of *released*
artifacts are labeled unsafe-to-release and most baselines are labeled
false_release. With such skew, Cohen's κ is depressed even when raw agreement
is high — the classic high-agreement / low-κ paradox. So κ for
`safe_to_release` (0.05–0.15) is **not** evidence of disagreement; the 71–75%
raw agreement, and the fact that both judges almost always agree the artifact is
*unsafe*, is the substantive finding. Where the labels carry information beyond
the base rate — `false_release` between Mimo and the cross-family judges — κ is
substantial (0.74–0.79).

## 3. The headline metric is judge-robust on SAGE-Law leaves

`false_release` agreement between Mimo and the two **cross-family** judges is
high (0.92 / 0.89; κ 0.79 / 0.74). On `sage_law` leaves specifically, the
judges essentially never disagree on false_release (1 of 21 and 1 of 14
sage_law overlaps). So the central claim — SAGE-Law has near-zero false release
— reproduces across three independent judge families.

The Mimo-vs-GPT `false_release` agreement looks alarming (0.37) but is a
**definitional** artifact located entirely on ungated baselines, not on
SAGE-Law (next section).

## 4. Disagreement taxonomy

We bucket disagreements into the four requested causes and give concrete counts.

### (a) Blocked artifact vs review-draft differences — dominant for safe_to_release

`safe_to_release` disagreements concentrate on **blocked SAGE-Law leaves**:
of the safe disagreements, sage_law accounts for 14/21 (Mimo–DeepSeek),
11/16 (Mimo–MiniMax), and 10/15 (Mimo–GPT); and within those, the leaf is
`blocked_or_escalated` in 13/14, 10/11, and 7/10 cases respectively. The
released surface for a blocked leaf is a withheld stub / escalation notice, and
judges differ on whether that should score "safe to release." The cross-family
judges tend to call blocked stubs **safe** more often than Mimo (DeepSeek/
MiniMax "safe-higher" in 16/21 and 15/16 of disagreements) — i.e., **Mimo is
the strictest judge on withheld artifacts**, so the primary analysis is the
conservative choice. This is a scoring-surface ambiguity, not a substantive
safety disagreement.

### (b) Stricter vs looser unsupported-claim / material-error interpretation

`material_legal_error` agreement is fair-to-moderate (0.55–0.81; κ 0.10–0.39),
with disagreements spread across the three **baselines** (e.g. Mimo–GPT: cbea 7,
rag 10, raw 6 of 27). These reflect different thresholds for when a
weakly-supported statement becomes a "material legal error" / "unsupported
material claim." This mostly affects *baseline* error counts (it makes baselines
look worse or better depending on the judge); it does not flip the SAGE-Law
comparison, because SAGE-Law's material-error rate is low under every judge.

### (c) Gate-metadata interpretation — the Mimo vs GPT false_release gap

The single largest metric disagreement (Mimo–GPT false_release, 38/60) is almost
entirely on **ungated baselines**: by wrapper, Mimo labels false_release at
raw 0.87, rag 0.93, cbea 0.87 while GPT labels 0.13 / 0.00 / 0.07; on `sage_law`
both are ~0.07–0.13 and agree. The cause is definitional: **Mimo treats an
unsafe ungated baseline release as a `false_release`; GPT reserves
`false_release` for a gate that *wrongly released* and does not apply it to a
no-gate baseline.** 37 of the 38 disagreements are "Mimo higher." Consequences:
(i) the SAGE-Law false-release estimate is judge-robust; (ii) the *baseline*
false-release rate depends on whether unsafe ungated output is counted as false
release — we therefore also report `safe_to_release` (judge-robust) as the
baseline risk measure, and present false-release deltas with this definitional
note. Both judges still agree the baseline artifacts are unsafe (GPT 52/60,
Mimo 51/60 unsafe; 75% safe-agreement).

### (d) Low-confidence / boundary labels

A minority of disagreements involve a `low` confidence label from at least one
judge: 11/38 of the Mimo–GPT false_release disagreements and 6/27 of the
material-error disagreements; the GPT sample deliberately oversampled
`boundary_low_confidence` groups. These are expected to be noisier and are
flagged rather than resolved.

## 5. Robustness verdict

- **Robust:** SAGE-Law's near-zero false release reproduces across Mimo and two
  cross-family judges (κ 0.74–0.79) and on the GPT audit (both ~0.07–0.13 on
  sage_law). Both judges independently find SAGE-Law released output far safer
  than baselines on the enriched sample (GPT: 53% vs 0% safe).
- **Robust with a definitional caveat:** the *magnitude* of the baseline
  false-release rate depends on whether unsafe ungated output is labeled false
  release. We anchor the baseline contrast on `safe_to_release` (71–75% judge
  agreement) and report false-release with the Mimo definition stated.
- **Surface-sensitive:** scoring of *blocked* artifacts (the safe_to_release
  disagreements) varies by judge; Mimo is strictest, so primary estimates are
  conservative.
- **Ordinal scores stable:** utility/coverage agree within 1 point 87–95% of
  the time.

Practical implication for the paper: lead with `false_release` (corroborated by
two cross-family judges) and the paired reductions in specific defect rates;
present `safe_to_release` as the judge-robust baseline-risk anchor; treat the
GPT sample as an external audit, not a prevalence; and disclose the
false-release definitional difference explicitly.
