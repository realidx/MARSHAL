# B/P-only, self-play, and B/P-to-self-play audit (2026-09-19)

This report records the completed training and CalBench evidence for three social-training arms. It is an audit of observed runs, not a claim that the reported checkpoints are optimal for other seeds or budgets.

## Provenance

| Item | Value |
|---|---|
| Base model | `/home/e/e1300530/models/Qwen3-4B-Instruct-2507` |
| Original B/P and SP run | job/run `860494`, source commit `0f6d73af9e32d39d680b4e5b1341f058d6956338` |
| Continued SP and B/P run | run root `MARSHAL-bp99-sp-stage-20260919`, source commit `c4c74ac1a652590f62491c1df937f9baec0bba2a` |
| B/P99-to-SP run | job `861145`, source commit `c4c74ac1a652590f62491c1df937f9baec0bba2a` |
| B/P99-to-SP checkpoint | complete native `checkpoint-27`; HF export `hf-exports-861145-861241/bp99-to-sp-step27` |
| Continued SP checkpoint | complete native `checkpoint-54`; HF export `hf-exports-861145-861241/sp39-continued-step54` |
| Continued B/P | reached validation step 199/approximately 5.43M response tokens, but no complete final checkpoint was saved after the time-limit signal |

The large native checkpoints, HF weights, full calls, games, and validation JSON files remain in the run directories and are not duplicated in Git. Exact local evidence paths are listed at the end.

## Executive result

1. B/P checkpoint 99 is the strongest evaluated model on CalBench.
2. SP improved to checkpoint 39 but did not improve monotonically: continuing to checkpoint 54 reduced CalBench performance and removed all D-family successes.
3. Starting SP from B/P checkpoint 99 did not compose the two abilities. It substantially degraded the B/P checkpoint on CalBench.
4. B/P-only showed a useful learning phase during roughly the first 100 updates, followed by large, mechanism-specific oscillations. The continuation did not produce a safely selectable final checkpoint.
5. The custom social pipeline had few utility-mixed groups per update. For SP, a single terminal player advantage was copied to every valid action in that player's episode; this is coarser than MARSHAL's original turn-level estimator and can reinforce terminal or causally irrelevant PASS actions.

## CalBench

All four formal evaluations completed 12/12 games with healthy transport. The two new evaluations contained isolated strict-envelope failures, reported below rather than silently treated as infrastructure success.

| Model | Coordinated | Successful and optimal | Mean headline score | F | D | C |
|---|---:|---:|---:|---:|---:|---:|
| B/P checkpoint 99 | **8/12** | **7/12** | **0.639** | 4/4 | 3/4 | 1/4 |
| SP checkpoint 39 | 6/12 | 4/12 | 0.463 | 4/4 | 2/4 | 0/4 |
| B/P99 -> SP checkpoint 27 | 4/12 | 2/12 | 0.278 | 2/4 | 1/4 | 1/4 |
| SP checkpoint 39 -> 54 | 4/12 | 4/12 | 0.333 | 4/4 | 0/4 | 0/4 |

### Per-game CalBench outcomes

`1` denotes coordinated success. Scores are headline scores.

| Game | B/P99 | SP39 | B/P99->SP27 | SP54 |
|---|---:|---:|---:|---:|
| F1 | 1 / 1.000 | 1 / 1.000 | 0 / 0.000 | 1 / 1.000 |
| F2 | 1 / 1.000 | 1 / 1.000 | 0 / 0.000 | 1 / 1.000 |
| F3 | 1 / 1.000 | 1 / 1.000 | 1 / 1.000 | 1 / 1.000 |
| F4 | 1 / 1.000 | 1 / 0.889 | 1 / 1.000 | 1 / 1.000 |
| D1 | 1 / 0.667 | 1 / 0.667 | 1 / 0.667 | 0 / 0.000 |
| D2 | 1 / 1.000 | 1 / 1.000 | 0 / 0.000 | 0 / 0.000 |
| D3 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 |
| D4 | 1 / 1.000 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 |
| C1 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 |
| C2 | 0 / 0.000 | 0 / 0.000 | 1 / 0.667 | 0 / 0.000 |
| C3 | 1 / 1.000 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 |
| C4 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 | 0 / 0.000 |

Infrastructure/format details:

- B/P99 and SP39: healthy transport 12/12, untruncated 12/12, zero strict-envelope failures.
- B/P99->SP27: healthy transport 12/12, untruncated 11/12, two strict-envelope failures. D2 contained one truncated generation and failed; C2 succeeded non-optimally despite one strict-envelope failure.
- SP54: healthy transport 12/12, untruncated 12/12, one strict-envelope failure on C2.
- These isolated failures do not explain the overall regressions. Even a generous correction of B/P99->SP27 D2 leaves it substantially below B/P99; SP54's lost D1/D2 successes were not transport failures.

## B/P-only training trajectory

The fixed validation set contains 20 B and 25 P examples; P4 result-use has 10 examples, P history has 8, and the history-control subset has 6. Consequently, one changed answer moves these metrics by 0.05, 0.04, 0.10, 0.125, and 0.167 respectively. The fixed requests and seeds make the direction changes real model changes, while the small denominators magnify their visual size.

| Optimizer step | Response tokens | B | P | P4 result-use | P history | History control | Held-out game player utility |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -1 | 0 | 0.10 | 0.40 | 0.40 | 0.875 | 0.833 | 0.448 |
| 9 | 305,278 | 0.20 | 0.32 | 0.20 | 0.25 | 0.167 | 0.323 |
| 19 | 637,981 | 0.15 | 0.32 | 0.20 | 0.25 | 0.167 | 0.385 |
| 29 | 891,013 | 0.20 | 0.40 | 0.20 | 0.50 | 0.333 | 0.490 |
| 39 | 1,133,392 | 0.30 | 0.40 | 0.20 | 0.375 | 0.333 | 0.625 |
| 49 | 1,313,652 | 0.30 | 0.44 | 0.30 | 0.25 | 0.167 | 0.552 |
| 59 | 1,562,961 | 0.25 | 0.40 | 0.30 | 0.375 | 0.333 | 0.702 |
| 69 | 1,735,250 | 0.25 | 0.44 | 0.40 | 0.375 | 0.333 | 0.510 |
| 79 | 1,981,511 | 0.25 | 0.52 | 0.40 | 0.625 | 0.50 | 0.762 |
| 89 | 2,223,475 | 0.30 | 0.40 | 0.10 | 0.50 | 0.333 | 0.679 |
| **99** | **2,516,803** | **0.20** | **0.44** | **0.20** | **0.50** | **0.333** | **0.729** |
| 109 | 2,836,930 | 0.30 | 0.32 | 0.00 | 0.25 | 0.00 | 0.393 |
| 119 | 3,185,339 | 0.20 | 0.36 | 0.10 | 0.375 | 0.333 | 0.875 |
| 129 | 3,460,923 | 0.25 | 0.40 | 0.30 | 0.375 | 0.333 | 0.552 |
| 139 | 3,718,344 | 0.30 | 0.36 | 0.00 | 0.25 | 0.167 | 0.607 |
| 149 | 4,042,202 | 0.30 | 0.28 | 0.10 | 0.25 | 0.167 | 0.536 |
| 159 | 4,392,545 | 0.40 | 0.44 | 0.20 | 0.625 | 0.50 | 0.552 |
| 169 | 4,660,918 | 0.30 | 0.40 | 0.10 | 0.50 | 0.333 | 0.760 |
| 179 | 4,953,901 | 0.30 | 0.52 | 0.20 | 0.625 | 0.50 | 0.679 |
| 189 | 5,137,448 | 0.35 | 0.48 | 0.30 | 0.50 | 0.333 | 0.656 |
| 199 | 5,429,956 | 0.40 | 0.44 | 0.10 | 0.25 | 0.00 | 0.667 |

Interpretation:

- Roughly the first 100 updates produced an improving envelope and the externally strongest saved checkpoint, despite local oscillations.
- After step 100, B, P, history, result-use, and held-out game utility peaked at different checkpoints and frequently moved in opposite directions. This is capability rotation, not monotonic accumulation.
- Mean task-signal coverage was already small. During steps 0-99, an update contained only 1.84 utility-mixed B groups and 3.38 utility-mixed P groups on average. After step 100 this became 1.45 B and 3.98 P groups.
- The mean measured KL rose from 0.042 before step 100 to 0.103 afterward, while the learning rate stayed at `1e-6`, the KL loss coefficient stayed at `0.01`, weight decay was zero, and there was no late-stage decay.
- Mean gradient norm did not explode (1.98 before step 100 versus 1.74 afterward). The evidence fits continued high-variance/interfering updates after useful shared improvements saturated, not a numerical optimizer failure.
- Step 199 therefore cannot be called better than checkpoint 99 from aggregate B/P validation. It has higher B but collapsed history control and P4 result-use; it also lacks a complete saved checkpoint and external CalBench evaluation.

## SP-only trajectory

The saved comparison is SP checkpoint 39 (5.03M response tokens) versus the continued checkpoint 54 (6.66M). Fixed validation snapshots also remain for steps 29 and 49.

| Optimizer step | Response tokens | B | P | P4 result-use | P history | History control | SP player utility |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 29 | 3,872,580 | 0.25 | 0.28 | 0.30 | 0.25 | 0.167 | 0.448 |
| **39** | **5,028,908** | **0.35** | **0.48** | **0.30** | **0.625** | **0.50** | **0.698** |
| 49 | 6,092,822 | 0.20 | 0.44 | 0.40 | 0.625 | 0.50 | 0.406 |
| 54 | 6,660,608 | 0.25 | 0.32 | 0.20 | 0.25 | 0.167 | 0.656 |

This trajectory is non-monotonic. Step 54 partly recovered the small internal game utility but did not recover the same policy: CalBench fell from 0.463 to 0.333, and D-family success fell from 2/4 to 0/4.

### Fixed-game behavior change

On `reasoning-v4-sp-validation-2`:

| Step | Terminal utilities | Behavior summary |
|---:|---:|---|
| 39 | `[1, 3, 2]` | Agents investigated, accepted mutually useful offers, and continued proposing the missing partner commitments until all useful goals were completed. |
| 49 | `[0, 0, 0]` | Blair learned relevant preferences but twice rejected Alex's attempt to add the Maple commitment required to complete Harbor, reasoning that Blair's own local commitments were already satisfied. |
| 54 | `[1, 1, 1]` | The team completed a subset of goals, then shifted into repeated PASS actions and stopped coordinating toward the remaining preferred goal. |

On `validation-2p-2:avoid_heavy`:

- Step 39 investigated Harbor and accepted mutual Maple, producing `[1,1]`.
- Step 49 investigated Orchard and accepted a split Alex-Maple/Blair-Cedar assignment. The explanation incorrectly treated one player's Cedar commitment as sufficient for a binary joint goal; the result was `[0,0]`.
- Step 54 returned to Harbor investigation and mutual Maple, again producing `[1,1]`.

Thus later training did not simply add knowledge. It moved between different context-conditioned policies.

### What the intervening SP groups rewarded

The table sums `abs(task_advantage) * loss_weight` by emitted action and reports positive minus negative mass.

| Training window | PASS | OFFER | INVESTIGATE | ACCEPT | REJECT |
|---|---:|---:|---:|---:|---:|
| SP steps 40-48, before the step-49 collapse | **+63.91** | -5.48 | **-39.24** | +21.87 | -21.30 |
| SP steps 50-54 | -9.88 | +13.58 | -6.27 | **-13.38** | **+20.29** |

The direction reversed across windows. Step 48 also had a relatively large gradient norm of 1.79. High-return trajectories gave the same positive task advantage to their investigations, offers, accepts, and terminal PASS actions; low-return trajectories similarly made every action negative. These aggregates are correlations, not causal action values, and demonstrate why the observed policy can flip.

Signal scale across the SP run:

| Phase | Mean groups/update | Mean utility-mixed groups | Mixed fraction | Mean nonzero task calls |
|---|---:|---:|---:|---:|
| SP steps 20-39 | 20.64 | 13.96 | 67.1% | 224.16 |
| SP steps 40-54 | 21.13 | 14.33 | 68.4% | 230.40 |

The final value of 11 mixed groups was not a unique anomaly; the absolute effective group count was small throughout.

## B/P checkpoint 99 followed by SP

This run initialized both actor and frozen reference from the B/P checkpoint-99 HF export. It performed 28 SP updates, consumed 4,084,634 response tokens against a 4,036,800 target, and saved complete checkpoint 27.

| SP optimizer step | SP response tokens | B | P | P4 result-use | P history | History control | SP player utility | Offer | Pass | Investigate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -1 | 0 | 0.25 | 0.36 | 0.20 | 0.50 | 0.333 | 0.500 | 0.528 | 0.170 | 0.302 |
| 9 | 1,779,061 | 0.25 | 0.36 | 0.20 | 0.625 | 0.50 | 0.479 | 0.453 | 0.245 | 0.302 |
| 19 | 3,133,544 | 0.20 | 0.44 | 0.20 | 0.25 | 0.00 | 0.615 | 0.453 | 0.283 | 0.264 |
| 27 | 4,084,634 | 0.25 | 0.40 | 0.10 | 0.25 | 0.167 | 0.448 | 0.377 | 0.358 | 0.264 |

The internal SP utility temporarily increased at step 19 while B/history controls degraded. By the final checkpoint, offer and investigate behavior had decreased and PASS had more than doubled relative to the B/P99 starting model.

Actual task-advantage direction by action:

| Training window | PASS | OFFER | INVESTIGATE | ACCEPT | REJECT |
|---|---:|---:|---:|---:|---:|
| Steps 0-9 | **+52.42** | -38.08 | +15.56 | +27.84 | -8.92 |
| Steps 10-19 | **+67.89** | -13.11 | **-31.01** | +17.18 | **-32.89** |
| Steps 20-27 | **+43.70** | -12.74 | -4.86 | -1.88 | **-21.12** |

This is consistent with a progressively more passive policy. It does not establish that PASS itself caused the terminal returns: because all valid actions in one player episode share the same task advantage, successful trajectories also reinforce their forced or irrelevant closing PASS calls.

Signal scale:

| Phase | Mean groups/update | Mean utility-mixed groups | Mixed fraction | Mean nonzero task calls |
|---|---:|---:|---:|---:|
| B/P99 -> SP steps 0-27 | 19.32 | 12.46 | 64.5% | 216.29 |

Early updates were especially weak: step 0 had 21 groups but only 7 utility-mixed groups and 12 incomplete groups; steps 2-6 also repeatedly contained incomplete groups. The final CalBench regression (`0.639 -> 0.278`) shows that sequential SP did not preserve or compose the B/P checkpoint's external coordination behavior.

## Comparison with the original MARSHAL SP design

The checked-in MARSHAL multi-game configuration describes two core mechanisms: turn-level advantage estimation and agent-specific advantage normalization. Important differences from the custom social run are:

| Component | Original MARSHAL multi-game configuration | Custom social runs audited here |
|---|---:|---:|
| Rollout batch | 384 | approximately 32-44 games, about 18-26 reset-seat groups |
| Advantage | turn-level REINFORCE return | one centered terminal advantage copied to every valid call in a player episode |
| Normalization | agent-specific; reward and advantage whitening enabled | exact reset-seat group of four replicas; no advantage whitening |
| KL loss coefficient | 0.20 | 0.01 |
| LR schedule | cosine with minimum LR | constant `1e-6` |
| Weight decay / warmup | 0.05 / 10 steps | 0 / 0 |
| Sampling | temperature 0.6, top-p 0.99, top-k 100 | temperature 1.0, top-p 1.0, no top-k cutoff |
| Environment diversity | multiple competitive/cooperative games, including fixed-MCTS conditions | one social negotiation mechanism over 108 train resets |

No explicit historical-policy replay or EWC-style anti-forgetting mechanism was found in the original configuration. Its stability instead relies on finer turn-level returns, agent-specific normalization, a much larger batch, stronger KL regularization, learning-rate decay, and broader environment/opponent coverage.

## Conclusions supported by these runs

- B/P local supervision is the strongest tested route, but its improvement is not monotonic. Checkpoint selection must be external and mechanism-aware; the final token budget is not a valid selector.
- Pure SP can improve coordination, but the current social SP implementation is too high-variance to train safely to a fixed terminal budget.
- B/P-to-SP is not composition under the current objective. With no B/P rehearsal and coarse SP credit, it overwrites B/P behavior.
- The most direct implementation issue is not self-play itself: it is the mismatch between terminal trajectory broadcasting and MARSHAL's advertised turn-level credit assignment, amplified by four-replica groups and weak stabilization.
- Future comparisons should save multiple checkpoints and evaluate them at matched response-token budgets. Storage limitations must not be handled by deleting the only intermediate checkpoint before evaluation.

## Local evidence paths

Training:

- B/P checkpoint 99 and SP checkpoint 39: `/home/e/e1300530/tmp/MARSHAL-train-new-20260918-0f6d73a/runs/social_mixed/`
- Continued SP and incomplete B/P continuation: `/home/e/e1300530/tmp/MARSHAL-bp99-sp-stage-20260919/runs/social_mixed/`
- B/P99-to-SP27: `/home/e/e1300530/tmp/MARSHAL-bp99-sp-stage-20260919/runs/social_mixed/selfplay-seed42-861145/`
- SP39-to-SP54: `/home/e/e1300530/tmp/MARSHAL-bp99-sp-stage-20260919/runs/social_mixed/selfplay-seed42-861241/`
- B/P continuation validations: `/home/e/e1300530/tmp/MARSHAL-bp99-sp-stage-20260919/runs/social_mixed/bp-seed42-861241/validation/`

CalBench:

- B/P99: `/home/e/e1300530/tmp/MARSHAL-calbench-20260918/runs/calbench_soc/bp99-860494-formal-860852/games/results.json`
- SP39: `/home/e/e1300530/tmp/MARSHAL-calbench-20260918/runs/calbench_soc/sp39-860494-r2-formal-860876/games/results.json`
- B/P99-to-SP27: `/home/e/e1300530/tmp/MARSHAL-calbench-20260918/runs/calbench_soc/bp99-to-sp27-formal-862434/games/results.json`
- SP39-to-SP54: `/home/e/e1300530/tmp/MARSHAL-calbench-20260918/runs/calbench_soc/sp39-continued54-formal-862435/games/results.json`
