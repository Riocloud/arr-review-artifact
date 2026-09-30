# Gate Ablation and Receipt Replay Summary

No provider API calls were made. The ablation replays SAGE-Law gate
decisions over frozen SAGE-Law drafts and uses existing Mimo v2.5-pro
review-draft labels for counterfactual exposure safety.

## Gate Ablation: Control Stratum

| condition | n | exposed_rate | unsafe_exposure_rate_all_leaves | newly_exposed_from_full_block_n | newly_exposed_unsafe_n | newly_exposed_safe_n | newly_exposed_unknown_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_sage_law | 128 | 0.6406 | 0.2344 | 0 | 0 | 0 | 0 |
| no_citation_source_gate | 128 | 0.6406 | 0.2266 | 0 | 0 | 0 | 0 |
| no_jurisdiction_gate | 128 | 0.6484 | 0.2344 | 1 | 1 | 0 | 0 |
| no_authority_status_gate | 128 | 0.6484 | 0.2344 | 1 | 1 | 0 | 0 |
| no_issue_coverage_gate | 128 | 0.6406 | 0.2266 | 0 | 0 | 0 | 0 |
| no_recommendation_gate | 128 | 0.7422 | 0.3047 | 13 | 10 | 3 | 0 |
| no_review_release_gate | 128 | 0.6562 | 0.2422 | 2 | 2 | 0 | 0 |
| no_review_receipt_gate | 128 | 0.6562 | 0.2422 | 2 | 2 | 0 | 0 |
| prompt_only_checklist | 128 | 0.9062 | 0.4609 | 34 | 30 | 4 | 0 |

## Gate Ablation: High-Risk Stratum

| condition | n | exposed_rate | unsafe_exposure_rate_all_leaves | newly_exposed_from_full_block_n | newly_exposed_unsafe_n | newly_exposed_safe_n | newly_exposed_unknown_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_sage_law | 48 | 0.0 | 0.0 | 0 | 0 | 0 | 0 |
| no_citation_source_gate | 48 | 0.0 | 0.0 | 0 | 0 | 0 | 0 |
| no_jurisdiction_gate | 48 | 0.0208 | 0.0208 | 1 | 1 | 0 | 0 |
| no_authority_status_gate | 48 | 0.0 | 0.0 | 0 | 0 | 0 | 0 |
| no_issue_coverage_gate | 48 | 0.0 | 0.0 | 0 | 0 | 0 | 0 |
| no_recommendation_gate | 48 | 0.5 | 0.4792 | 24 | 23 | 1 | 0 |
| no_review_release_gate | 48 | 0.0833 | 0.0625 | 4 | 3 | 1 | 0 |
| no_review_receipt_gate | 48 | 0.0833 | 0.0625 | 4 | 3 | 1 | 0 |
| prompt_only_checklist | 48 | 0.9792 | 0.8958 | 47 | 43 | 4 | 0 |

## Gate Ablation: All SAGE-Law Leaves

| condition | n | exposed_rate | unsafe_exposure_rate_all_leaves | newly_exposed_from_full_block_n | newly_exposed_unsafe_n | newly_exposed_safe_n | newly_exposed_unknown_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_sage_law | 176 | 0.4659 | 0.1705 | 0 | 0 | 0 | 0 |
| no_citation_source_gate | 176 | 0.4659 | 0.1648 | 0 | 0 | 0 | 0 |
| no_jurisdiction_gate | 176 | 0.4773 | 0.1761 | 2 | 2 | 0 | 0 |
| no_authority_status_gate | 176 | 0.4716 | 0.1705 | 1 | 1 | 0 | 0 |
| no_issue_coverage_gate | 176 | 0.4659 | 0.1648 | 0 | 0 | 0 | 0 |
| no_recommendation_gate | 176 | 0.6761 | 0.3523 | 37 | 33 | 4 | 0 |
| no_review_release_gate | 176 | 0.5 | 0.1932 | 6 | 5 | 1 | 0 |
| no_review_receipt_gate | 176 | 0.5 | 0.1932 | 6 | 5 | 1 | 0 |
| prompt_only_checklist | 176 | 0.9261 | 0.5795 | 81 | 73 | 8 | 0 |

## Receipt Replay / Type Confusion

| test | n | expected_accept_n | actual_accept_n | passed_n | pass_rate |
| --- | --- | --- | --- | --- | --- |
| cross_matter_replay | 82 | 0 | 0 | 82 | 1.0 |
| missing_review_scope_replay | 82 | 0 | 0 | 82 | 1.0 |
| receipt_type_confusion_as_release | 176 | 0 | 0 | 176 | 1.0 |
| stale_artifact_hash_replay | 82 | 0 | 0 | 82 | 1.0 |
| valid_release_receipt | 82 | 82 | 82 | 82 | 1.0 |
| wrong_audience_replay | 82 | 0 | 0 | 82 | 1.0 |
| wrong_release_scope_replay | 82 | 0 | 0 | 82 | 1.0 |
