# Semantic BENAC-P diagnosis

Run mode: LLM.
Selected, certified three-stage protocol family. No claim about unrestricted random games or cross-environment transfer.
Partner responses are deterministic and terminal-rational under the public protocol; hidden configurations are enumerated, never sampled during evaluation.
Confidence intervals bootstrap independent matched bundles within each condition. Conditions are not counted as independent replicates.
R: regret, first letter judgment and second planner. J: utility, first letter initial chooser and second updater; continuation planner is reference.
A chooser utility gain is not by itself evidence of information mediation. Inspect channel and judgment metrics together.

## discovery: unknown_relevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.2222222222222222 | [0.1111111111111111, 0.3333333333333333] | 6 |
| false_exclusions | 0.0 | [0.0, 0.0] | 6 |
| unsupported_possibilities | 0.7777777777777777 | [0.6666666666666666, 0.8888888888888888] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 2.2777777777777777 | [1.222222222222222, 3.3333333333333335] | 6 |
| belief_repair | 0.8333333333333334 | [-0.6666666666666666, 2.111111111111111] | 6 |
| root_planning_regret | 1.444444444444444 | [0.7777777777777772, 2.555555555555555] | 6 |
| chooser_repair | -1.3888888888888893 | [-2.6666666666666665, 0.2777777777777772] | 6 |
| updater_repair_model_action | 0.611111111111111 | [0.0, 1.3333333333333333] | 6 |
| updater_repair_oracle_action | 3.444444444444444 | [2.888888888888889, 3.888888888888889] | 6 |
| channel_information_repair | 1.1677527782585484 | [0.6394319446848298, 1.584962500721156] | 6 |
| end_to_end_regret | 2.2222222222222214 | [0.9444444444444443, 3.8333333333333335] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 2.2777777777777777 |
| Model | 3.444444444444444 | 3.1111111111111107 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.666666666666666 | 1.2222222222222219 |
| Model | 3.222222222222222 | 2.611111111111111 |

Measurement coverage: {'requested': 111, 'format_valid': 111, 'complete_games': 6, 'expected_games': 6}
## discovery: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| unsupported_possibilities | 0.3333333333333333 | [0.16666666666666666, 0.5] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 1.0 | [0.0, 3.0] | 6 |
| belief_repair | 2.0 | [-2.0, 5.0] | 6 |
| root_planning_regret | 1.6666666666666667 | [0.5, 2.8333333333333335] | 6 |
| chooser_repair | -0.3333333333333333 | [-3.0, 2.1666666666666665] | 6 |
| updater_repair_model_action | 1.8333333333333333 | [0.0, 3.8333333333333335] | 6 |
| updater_repair_oracle_action | 3.8333333333333335 | [1.8333333333333333, 5.833333333333333] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 4.5 | [1.3333333333333333, 7.833333333333333] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 1.0 |
| Model | 3.8333333333333335 | 3.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 3.5 |
| Model | 5.666666666666667 | 3.8333333333333335 |

Measurement coverage: {'requested': 63, 'format_valid': 63, 'complete_games': 6, 'expected_games': 6}
## discovery: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.4444444444444444 | [0.2222222222222222, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.388888888888889 | [0.0, 1.166666666666667] | 6 |
| chooser_repair | 0.388888888888889 | [0.0, 1.166666666666667] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| channel_information_repair | -0.26416041678685936 | [-0.792481250360578, 0.0] | 6 |
| end_to_end_regret | 1.1111111111111114 | [0.27777777777777785, 2.0000000000000004] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 7.333333333333333 |
| Model | 6.944444444444444 | 6.944444444444444 |

Measurement coverage: {'requested': 72, 'format_valid': 72, 'complete_games': 6, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=6).

## confirmation: unknown_relevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.2222222222222222 | [0.1111111111111111, 0.3333333333333333] | 6 |
| false_exclusions | 0.0 | [0.0, 0.0] | 6 |
| unsupported_possibilities | 0.7777777777777777 | [0.6666666666666666, 0.888888888888889] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 0.6666666666666666 | [0.0, 1.444444444444444] | 6 |
| belief_repair | 2.1666666666666665 | [1.2194444444444446, 3.1111111111111107] | 6 |
| root_planning_regret | 2.5555555555555554 | [1.3333333333333333, 3.7777777777777772] | 6 |
| chooser_repair | 0.4444444444444444 | [-1.333333333333333, 2.4999999999999996] | 6 |
| updater_repair_model_action | 0.7777777777777777 | [0.0, 1.5555555555555554] | 6 |
| updater_repair_oracle_action | 2.888888888888889 | [2.1666666666666665, 3.7222222222222214] | 6 |
| channel_information_repair | 1.0566416671474375 | [0.5283208335737187, 1.584962500721156] | 6 |
| end_to_end_regret | 3.6111111111111107 | [1.6111111111111114, 5.611111111111111] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.6666666666666666 |
| Model | 2.888888888888889 | 2.8333333333333326 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.833333333333333 | 1.9444444444444446 |
| Model | 2.2777777777777777 | 1.5 |

Measurement coverage: {'requested': 117, 'format_valid': 117, 'complete_games': 6, 'expected_games': 6}
## confirmation: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |
| false_exclusions | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.25 | [0.08333333333333333, 0.4166666666666667] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.8333333333333334 | [0.0, 2.5] | 6 |
| belief_repair | 2.1666666666666665 | [-1.5, 5.333333333333333] | 6 |
| root_planning_regret | 2.3333333333333335 | [0.3333333333333333, 5.0] | 6 |
| chooser_repair | 1.1666666666666667 | [0.3333333333333333, 2.1666666666666665] | 6 |
| updater_repair_model_action | 0.8333333333333334 | [0.0, 2.5] | 6 |
| updater_repair_oracle_action | 2.0 | [0.0, 4.5] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 4.5 | [1.5, 7.666666666666667] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.8333333333333334 |
| Model | 2.0 | 3.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 4.833333333333333 |
| Model | 4.5 | 3.6666666666666665 |

Measurement coverage: {'requested': 57, 'format_valid': 57, 'complete_games': 6, 'expected_games': 6}
## confirmation: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.4444444444444444 | [0.2222222222222222, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.388888888888889 | [0.0, 1.166666666666667] | 6 |
| chooser_repair | 0.388888888888889 | [0.0, 1.166666666666667] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| channel_information_repair | -0.26416041678685936 | [-0.792481250360578, 0.0] | 6 |
| end_to_end_regret | 0.5555555555555558 | [0.0, 1.1111111111111118] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 6.833333333333333 |
| Model | 6.444444444444444 | 6.444444444444444 |

Measurement coverage: {'requested': 66, 'format_valid': 66, 'complete_games': 6, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=6).

