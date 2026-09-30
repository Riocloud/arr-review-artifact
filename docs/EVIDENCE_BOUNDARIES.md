# Evidence and availability boundaries

| Claim or artifact | Availability | Interpretation |
| --- | --- | --- |
| Frozen primary leaf label table | Included unchanged | 704 primary leaves; labels are metadata-aware and output-only |
| Coverage-matched selection | Reproducible from leaf CSV | 101 draft-labeled groups from 89 tasks; selected subset, 27 control drafts missing labels |
| Task-clustered paired intervals | Reproducible from leaf CSV | Resample tasks, preserving each task's groups; descriptive sample contrasts |
| Gate-ablation effects and aggregates | Included; aggregates can be recomputed | Historical reconstructed post-hoc exposure decisions, not a live generation ablation |
| Receipt replay outcomes | Included; outcome counts can be recomputed | Archived offline replay checks, not receipt validation at live consumption |
| Full raw generations, judge records, gate/debt/receipt inputs | Absent | Cannot regenerate labels or original counterfactual/replay decisions end to end |
| Human concordance | Summary only | Author-reported 356/360 output-label agreement; no raw annotations, seed/frame, or mapping |
| Public Harvey LAB inputs | External | Public tasks/rubrics are policy inputs; no hidden-criterion generalization claim |
| Experiment runtime code | Current checkout snapshot | Historical runtime identity and provider execution are not sealed |

No new model calls, relabeling, human review, or experiments are represented by
this packaging operation. Labels are not an independent legal gold standard.
The complete target contract contains unimplemented or untested requirements.
Study figures describe generated drafts and selective release, not repaired
legal correctness or a production deployment.

Packaging changes are limited to repository documentation, one local metadata
path in `safety_stats.json`, raw-input guards in two analysis entry points, and
new offline orchestration/integrity/reaggregation utilities. Original CSVs,
runtime modules and gate policy are
copied unchanged. The manifest identifies every packed file by hash.

Only the paper's original release-control study is represented. Later repair
labs, source-status pilots, confirmatory dry-runs, internal handoffs, and hidden
holdout artifacts are outside this artifact's scope.
