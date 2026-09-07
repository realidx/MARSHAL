# Native BENAC-P diagnosis

LLM

Selected native positions; at most two measured ego decisions, without skipping native ego responses, and with reference continuation after the second measured action. Not an end-to-end LLM game outcome. Information-channel changes do not alone establish an information-mediated utility effect.

Oracle-judgment-assisted planning with public history, not a pure planning deficit isolated from belief computation.

Paired replacement of explicit partner judgment with identical public history, state and actions in fresh contexts. The planner may re-infer beliefs from history; a null repair effect does not establish absence of belief dependence.

A supplied wrong judgment can assign probability to types incompatible with public history. If this makes the history-aware reference undefined, LO and corresponding J entries are unavailable, never zero-filled. Direct paired LLM action regret, belief accuracy and channel scores remain defined.

Measurement coverage: {'requested': 302, 'valid': 301, 'unavailable_reference_costs': 3, 'expected_model_action_arms': 36, 'observed_model_action_arms': 36, 'complete_J_tables': 36}

Selection readiness: {'passed': True, 'missing': [], 'independent_games': {'discovery/known': 6, 'discovery/unknown_relevant': 6, 'discovery/unknown_irrelevant': 6, 'confirmation/known': 6, 'confirmation/unknown_relevant': 6, 'confirmation/unknown_irrelevant': 6}, 'scope': 'Conditional diagnostic opportunities, not a guarantee of model weaknesses or positive repair effects. Common optimal menus remain valid in every condition; no action change is demanded without utility regret.'}

Partner optimality is a best response to the exported fixed reference continuation, not an equilibrium. Confidence intervals cluster positions by original generated game seed. No model-performance filtering is applied.

## discovery/known

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.16666666666666666 | [0.0, 0.5] | 6 |
| unsupported_possibilities | 0.5833333333333334 | [0.25, 0.9166666666666666] | 6 |
| OL | 0.16666666666666666 | [0.0, 0.5] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.16666666666666666 | [0.0, 0.5] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| chooser_repair | 0.16666666666666666 | [0.0, 0.5] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.16666666666666666 | [0.0, 0.5] | 6 |
| model_action_belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.16666666666666666 |
| Model belief | 0.0 | 0.16666666666666666 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.3333333333333333 | 0.3333333333333333 |
| Model action chooser | 0.16666666666666666 | 0.16666666666666666 |

## discovery/unknown_relevant

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| false_exclusions | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |
| unsupported_possibilities | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| OL | 0.75 | [0.4166666666666667, 1.0] | 6 |
| belief_repair | 0.0 | [-0.5, 0.5] | 6 |
| root_planning_regret | 0.5277777777777778 | [0.19444444444444442, 0.8333333333333334] | 6 |
| channel_information_repair | 0.013617360990918426 | [-0.4591479170272447, 0.5] | 6 |
| chooser_repair | 0.5277777777777778 | [0.19444444444444442, 0.8333333333333334] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.3055555555555555 | [0.05555555555555555, 0.6111111111111112] | 6 |
| model_action_belief_exact | 0.05555555555555555 | [0.0, 0.16666666666666666] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.75 |
| Model belief | 0.16666666666666666 | 0.75 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.25 | 0.25 |
| Model action chooser | -0.27777777777777773 | -0.27777777777777773 |

## discovery/unknown_irrelevant

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 6 |
| false_exclusions | 0.5277777777777777 | [0.3055555555555555, 0.6666666666666666] | 6 |
| unsupported_possibilities | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| OL | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| belief_repair | 0.3333333333333333 | [0.0, 0.6666666666666666] | 6 |
| root_planning_regret | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| chooser_repair | 0.6666666666666666 | [0.3333333333333333, 1.0] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.2222222222222222 | [0.0, 0.5555555555555555] | 6 |
| model_action_belief_exact | 0.38888888888888884 | [0.05555555555555555, 0.7222222222222223] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.6666666666666666 |
| Model belief | 0.0 | 1.0 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.7777777777777778 | 0.7777777777777778 |
| Model action chooser | 0.11111111111111109 | 0.11111111111111109 |

## confirmation/known

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |
| false_exclusions | 0.16666666666666666 | [0.0, 0.5] | 6 |
| unsupported_possibilities | 0.4166666666666667 | [0.08333333333333333, 0.75] | 6 |
| OL | 0.6666666666666666 | [0.0, 1.6666666666666667] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.6666666666666666 | [0.0, 1.6666666666666667] | 6 |
| channel_information_repair | 0.0 | [0.0, 0.0] | 6 |
| chooser_repair | 0.6666666666666666 | [0.0, 1.6666666666666667] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.8333333333333334 | [0.5, 1.0] | 6 |
| model_action_belief_exact | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.6666666666666666 |
| Model belief | 0.0 | 0.6666666666666666 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.3333333333333333 | 0.3333333333333333 |
| Model action chooser | -0.3333333333333333 | -0.3333333333333333 |

## confirmation/unknown_relevant

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.16666666666666666 | [0.0, 0.5] | 6 |
| false_exclusions | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |
| unsupported_possibilities | 0.5 | [0.16666666666666666, 0.8333333333333334] | 6 |
| OL | 0.6666666666666666 | [0.25, 1.0833333333333333] | 6 |
| belief_repair | -0.5 | [-1.0833333333333333, 0.08333333333333333] | 6 |
| root_planning_regret | 0.6944444444444445 | [0.19444444444444442, 1.2777777777777777] | 6 |
| channel_information_repair | 0.31971597234241494 | [-0.30609861135149646, 0.792481250360578] | 6 |
| chooser_repair | 0.6944444444444445 | [0.19444444444444442, 1.2777777777777777] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.3055555555555555 | [0.05555555555555555, 0.6111111111111112] | 6 |
| model_action_belief_exact | 0.38888888888888884 | [0.05555555555555555, 0.7222222222222223] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.6666666666666666 |
| Model belief | 0.0 | 0.16666666666666666 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 1.472222222222222 | 1.472222222222222 |
| Model action chooser | 0.7777777777777777 | 0.7777777777777777 |

## confirmation/unknown_irrelevant

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.16666666666666666 | [0.0, 0.5] | 6 |
| false_exclusions | 0.4444444444444444 | [0.25, 0.611111111111111] | 6 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 6 |
| OL | 1.0555555555555556 | [0.3333333333333333, 1.888888888888889] | 6 |
| belief_repair | 0.0 | [0.0, 0.0] | 6 |
| root_planning_regret | 0.7222222222222222 | [0.0, 1.722222222222222] | 6 |
| channel_information_repair | 0.0 | [-0.4591479170272447, 0.4591479170272447] | 6 |
| chooser_repair | 0.7222222222222222 | [0.0, 1.722222222222222] | 6 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 6 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 6 |
| oracle_action_belief_exact | 0.2222222222222222 | [0.0, 0.5555555555555555] | 6 |
| model_action_belief_exact | 0.2222222222222222 | [0.0, 0.5555555555555555] | 6 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 1.0555555555555556 |
| Model belief | 0.0 | 1.0555555555555556 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 1.2222222222222223 | 1.2222222222222223 |
| Model action chooser | 0.5 | 0.5 |

