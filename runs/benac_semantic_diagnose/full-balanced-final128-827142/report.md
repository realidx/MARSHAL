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
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.0 | [0.0, 0.0] | 6 |
| unsupported_possibilities | 0.9722222222222222 | [0.9166666666666665, 1.0] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 1.9444444444444444 | [0.27777777777777773, 3.9444444444444446] | 6 |
| belief_repair | 1.8333333333333333 | [-0.05555555555555566, 3.5] | 6 |
| root_planning_regret | 1.111111111111111 | [0.8888888888888885, 1.333333333333333] | 6 |
| chooser_repair | -1.7222222222222225 | [-2.6666666666666665, -0.8333333333333336] | 6 |
| updater_repair_model_action | 0.9444444444444443 | [0.27777777777777773, 1.611111111111111] | 6 |
| updater_repair_oracle_action | 3.7777777777777772 | [3.555555555555555, 4.0] | 6 |
| channel_information_repair | 1.1258145836939113 | [0.8197159723424149, 1.4319131950454078] | 6 |
| end_to_end_regret | 2.444444444444444 | [0.9444444444444443, 3.888888888888889] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 1.9444444444444444 |
| Model | 3.7777777777777772 | 3.7777777777777772 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.666666666666666 | 0.8888888888888885 |
| Model | 3.5555555555555554 | 2.6111111111111107 |

Measurement coverage: {'requested': 111, 'format_valid': 111, 'complete_games': 6, 'expected_games': 6}
## discovery: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.0 | [0.0, 0.0] | 6 |
| unsupported_possibilities | 0.9166666666666666 | [0.75, 1.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 1.0 | [0.0, 3.0] | 6 |
| belief_repair | 2.8333333333333335 | [0.8333333333333334, 5.0] | 6 |
| root_planning_regret | 1.6666666666666667 | [0.5, 2.8333333333333335] | 6 |
| chooser_repair | 0.6666666666666666 | [-0.6666666666666666, 1.8333333333333333] | 6 |
| updater_repair_model_action | 1.0 | [0.0, 3.0] | 6 |
| updater_repair_oracle_action | 2.0 | [0.0, 4.0] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 5.333333333333333 | [2.3333333333333335, 8.166666666666666] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 1.0 |
| Model | 2.0 | 3.8333333333333335 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 5.333333333333333 |
| Model | 5.666666666666667 | 4.666666666666667 |

Measurement coverage: {'requested': 57, 'format_valid': 57, 'complete_games': 6, 'expected_games': 6}
## discovery: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.2222222222222222 | [0.1111111111111111, 0.3333333333333333] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.8333333333333335 | [0.0, 1.7222222222222225] | 6 |
| chooser_repair | 0.8333333333333335 | [0.0, 1.7222222222222225] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| channel_information_repair | -0.5283208335737187 | [-1.0566416671474375, 0.0] | 6 |
| end_to_end_regret | 0.7222222222222223 | [0.0, 1.6111111111111114] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 7.333333333333333 |
| Model | 6.5 | 6.5 |

Measurement coverage: {'requested': 66, 'format_valid': 66, 'complete_games': 6, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=6).

## confirmation: unknown_relevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.0 | [0.0, 0.0] | 6 |
| unsupported_possibilities | 0.9722222222222222 | [0.9166666666666665, 1.0] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 2.8333333333333335 | [1.5, 3.944444444444444] | 6 |
| belief_repair | 1.0555555555555554 | [-0.27777777777777773, 2.444444444444444] | 6 |
| root_planning_regret | 2.0555555555555554 | [1.222222222222222, 3.1666666666666665] | 6 |
| chooser_repair | -1.0555555555555554 | [-2.1111111111111107, 0.3333333333333335] | 6 |
| updater_repair_model_action | 0.7777777777777777 | [0.0, 1.5555555555555554] | 6 |
| updater_repair_oracle_action | 3.888888888888888 | [3.444444444444444, 4.333333333333333] | 6 |
| channel_information_repair | 1.1677527782585484 | [0.6394319446848298, 1.584962500721156] | 6 |
| end_to_end_regret | 3.6111111111111107 | [1.6111111111111114, 5.611111111111111] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 2.8333333333333335 |
| Model | 3.888888888888888 | 3.888888888888888 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.833333333333333 | 0.9444444444444443 |
| Model | 2.7777777777777772 | 1.9999999999999998 |

Measurement coverage: {'requested': 123, 'format_valid': 123, 'complete_games': 6, 'expected_games': 6}
## confirmation: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.16666666666666666 | [0.0, 0.5] | 6 |
| unsupported_possibilities | 1.0 | [1.0, 1.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.8333333333333334 | [0.0, 2.5] | 6 |
| belief_repair | 2.1666666666666665 | [-1.3333333333333333, 5.333333333333333] | 6 |
| root_planning_regret | 2.3333333333333335 | [0.3333333333333333, 5.0] | 6 |
| chooser_repair | 0.0 | [-1.6666666666666667, 1.3333333333333333] | 6 |
| updater_repair_model_action | 1.6666666666666667 | [0.0, 3.3333333333333335] | 6 |
| updater_repair_oracle_action | 4.0 | [1.6666666666666667, 6.333333333333333] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 6.333333333333333 | [3.6666666666666665, 8.5] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.8333333333333334 |
| Model | 4.0 | 3.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 2.8333333333333335 |
| Model | 4.5 | 2.8333333333333335 |

Measurement coverage: {'requested': 57, 'format_valid': 57, 'complete_games': 6, 'expected_games': 6}
## confirmation: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| false_exclusions | 0.1111111111111111 | [0.0, 0.2222222222222222] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.27777777777777796 | [0.0, 0.8333333333333339] | 6 |
| chooser_repair | 0.27777777777777796 | [0.0, 0.8333333333333339] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| channel_information_repair | -0.15304930567574823 | [-0.4591479170272447, 0.0] | 6 |
| end_to_end_regret | 0.8333333333333336 | [0.27777777777777785, 1.3888888888888895] | 6 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 6.833333333333333 |
| Model | 6.5555555555555545 | 6.5555555555555545 |

Measurement coverage: {'requested': 66, 'format_valid': 66, 'complete_games': 6, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=6).

