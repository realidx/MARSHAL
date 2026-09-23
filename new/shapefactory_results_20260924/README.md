# ShapeFactory evaluation evidence (2026-09-24)

This directory archives completed results from the local ShapeFactory evaluation worktree. It contains the raw per-agent request/response traces, cycles, events, final states, per-game results, aggregate summaries, execution identity, routes, and runtime environment. `runs/*/games/COMPLETE` and `runs/*/EXIT_CODE` should both be checked before interpreting a run. Server logs and Triton caches are omitted.

| Run | Scope | Outcome |
| --- | --- | --- |
| `q0-base-shape24-874022` | Original adapted 12 cases x private/dashboard | 0 order completion in both conditions; this is an adapted fixed-clock run, not a reproduction of the paper's native real-time controller. |
| `q0-lite-876601` | Lite v1, 2 cases x 2 visibility conditions | 0/8 items, 0 accepted trades; 18 parse failures and 36 execution rejections. |
| `old-bp99-lite-876612` | Lite v1, same cases | 0/8 items, 0 accepted trades; 19 parse failures and 42 execution rejections. |
| `q0-lite-v2-876613` | Lite v2, same cases | 0/8 items, 0 accepted trades; 2 post-normalization parse failures and 82 execution rejections. |
| `old-bp99-lite-v2-876614` | Lite v2, same cases | 0/8 items, 0 accepted trades; 4 post-normalization parse failures and 76 execution rejections. |

Lite is a separate diagnostic, not the original benchmark. V1 and v2 changed adapter behavior and prompt presentation, so parse-failure and rejection counts are not directly comparable. Neither version automatically executes a model action. The v2 results show repeated unsupported offers and sparse production; in one old-B/P game the model later selected `fulfill_order` when the correct item was in inventory, but malformed JSON prevented execution. Thus zero fulfillment mixes task-state/planning errors and protocol errors, and cannot alone measure social reasoning.

`source/` holds the exact v2 Lite runner and adapter snapshots where their SHA256 matches the `execution_identity.json` of the v2 runs. The earlier full 24-game run used a different adapter hash; its identity is preserved, but that historical source snapshot is not claimed here. `diagnostics/` holds the prior offline normalization and isolated stock-state checks. The original live worktree was dirty and was not modified for this archive; this results-only commit does not merge its code into the official evaluation pipeline.
