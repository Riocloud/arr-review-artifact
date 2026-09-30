# Frozen numerical data for SAGE-Law

This data archive accompanies the anonymous software package for
*Context Is Not Legal Authority: Rubric-Informed Release Control for Legal Work Product*.
Extract both archives into the same directory; they share a `sage-law/` root.

Data are under `experiments/results/audits/`. The archive includes numeric leaf
labels, archived ablation/replay outcomes, aggregate statistics, and summary
reports. See `docs/DATA_DICTIONARY.md` for fields and missing-value conventions.

The leaf CSVs are unchanged. Only one local host path in the aggregate metadata
was anonymized. Raw generations, complete judge records, original gate/debt/
receipt inputs, and raw human annotation records are absent. Labels are
output-only and metadata-aware, not independent legal gold standards.

After overlaying the software archive, run `python3 verify_integrity.py` and
`python3 reproduce.py --output-dir reproduction`. Offline reanalysis needs
Python 3.10+ and no API keys. Public Harvey LAB inputs are acquired separately.
