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
| belief_exact | 0.16666666666666666 | [0.05555555555555555, 0.27777777777777773] | 6 |
| false_exclusions | 0.05555555555555555 | [0.0, 0.16666666666666666] | 6 |
| unsupported_possibilities | 0.8055555555555555 | [0.6944444444444443, 0.9166666666666666] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 0.6666666666666666 | [0.0, 2.0] | 3 |
| belief_repair | None | None | 0 |
| root_planning_regret | 2.1111111111111107 | [1.333333333333333, 3.0027777777777622] | 6 |
| chooser_repair | -1.2222222222222225 | [-2.6666666666666665, -0.3333333333333335] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 2.5555555555555554 | [1.6666666666666667, 4.0] | 3 |
| channel_information_repair | 0.5974937501201927 | [0.2222222222222222, 1.0147034725828001] | 6 |
| end_to_end_regret | 4.999999999999999 | [3.9999999999999996, 5.999999999999999] | 2 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | None | None |
| Model | None | None |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.666666666666666 | 1.8333333333333328 |
| Model | 2.5555555555555554 | 3.444444444444444 |

Measurement coverage: {'requested': 144, 'format_valid': 104, 'complete_games': 0, 'expected_games': 6}
## discovery: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| unsupported_possibilities | 0.3333333333333333 | [0.16666666666666666, 0.5] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 4 |
| belief_repair | 6.0 | [6.0, 6.0] | 2 |
| root_planning_regret | 3.6666666666666665 | [0.8333333333333334, 6.666666666666667] | 6 |
| chooser_repair | 3.8 | [0.2, 7.6] | 5 |
| updater_repair_model_action | 4.6 | [2.2, 6.0] | 5 |
| updater_repair_oracle_action | 3.4 | [1.0, 5.8] | 5 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 5.333333333333333 | [0.0, 10.0] | 3 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 6.0 | 6.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 3.5 |
| Model | 3.6666666666666665 | 0.2 |

Measurement coverage: {'requested': 60, 'format_valid': 48, 'complete_games': 0, 'expected_games': 6}
## discovery: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.6666666666666666 | [0.6666666666666666, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 5 |
| belief_repair | 0.0 | [0.0, 0.0] | 4 |
| root_planning_regret | 1.666666666666667 | [0.5833333333333335, 2.5000000000000004] | 4 |
| chooser_repair | 1.666666666666667 | [0.5833333333333335, 2.5000000000000004] | 4 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 4 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 4 |
| channel_information_repair | -0.6887218755408671 | [-0.9182958340544894, -0.22957395851362236] | 4 |
| end_to_end_regret | 1.4444444444444446 | [0.0, 2.6666666666666665] | 3 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 7.333333333333333 | 7.333333333333333 |
| Model | 5.833333333333332 | 5.833333333333332 |

Measurement coverage: {'requested': 93, 'format_valid': 80, 'complete_games': 2, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=4).

## confirmation: unknown_relevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.2222222222222222 | [0.05555555555555555, 0.4444444444444444] | 6 |
| false_exclusions | 0.05555555555555555 | [0.0, 0.16666666666666666] | 6 |
| unsupported_possibilities | 0.7222222222222222 | [0.5277777777777778, 0.9166666666666666] | 6 |
| prior_only_exact | 0.0 | [0.0, 0.0] | 6 |
| OL | 1.6666666666666665 | [0.0, 3.333333333333333] | 2 |
| belief_repair | None | None | 0 |
| root_planning_regret | 1.583333333333333 | [1.1666666666666665, 1.9166666666666665] | 4 |
| chooser_repair | -0.33333333333333326 | [-0.5833333333333331, -0.08333333333333337] | 4 |
| updater_repair_model_action | 0.9999999999999999 | [0.0, 1.9999999999999998] | 4 |
| updater_repair_oracle_action | 2.9166666666666665 | [1.833333333333333, 3.9999999999999996] | 4 |
| channel_information_repair | 0.8962406251802889 | [0.6666666666666666, 1.3553885422075336] | 4 |
| end_to_end_regret | 4.583333333333333 | [3.666666666666666, 5.5] | 4 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | None | None |
| Model | None | None |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 4.833333333333333 | 1.6666666666666663 |
| Model | 3.333333333333333 | 2.333333333333333 |

Measurement coverage: {'requested': 126, 'format_valid': 93, 'complete_games': 0, 'expected_games': 6}
## confirmation: known

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| unsupported_possibilities | 0.3333333333333333 | [0.16666666666666666, 0.5] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 1.0 | [0.0, 3.0] | 5 |
| belief_repair | 4.0 | [0.0, 7.0] | 3 |
| root_planning_regret | 2.0 | [0.3333333333333333, 4.166666666666667] | 6 |
| chooser_repair | 1.1666666666666667 | [0.3333333333333333, 2.1666666666666665] | 6 |
| updater_repair_model_action | 2.8333333333333335 | [0.8333333333333334, 5.166666666666667] | 6 |
| updater_repair_oracle_action | 3.6666666666666665 | [1.6666666666666667, 5.666666666666667] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| end_to_end_regret | 8.0 | [6.0, 10.0] | 3 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 1.6666666666666667 |
| Model | 5.666666666666667 | 5.666666666666667 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 3.1666666666666665 |
| Model | 4.833333333333333 | 2.0 |

Measurement coverage: {'requested': 66, 'format_valid': 55, 'complete_games': 1, 'expected_games': 6}
## confirmation: unknown_irrelevant

| Metric | Mean | 95% CI | Complete bundles |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.6666666666666666 | [0.6666666666666666, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| prior_only_exact | 1.0 | [1.0, 1.0] | 6 |
| OL | 0.0 | [0.0, 0.0] | 5 |
| belief_repair | 0.0 | [0.0, 0.0] | 5 |
| root_planning_regret | 1.5000000000000004 | [1.333333333333334, 1.666666666666667] | 4 |
| chooser_repair | 1.4444444444444449 | [1.333333333333334, 1.666666666666667] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 3 |
| channel_information_repair | -1.084962500721156 | [-1.4182958340544893, -0.9182958340544894] | 4 |
| end_to_end_regret | 1.9166666666666674 | [1.5000000000000009, 2.3333333333333335] | 4 |

R table:

| | Reference | Model |
|---|---:|---:|
| Reference | 0.0 | 0.0 |
| Model | 0.0 | 0.0 |


J table:

| | Reference | Model |
|---|---:|---:|
| Reference | 6.833333333333333 | 6.833333333333333 |
| Model | 5.249999999999999 | 5.5555555555555545 |

Measurement coverage: {'requested': 111, 'format_valid': 99, 'complete_games': 0, 'expected_games': 6}

All three control conditions optimal in the same bundle: 0.0 (95% CI [0.0, 0.0]; n=3).

