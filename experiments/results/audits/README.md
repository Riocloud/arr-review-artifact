# Frozen safety-audit tables

The CSVs and `gate_ablation_stats.json` are copied unchanged. In
`safety_stats.json`, only `meta.experiments_dir` was changed to `experiments` to
remove a local author path. All statistical values are preserved.

`null_gate_control.py` and `task_clustered_sensitivity.py` use the included leaf
table. `replay_aggregate_tables.py` recomputes aggregates from archived per-leaf
ablation/replay outcomes; it does not recreate the decisions from raw artifacts.
`make_figures.py` redraws analysis figure masters from these tables and JSON.

`analyze_safety_labels.py` and `gate_ablation_analysis.py` require missing frozen
judge JSONL and original run artifacts. Their standalone entry points are
guarded against accidentally replacing the supplied statistics with empty
results. Use the root `reproduce.py` for the available reproduction path.

See the root documentation for distinct draft/post-gate label surfaces, sample
selection limits, and the absence of raw human annotations.
