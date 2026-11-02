# CalBench v6/v8 diagnostic run data

This directory contains the complete raw output for four H100-47 runs, organized as two registered belief-MS versions across two checkpoints:

| Directory | Job | Checkpoint / condition | Case outcome |
|---|---:|---|---|
| `qwen_base_v6_1060153/` | 1060153 | Qwen3-4B-Instruct-2507, belief-MS v6 | 16 cases started; 15 completed, 1 MS truncation; 8 not started |
| `qwen_base_v8_1060433/` | 1060433 | Qwen3-4B-Instruct-2507, belief-MS v8 | 24 attempted; 20 completed, 4 unresolved after an MS truncation and one same-prompt retry |
| `outcome99_v6_1060154/` | 1060154 | outcome-99 step99, belief-MS v6 | 8 cases started; 7 completed, 1 MS truncation; 16 not started |
| `outcome99_v8_1060434/` | 1060434 | outcome-99 step99, belief-MS v8 | 24 attempted; 20 completed, 4 unresolved after an MS truncation and one same-prompt retry |

Each run directory preserves its original run files, including job submission metadata, resolved routes, model identity, runtime environment, server logs, pipeline snapshots, frozen suite manifest, per-case scenarios and references, events/traces/results, scaffold receipts, and raw transport JSONL. The transport records contain the exact requests and model responses, completion usage, finish reasons, retry attempt numbers, and acceptance/error status needed to inspect the visible MS loops. Missing or aborted game outcomes remain missing; they are not filled with zeroes.

No model weights are included. The dataset is approximately 137.6 MiB across 1,416 files; the largest individual file is about 0.4 MiB. These are ordinary tracked files; no Git LFS or external blob store is used.

The associated summaries are [v6 results](../../CALBENCH_BELIEF_MS_V6_H10047_20261102.md) and [v8 results](../../CALBENCH_BELIEF_MS_V8_H10047_20261102.md). The registered snapshots are [v6](../../../strategic_slices/versions/general_ms_calbench_v6_20261102/SNAPSHOT.json) and [v8](../../../strategic_slices/versions/general_ms_calbench_v8_20261102/SNAPSHOT.json).
