# CalBench transfer results inventory

Local audit of archived runs. The frozen sequential suite has 24 games, four homogeneous agents, and three requested meetings per game. This file lists every locally found run with all 24 distinct cases; serving protocols and training budgets vary, so the rows do not form a controlled model comparison.

Metrics: **Meetings** sums `diagnostics.final_valid_meetings` over the 24 final calendars (72 requests); **full-game success** counts `diagnostics.full_stream_completion` (24). The native `meetings_scheduled` instead counts coordinated round resolutions: it exceeds final retained meetings by one in three archived runs, identified below. **Per-person excess cost**, **communication overhead**, and **burden imbalance** are the mean over 24 games of the within-game four-agent means of `per_agent_coordination_cost`, `per_agent_communication_efficiency`, and `per_agent_fairness_cost`, respectively. Communication uses the native per-agent messages-per-scheduled-meeting field. Native excess cost and fairness values from failed games may be zero or misleading; verified full-stream excess cost should be analyzed only within successful games. These are local CalBench-adaptation metrics, not the benchmark’s composite score.

## Models named in the current paper draft, plus external comparisons

| Model | Meetings ↑ | Full-game success ↑ | Per-person excess cost ↓ | Communication overhead ↓ | Burden imbalance ↓ | Raw evidence |
|---|---:|---:|---:|---:|---:|---|
| Q0 baseline | 37/72 | 5/24 | 0.260 | 5.663 | 0.443 | [source](../new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868929.tar.gz) |
| SP-41 | 37/72 | 6/24 | 0.479 | 5.181 | 0.755 | [source](../new/sp41_calbench_20260926/calbench_sp41_874283.tar.gz) |
| O-99 | 38/72 | 8/24 | 0.396 | 5.003 | 0.490 | [source](../new/osc_training_evidence_20260922/calbench/outcome.tar.gz) |
| O+P (BP-99) | 44/72 | 10/24 | 0.219 | 4.760 | 0.432 | [source](../new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz) |
| O+P+B (micro24-39) | 47/72 | 9/24 | 0.156 | 4.714 | 0.292 | [source](../new/micro_learning_evidence_20260925/calbench_micro24.tar.gz) |
| Qwen3-4B (thinking) | 42/72 | 7/24 | 0.344 | 4.828 | 0.557 | [source](../new/qwen3_4b_thinking_calbench_20260926/calbench_qwen3_4b_thinking_877057.tar.gz) |
| MARSHAL Generalist | 37/72 | 6/24 | 0.677 | 4.429 | 0.875 | [source](../new/external_models_20260926/calbench/marshal-generalist-thinking-881115/games/results.json) |
| Social-R1-4B | 39/72 | 5/24 | 0.823 | 4.554 | 0.901 | [source](../new/external_models_20260926/calbench/socialr1-thinking-881116/games/results.json) |

The SP, O, BP, and micro-bank checkpoints differ in training exposure. External models use thinking mode; output truncation affected 11/24 MARSHAL games and 14/24 Qwen3-4B thinking games under the 4,096-token cap. The complete archive below includes other D, O, C, and micro-bank runs.

The paper's CalBench table instead reports **verified excess team cost divided by four, averaged only over full-game successes**. That quantity is different from the native all-game per-agent excess-cost column in this audit (e.g., Q0: 0.100 versus 0.260), because failed games have no comparable full-stream reference cost.

## All complete 24-game runs

| Run | Meetings ↑ | Full-game success ↑ | Per-person excess cost ↓ | Communication overhead ↓ | Burden imbalance ↓ | Raw evidence |
|---|---:|---:|---:|---:|---:|---|
| d19-878627-h10047 | 35/72 | 4/24 | 0.812 | 5.835 | 0.734 | [source](../new/d19_fixed_training_snapshot_20260925/calbench/d19-878627-h10047.tar.gz) |
| d19-881339 | 33/72 | 4/24 | 0.135 | 5.821 | 0.349 | [source](../new/d24_partner32_evidence_20260926/calbench/d19-881339/games/results.json) |
| d39-881481 | 38/72 | 7/24 | 0.135 | 5.498 | 0.219 | [source](../new/d24_partner32_evidence_20260926/calbench/d39-881481/games/results.json) |
| d52-878528 | 37/72 | 6/24 | 0.250 | 5.017 | 0.312 | [source](../new/d52_resume_evidence_20260925/calbench/d52-878528.tar.gz) |
| d119-876729-biinv-v1-stream-876945 | 41/72 | 6/24 | 0.573 | 5.247 | 0.760 | [source](../new/d67_125_continuation_20260924/calbench/d119-876729-biinv-v1-stream-876945/results.json) |
| d67-876617-biinv-v1-stream-876660 | 45/72 | 8/24 | 0.594 | 5.071 | 0.880 | [source](../new/d67_125_continuation_20260924/calbench/d67-876617-biinv-v1-stream-876660/results.json) |
| d79-876729-biinv-v1-stream-876772 | 33/72 | 4/24 | 0.281 | 5.797 | 0.396 | [source](../new/d67_125_continuation_20260924/calbench/d79-876729-biinv-v1-stream-876772/results.json) |
| d99-876729-biinv-v1-stream-876872 | 42/72 | 6/24 | 0.208 | 5.281 | 0.422 | [source](../new/d67_125_continuation_20260924/calbench/d99-876729-biinv-v1-stream-876872/results.json) |
| d119-875538 | 37/72 | 5/24 | 0.406 | 5.486 | 0.469 | [source](../new/d_evidence_20260924/calbench/d119-875538.tar.gz) |
| d148-876196 | 36/72 | 4/24 | 0.188 | 5.701 | 0.307 | [source](../new/d_evidence_20260924/calbench/d148-876196.tar.gz) |
| d19-874430 | 37/72 | 5/24 | 0.240 | 5.795 | 0.271 | [source](../new/d_evidence_20260924/calbench/d19-874430.tar.gz) |
| d39-874492 | 37/72 | 6/24 | 0.500 | 5.318 | 0.521 | [source](../new/d_evidence_20260924/calbench/d39-874492.tar.gz) |
| d53-874013 | 38/72 | 5/24 | 0.344 | 5.646 | 0.469 | [source](../new/d_evidence_20260924/calbench/d53-874013.tar.gz) |
| d72-875168 | 40/72 | 6/24 | 0.406 | 4.967 | 0.578 | [source](../new/d_evidence_20260924/calbench/d72-875168.tar.gz) |
| d25-877838-7of24 | 37/72 | 7/24 | 0.250 | 5.675 | 0.719 | [source](../new/d_interaction_chains_20260925/calbench/d25-877838-7of24.tar.gz) |
| marshal-generalist-thinking-881115 | 37/72 | 6/24 | 0.677 | 4.429 | 0.875 | [source](../new/external_models_20260926/calbench/marshal-generalist-thinking-881115/games/results.json) |
| socialr1-thinking-881116 | 39/72 | 5/24 | 0.823 | 4.554 | 0.901 | [source](../new/external_models_20260926/calbench/socialr1-thinking-881116/games/results.json) |
| qwen3-4b-thinking-biinv-v1-stream-877057 | 42/72 | 7/24 | 0.344 | 4.828 | 0.557 | [source](../new/qwen3_4b_thinking_calbench_20260926/calbench_qwen3_4b_thinking_877057.tar.gz) |
| step49 | 35/72 | 6/24 | 0.323 | 6.026 | 0.385 | [source](../new/micro_learning_continuation_20260925/calbench_step49.tar.gz) |
| step79 | 39/72 | 4/24 | 0.292 | 5.835 | 0.479 | [source](../new/micro_learning_continuation_20260925/calbench_step79.tar.gz) |
| micro13-step19-878930-r2-biinv-v1-stream-878966 | 37/72 | 4/24 | 0.292 | 5.554 | 0.406 | [source](../new/micro_learning_evidence_20260925/calbench_micro13.tar.gz) |
| micro13-step39-878930-biinv-v1-stream-879032 | 38/72 | 4/24 | 0.573 | 5.307 | 0.729 | [source](../new/micro_learning_evidence_20260925/calbench_micro13.tar.gz) |
| micro13-step9-878813-r2-biinv-v1-stream-878924 | 41/72 | 6/24 | 0.521 | 5.406 | 0.599 | [source](../new/micro_learning_evidence_20260925/calbench_micro13.tar.gz) |
| micro24-step19-878930-r2-biinv-v1-stream-878967 | 39/72 | 4/24 | 0.333 | 5.316 | 0.479 | [source](../new/micro_learning_evidence_20260925/calbench_micro24.tar.gz) |
| micro24-step39-878930-biinv-v1-stream-879033 | 47/72 | 9/24 | 0.156 | 4.714 | 0.292 | [source](../new/micro_learning_evidence_20260925/calbench_micro24.tar.gz) |
| micro24-step9-878813-r2-biinv-v1-stream-878925 | 38/72 | 2/24 | 0.365 | 5.595 | 0.510 | [source](../new/micro_learning_evidence_20260925/calbench_micro24.tar.gz) |
| d24v2 | 41/72 | 7/24 | 0.344 | 5.332 | 0.667 | [source](../new/micro_v2_evidence_20260925/calbench_d24v2.tar.gz) |
| op16v2 | 30/72 | 3/24 | 0.417 | 6.608 | 0.661 | [source](../new/micro_v2_evidence_20260925/calbench_op16v2.tar.gz) |
| stream24-frozen-868934 | 44/72 | 10/24 | 0.219 | 4.760 | 0.432 | [source](../new/old_bp99_evidence_20260924/calbench/stream24-frozen-868934.tar.gz) |
| stream24-prefreeze-868599 | 45/72 | 10/24 | 0.260 | 4.965 | 0.427 | [source](../new/old_bp99_evidence_20260924/calbench/stream24-prefreeze-868599.tar.gz) |
| conditioned43-871298-biinv-v1-stream-871471 | 32/72 | 4/24 | 0.292 | 5.554 | 0.391 | [source](../new/osc_training_evidence_20260922/calbench/conditioned.tar.gz) |
| conditioned89-871607-h47-biinv-v1-stream-872717 | 38/72 | 5/24 | 0.260 | 5.444 | 0.484 | [source](../new/osc_training_evidence_20260922/calbench/conditioned.tar.gz) |
| outcome19-871285-biinv-v1-stream-871541 | 38/72 | 6/24 | 0.229 | 5.236 | 0.339 | [source](../new/osc_training_evidence_20260922/calbench/outcome.tar.gz) |
| outcome29-871285-biinv-v1-stream-871428 | 40/72 | 6/24 | 0.531 | 5.144 | 0.844 | [source](../new/osc_training_evidence_20260922/calbench/outcome.tar.gz) |
| outcome39-871623-h47-biinv-v1-stream-871943 | 37/72 | 4/24 | 0.323 | 5.625 | 0.484 | [source](../new/osc_training_evidence_20260922/calbench/outcome.tar.gz) |
| outcome99-871623-h47-biinv-v1-stream-872963 | 38/72 | 8/24 | 0.396 | 5.003 | 0.490 | [source](../new/osc_training_evidence_20260922/calbench/outcome.tar.gz) |
| selfplay19-871285-biinv-v1-stream-871429 | 38/72 | 4/24 | 0.375 | 5.505 | 0.729 | [source](../new/osc_training_evidence_20260922/calbench/selfplay.tar.gz) |
| partner-c-step39-biinv-v1-stream-881967 | 35/72 | 3/24 | 0.260 | 5.910 | 0.453 | [source](../new/partner_oc_evidence_20260926/calbench_c.tar.gz) |
| partner-o-step39-biinv-v1-stream-881966 | 34/72 | 3/24 | 0.219 | 5.405 | 0.349 | [source](../new/partner_oc_evidence_20260926/calbench_o.tar.gz) |
| fast8-2of24-868916 | 32/72 | 2/24 | 0.375 | 5.788 | 0.620 | [source](../new/q0_calbench_24_repeats_20260924/runs/fast8-2of24-868916.tar.gz) |
| fast8-5of24-868896 | 39/72 | 5/24 | 0.458 | 5.509 | 0.615 | [source](../new/q0_calbench_24_repeats_20260924/runs/fast8-5of24-868896.tar.gz) |
| frozen-5of24-868929 | 37/72 | 5/24 | 0.260 | 5.663 | 0.443 | [source](../new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868929.tar.gz) |
| frozen-5of24-868930 | 37/72 | 5/24 | 0.260 | 5.663 | 0.443 | [source](../new/q0_calbench_24_repeats_20260924/runs/frozen-5of24-868930.tar.gz) |
| r3-6of24-865854 | 41/72 | 6/24 | 0.240 | 5.667 | 0.370 | [source](../new/q0_calbench_24_repeats_20260924/runs/r3-6of24-865854.tar.gz) |
| r4-4of24-868761 | 34/72 | 4/24 | 0.417 | 5.703 | 0.526 | [source](../new/q0_calbench_24_repeats_20260924/runs/r4-4of24-868761.tar.gz) |
| sp41-873855-biinv-v1-stream-874283 | 37/72 | 6/24 | 0.479 | 5.181 | 0.755 | [source](../new/sp41_calbench_20260926/calbench_sp41_874283.tar.gz) |

46 complete 24-game runs found. Historical repeated baselines and the pre-freeze BP-99 run are retained above for provenance; they should not be counted as independent models.

The four round-versus-final differences occur in `d19-881339/replan_varied_s2`, `micro13-step9-878813-r2-biinv-v1-stream-878924/replan_uniform_s1`, `partner-o-step39-biinv-v1-stream-881966/replan_uniform_s2`, and `qwen3-4b-thinking-biinv-v1-stream-877057/dense_varied_s1`.

Excluded from the 24-game table:
- micro13-step9-878813-biinv-v1-stream-878848: 14 cases in [source](../new/micro_learning_evidence_20260925/calbench_micro13.tar.gz).
- micro24-step9-878813-biinv-v1-stream-878849: 15 cases in [source](../new/micro_learning_evidence_20260925/calbench_micro24.tar.gz).
- original12-860852.tar.gz: 12 cases in [source](../new/old_bp99_evidence_20260924/calbench/original12-860852.tar.gz).
