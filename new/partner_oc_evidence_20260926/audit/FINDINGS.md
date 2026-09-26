# O/C versus partner-D: actual-call audit

The package README's claim that these runs also train a base O/B/P mixture is contradicted by actual micro collector calls and dataset selection. `experiment.json.mixture` is generic metadata. Raw call `kind` is also misleading for some legacy O rows: classify by the frozen dataset row's `evidence.kind` and request. No B calls occur in O/C.

Comparator: partner-D checkpoint39 (881010 training, 881481 CalBench), not original micro24 checkpoint39 (879033 evaluation). The latter uses a different bank.

All 1,920 O requests (step, task_id, replica) exactly match the corresponding partner-D requests. All 3,840 C requests likewise match partner-D. Counts: O 1,920; C O1,920/P1,920; D O1,920/P1,920/B1,280. Unique training rows 12/24/32. Thus shared-task exposure is matched, not lower in O/C.

Weights: O .5/48 rows, C 1/96, D (4/3)/128: each shared response has the same 1/96 coefficient before the response loss. Equal coefficients do not imply equal optimizer trajectories; additional task/protocol/KL terms and Adam/global clipping matter.

| CalBench | O | C | partner-D |
|---|---:|---:|---:|
| headline | .459590 | .472641 | .504938 |
| coordinated success | 3 | 3 | 7 |
| final valid meetings /72 | 34 | 35 | 38 |
| semantic invalid actions | 32 | 44 | 23 |
| new-meeting slot mismatches | 31 | 29 | 29 |
| strict envelope failures | 12 | 12 | 5 |
| untruncated games /24 | 19 | 18 | 22 |

Training correctness below counts all responses including failures; 0–9 versus 30–39 updates. This is repeated training exposure, not held-out improvement.

| domain | O arm | C arm | D arm |
|---|---|---|---|
| O | .660 → .900 | .681 → .848 | .648 → .856 |
| P | — | .460 → .721 | .492 → .756 |
| B | — | — | .484 → .956 |

Final ten updates: O-arm O truncations13/480; C O48/480, P35/480; D O45/480, P31/480, B4/320. D B starts at67/320 truncations. Final active B groups6/40 versus37/40 initially. B was learned in this bank, not permanently without contrast signal.

Interpretation: D has fewer execution/protocol failures and more full completions, but only3–4 more completed meetings and .032–.045 headline than these matched controls. This is consistent with beneficial B-inclusive training in this particular bank, not proof of a belief-mediated causal pathway. C and D O/P learning is close; O learns its own training answers most strongly yet transfers less. Additional B entails additional optimization terms and total generated tokens. Training source commits and GPU profiles differ. The original D24 9/24,.630 result cannot serve as the sole matched D arm here. No new model evaluation was run.
