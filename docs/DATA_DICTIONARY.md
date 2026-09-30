# Data dictionary

Blank CSV cells represent missing/unknown values and must not be converted to false.

The primary leaf key is `(judge, task_id, context_mode, generated_model, wrapper)`. 
Paired groups omit judge/wrapper; task-level resampling preserves all groups per task.

`rel_*` fields refer to post-gate exposed/status artifacts; `draft_*` fields refer to pre-gate drafts.
`unsafe_release` is exposure AND unsafe post-gate label; it differs from the draft-based matched replay.
`exposed_artifact` is release availability. Ordinal utility/coverage scores range from 0 to 3.
Condition names in code map raw_agent to Raw, rag_agent to Support cue, cbea_lcv_legal to Commitment cue, and sage_law to the controller.
The cue baselines are prompt conditions, not full RAG or CBEA+LCV systems.

## gate_ablation_leaf_effects.csv

Rows: 1584.

Fields: `condition`, `description`, `sample_stratum`, `task_id`, `context_mode`, `generated_model`, `actual_decision`, `actual_exposed`, `counterfactual_exposed`, `newly_exposed_from_full_block`, `safety_known`, `safe_to_release_surface`, `unsafe_exposure`, `newly_exposed_safe`, `newly_exposed_unsafe`, `released_safe`, `draft_safe`, `gate_false_release`, `gate_false_refusal`, `unsatisfied_predicates`, `remaining_predicates`.

## gpt_wrapper_view.csv

Rows: 4.

Fields: `wrapper`, `n`, `rel_safe`, `false_release`, `rel_util`.

## judge_agreement.csv

Rows: 3.

Fields: `pair`, `n_overlap`, `safe_to_release_n`, `safe_to_release_pct_agree`, `safe_to_release_kappa`, `material_legal_error_n`, `material_legal_error_pct_agree`, `material_legal_error_kappa`, `false_release_n`, `false_release_pct_agree`, `false_release_kappa`, `utility_exact`, `utility_within1`, `utility_mean_abs_diff`, `coverage_exact`, `coverage_within1`, `coverage_mean_abs_diff`.

## leaf_labels_all_judges.csv

Rows: 1052.

Fields: `judge`, `study`, `sample_stratum`, `selection_category`, `task_id`, `context_mode`, `generated_model`, `generated_family`, `wrapper`, `gate_decision`, `trace_reconstructable`, `confidence`, `rel_safe`, `rel_mat_err`, `rel_overcommit`, `rel_unsup_rec`, `rel_issue_omit`, `rel_unsup_claims`, `rel_contra_claims`, `rel_util`, `rel_cov`, `rel_claims_audited`, `false_release`, `false_refusal`, `false_downgrade`, `gate_decision_correct`, `has_review_draft`, `draft_safe`, `draft_mat_err`, `draft_util`, `draft_cov`, `draft_unsup_claims`, `exposed_artifact`, `unsafe_release`, `rel_unsafe`.

## paired_deltas_mimo_task_clustered.csv

Rows: 99.

Fields: `stratum`, `metric`, `baseline`, `n_groups`, `n_tasks`, `sage_law_mean`, `baseline_mean`, `delta_sage_minus_base`, `ci_lo`, `ci_hi`, `interval_excludes_zero`, `bootstrap_cluster`, `n_boot`, `seed`.

## receipt_replay_type_confusion.csv

Rows: 668.

Fields: `test`, `task_id`, `context_mode`, `generated_model`, `sample_stratum`, `expected_accept`, `actual_accept`, `passed`, `reason`.

## receipt_replay_type_confusion_summary.csv

Rows: 7.

Fields: `test`, `n`, `expected_accept_n`, `actual_accept_n`, `passed_n`, `pass_rate`.
