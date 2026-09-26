# Diagnostic v8: seven-model H100-47 results

Source commit: `bdb13915f9dcaa56372b229c5341c3fdb8a209f9`. Frozen manifest SHA256: `d68b700b86b26c11c8baf37af9fae7d2f9ad4ef41d85afce71649b468841bb9b`.

All seven runs exited 0 and have `COMPLETE.json`, 27/27 cases, and 108/108 raw calls. The archive contains the full run directories, including `calls.jsonl`, `results.json`, `summary.json`, `protocol.json`, vLLM logs, completion markers, and the exact Slurm launcher. No infrastructure failure or truncation was recorded; task-format failures are retained in the raw results and per-condition status counts.

Each used one H100-47 GPU, vLLM 0.28.0, BF16, TP=1, `VLLM_BATCH_INVARIANT=1`, `max_num_seqs=32`, prefix caching on, chunked prefill off, cascade attention off, eager mode, temperature 0, max output 4096, concurrency 4, seed 42, and one repeat per case. Node `xgpi17` was excluded because it had insufficient free GPU memory during the prior v7p run. The `checkpoint_hash` recorded in each protocol is the SHA256 of a sorted per-shard SHA256 listing, not the direct hash of one model file.

| Model (job) | B joint /27 | O /27 | P with gold B /27 | P with model B /27 | Repair-sensitive P gold/model /13 | Action-control P gold/model /14 |
|---|---:|---:|---:|---:|---:|---:|
| Q0 (`882107`) | 3 | 15 | 15 | 12 | 3 / 1 | 12 / 11 |
| Old BP-99 (`882111`) | 6 | 16 | 19 | 18 | 6 / 5 | 13 / 13 |
| SP-39 (`882108`) | 5 | 14 | 11 | 13 | 2 / 2 | 9 / 11 |
| SP-41 (`882110`) | 5 | 15 | 19 | 20 | 9 / 7 | 10 / 13 |
| O-99 (`882105`) | 3 | 18 | 19 | 17 | 6 / 6 | 13 / 11 |
| D-39 (`882109`) | 4 | 18 | 16 | 16 | 5 / 3 | 11 / 13 |
| micro24-39 (`882106`) | 5 | 13 | 12 | 14 | 5 / 5 | 7 / 9 |

`D-39` denotes `decomposed-step39`, distinct from `micro24-step39`. All models scored 0/8 on B joint correctness in `single_elimination` and 0/8 in `multi_update`; the per-layer B support/favored breakdown is in each `summary.json`. The two primary panels and the four evidence layers must be reported separately. Paired repair gains have model-specific valid-pair denominators and should not be inferred from aggregate correct counts; they are recorded in each summary.

This is a development diagnostic on reused validation structures, not an untouched transfer benchmark. Direct-feedback cases have simpler evidence, not necessarily simpler actions. Extract `raw_runs.tar.gz` into a scratch directory, not over a live checkout.
