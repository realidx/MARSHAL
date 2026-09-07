# Native BENAC-P diagnosis

LLM

Selected native positions; at most two measured ego decisions, without skipping native ego responses, and with reference continuation after the second measured action. Not an end-to-end LLM game outcome. Information-channel changes do not alone establish an information-mediated utility effect. Separate B->P sensitivity and P->B forced-action cohorts. Forced high/low-information actions are legal interventions, not necessarily utility-optimal. Their evidence contrast establishes action-to-evidence opportunity; utility differences also include commitment effects. Positive model repair is not an admission condition. Cohorts can share source games and must not be pooled as independent replications. Existing seeds are development diagnostics, not untouched confirmatory evidence. Semantic preflight controls were not all correct. Formal belief errors may include basic instruction/role/prior-grounding errors; do not attribute them exclusively to strategic belief updating.

Oracle-judgment-assisted planning with public history, not a pure planning deficit isolated from belief computation.

Paired replacement of explicit partner judgment with identical public history, state and actions in fresh contexts. The planner may re-infer beliefs from history; a null repair effect does not establish absence of belief dependence.

A supplied wrong judgment can assign probability to types incompatible with public history. If this makes the history-aware reference undefined, LO and corresponding J entries are unavailable, never zero-filled. Direct paired LLM action regret, belief accuracy and channel scores remain defined.

Measurement coverage: {'requested': 127, 'valid': 127, 'unavailable_reference_costs': 1, 'expected_model_action_arms': 10, 'observed_model_action_arms': 10, 'complete_J_tables': 10}

Selection readiness: {'passed': True, 'missing': [], 'independent_games': {'discovery/b_to_p': 3, 'discovery/p_to_b': 3, 'confirmation/b_to_p': 3, 'confirmation/p_to_b': 3}, 'scope': 'Separate functional cohorts; a source game may contribute to both groups, not independent replications across groups.'}

Partner optimality is a best response to the exported fixed reference continuation, not an equilibrium. Confidence intervals cluster positions by original generated game seed. No model-performance filtering is applied.

Preflight semantic control: 3/4 correct; policy: protocol. Full control details and retained answers are exported separately.

## discovery/b_to_p

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.0 | [0.0, 0.0] | 3 |
| false_exclusions | 0.5 | [0.3333333333333333, 0.6666666666666666] | 3 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 3 |
| OL | 0.38888888888888884 | [0.0, 0.6666666666666666] | 3 |
| belief_repair | -0.2222222222222222 | [-0.6666666666666666, 0.0] | 3 |
| root_planning_regret | 0.38888888888888884 | [0.0, 0.6666666666666666] | 3 |
| channel_information_repair | 0.02723472198183685 | [-0.9182958340544894, 1.0] | 3 |
| chooser_repair | 0.38888888888888884 | [0.0, 0.6666666666666666] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 3 |
| oracle_action_belief_exact | 0.0 | [0.0, 0.0] | 3 |
| model_action_belief_exact | 0.1111111111111111 | [0.0, 0.3333333333333333] | 3 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.38888888888888884 |
| Model belief | 0.16666666666666666 | 0.16666666666666666 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.5 | 0.5 |
| Model action chooser | 0.11111111111111112 | 0.11111111111111112 |

## discovery/p_to_b

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 1.0] | 3 |
| false_exclusions | 0.3333333333333333 | [0.0, 0.6666666666666666] | 3 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 3 |
| OL | 0.6666666666666666 | [0.0, 1.3333333333333333] | 3 |
| belief_repair | -0.4444444444444445 | [-0.6666666666666666, 0.0] | 3 |
| root_planning_regret | 0.6666666666666666 | [0.0, 1.3333333333333333] | 3 |
| channel_information_repair | -0.6121972227029929 | [-0.9182958340544894, 0.0] | 3 |
| chooser_repair | 0.6666666666666666 | [0.0, 1.3333333333333333] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 3 |
| oracle_action_belief_exact | 0.0 | [0.0, 0.0] | 3 |
| model_action_belief_exact | 0.2222222222222222 | [0.0, 0.3333333333333333] | 3 |

Forced action contrast: information gap = low-information posterior entropy minus high-information posterior entropy; other deltas = high-information arm minus low-information arm. Utility deltas include physical-state effects.

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| forced_information_gap | 0.9182958340544894 | [0.9182958340544894, 0.9182958340544894] | 3 |
| forced_belief_exact_delta | 0.1111111111111111 | [0.0, 0.3333333333333333] | 3 |
| forced_unsupported_possibilities_delta | 0.4444444444444444 | [0.0, 1.0] | 3 |
| forced_low_posterior_entropy | 1.584962500721156 | [1.584962500721156, 1.584962500721156] | 3 |
| forced_high_posterior_entropy | 0.6666666666666666 | [0.6666666666666666, 0.6666666666666666] | 3 |
| forced_low_belief_exact | 0.0 | [0.0, 0.0] | 3 |
| forced_high_belief_exact | 0.1111111111111111 | [0.0, 0.3333333333333333] | 3 |
| forced_false_exclusions_delta | -0.3333333333333333 | [-0.6666666666666666, 0.0] | 3 |
| forced_reference_utility_delta | -7.401486830834377e-17 | [-1.0, 1.3333333333333333] | 3 |
| forced_reference_planner_with_model_judgment_delta | -7.401486830834377e-17 | [-1.0, 1.3333333333333333] | 3 |
| forced_model_second_decision_then_reference_delta | -0.4444444444444444 | [-2.333333333333333, 1.3333333333333333] | 3 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.6666666666666666 |
| Model belief | 0.0 | 0.22222222222222224 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 1.0 | 1.0 |
| Model action chooser | 0.3333333333333333 | 0.3333333333333333 |

## confirmation/b_to_p

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 1.0] | 3 |
| false_exclusions | 0.5555555555555555 | [0.0, 1.0] | 3 |
| unsupported_possibilities | 0.3333333333333333 | [0.0, 1.0] | 3 |
| OL | 0.5 | [0.0, 1.0] | 3 |
| belief_repair | 0.0 | [0.0, 0.0] | 3 |
| root_planning_regret | 0.5 | [0.0, 1.0] | 3 |
| channel_information_repair | 0.3333333333333333 | [-0.9182958340544894, 1.0] | 3 |
| chooser_repair | 0.5 | [0.0, 1.0] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 3 |
| oracle_action_belief_exact | 0.3333333333333333 | [0.0, 1.0] | 3 |
| model_action_belief_exact | 0.1111111111111111 | [0.0, 0.3333333333333333] | 3 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 0.5 |
| Model belief | 0.0 | 0.5 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 0.8333333333333334 | 0.8333333333333334 |
| Model action chooser | 0.3333333333333333 | 0.3333333333333333 |

## confirmation/p_to_b

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| belief_exact | 0.3333333333333333 | [0.0, 1.0] | 3 |
| false_exclusions | 0.3333333333333333 | [0.0, 0.6666666666666666] | 3 |
| unsupported_possibilities | 0.0 | [0.0, 0.0] | 3 |
| OL | 1.3333333333333333 | [0.6666666666666666, 2.0] | 3 |
| belief_repair | 0.0 | [0.0, 0.0] | 3 |
| root_planning_regret | 1.3333333333333333 | [0.6666666666666666, 2.0] | 3 |
| channel_information_repair | 0.6121972227029929 | [0.0, 0.9182958340544894] | 3 |
| chooser_repair | 1.3333333333333333 | [0.6666666666666666, 2.0] | 3 |
| updater_repair_model_action | 0.0 | [0.0, 0.0] | 3 |
| updater_repair_oracle_action | 0.0 | [0.0, 0.0] | 3 |
| oracle_action_belief_exact | 0.2222222222222222 | [0.0, 0.3333333333333333] | 3 |
| model_action_belief_exact | 0.0 | [0.0, 0.0] | 3 |

Forced action contrast: information gap = low-information posterior entropy minus high-information posterior entropy; other deltas = high-information arm minus low-information arm. Utility deltas include physical-state effects.

| Metric | Mean | 95% interval | Games |
|---|---:|---|---:|
| forced_information_gap | 0.9182958340544894 | [0.9182958340544894, 0.9182958340544894] | 3 |
| forced_belief_exact_delta | -1.850371707708594e-17 | [-1.0, 0.6666666666666666] | 3 |
| forced_unsupported_possibilities_delta | 0.5555555555555555 | [0.16666666666666666, 0.8333333333333334] | 3 |
| forced_low_posterior_entropy | 1.584962500721156 | [1.584962500721156, 1.584962500721156] | 3 |
| forced_high_posterior_entropy | 0.6666666666666666 | [0.6666666666666666, 0.6666666666666666] | 3 |
| forced_low_belief_exact | 0.3333333333333333 | [0.0, 1.0] | 3 |
| forced_high_belief_exact | 0.3333333333333333 | [0.0, 0.6666666666666666] | 3 |
| forced_false_exclusions_delta | 0.0 | [-0.3333333333333333, 0.3333333333333333] | 3 |
| forced_reference_utility_delta | 0.8888888888888888 | [0.6666666666666665, 1.3333333333333333] | 3 |
| forced_reference_planner_with_model_judgment_delta | 0.8888888888888888 | [0.6666666666666665, 1.3333333333333333] | 3 |
| forced_model_second_decision_then_reference_delta | 3.700743415417188e-17 | [-1.6666666666666667, 1.0] | 3 |

R four-cell decomposition (regret; lower is better):

| | Reference planner | Model planner |
|---|---:|---:|
| Reference belief | 0.0 | 1.3333333333333333 |
| Model belief | 0.0 | 1.3333333333333333 |


J four-cell decomposition (utility; higher is better; reference continuation planner):

| | Reference belief updater | Model belief updater |
|---|---:|---:|
| Reference action chooser | 1.5555555555555556 | 1.5555555555555556 |
| Model action chooser | 0.22222222222222218 | 0.22222222222222218 |

