# Reproduction instructions

## Frozen-table analysis

From the repository root:

```bash
python3 verify_integrity.py
python3 reproduce.py --output-dir reproduction
```

The count checks preserve the original leaf CSV SHA-256. The seeded null control
uses 20,000 permutations and 2,000 task bootstrap resamples, seed 20260808. The
paired sensitivity preserves the original task-clustered script and seed.
Reaggregation uses archived per-leaf decisions; it does not rerun validators
over absent receipts or verify source correctness. Results are compared against
the supplied aggregate JSON and receipt summary table.

To redraw analysis figures:

```bash
python3 -m pip install -r requirements-figures.txt
python3 reproduce.py --output-dir reproduction-with-figures --figures
```

The figure code emits analysis masters. The manuscript uses figure variants
with revised labels/layout; a redraw is not a byte-identical manuscript build.

## Manuscript source availability

The manuscript is maintained separately on Overleaf. This review package
contains experimental code and data and does not include LaTeX or paper PDFs.

## Structural dry-run of the prototype

```bash
cd experiments
python3 -m sage_law_experiment.cli dry-run --manifest manifests/harvey_smoke_5.json --out runs/dry-run
```

This writes placeholders and candidate/witness/debt/receipt/gate records for
five tasks and four wrappers. It makes no provider calls and supplies no legal
performance evidence.

## Optional new generation and judging

Acquire the public benchmark separately from
https://github.com/harveyai/harvey-labs and inspect its upstream license/terms.
Install `requirements-runtime.txt` for Office deliverable writing. Keep inputs
outside the repository. For example, from `experiments/`:

```bash
export HARVEY_LAB_DIR=/path/to/harvey-labs
python3 -m sage_law_experiment.cli inspect
python3 -m sage_law_experiment.cli --help
```

For new generation, set `SAGE_LAW_PROVIDER` and the matching provider environment
variables. MiniMax uses `MINIMAX_API_KEY` and optionally `MINIMAX_BASE_URL`;
DeepSeek uses `DEEPSEEK_API_KEY` and optionally `DEEPSEEK_BASE_URL`. See CLI help
and `sage_law_experiment/minimax.py` for current routing and retry defaults.
Never commit credentials or populated `.env` files. A new provider run is not
the frozen study and cannot reconstruct the original stochastic outputs.

The 5/80/240 generation manifests define generation plans. They are not the
outcome-informed 132-task safety-audit sample. The latter's identities and group
membership are encoded in `leaf_labels_all_judges.csv`.

## Software/data uploads

For direct supplementary uploads, extract both the software ZIP and data ZIP
into the same parent directory: they share a `sage-law/` root. The data archive
provides the tables/statistics required by the software's analysis commands.
The combined repository archive contains the complete code/data artifact.
