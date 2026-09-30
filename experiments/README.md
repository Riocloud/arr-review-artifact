# Experiment harness

The public Harvey LAB checkout is external. Configure `HARVEY_LAB_DIR` or
`--lab-dir` for commands that read benchmark documents. The three supplied
manifests are generation plans, not the selected audit sample.

For offline reproduction from frozen numeric tables, run `reproduce.py` from
the repository root. For a structural dry-run, use:

```bash
python3 -m sage_law_experiment.cli dry-run --manifest manifests/harvey_smoke_5.json --out runs/dry-run
```

This creates placeholders, not model outputs. Consult `../docs/REPRODUCTION.md`
for data availability, current-runtime limitations, and optional provider use.
