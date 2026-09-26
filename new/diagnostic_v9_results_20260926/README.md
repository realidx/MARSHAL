# Diagnostic v9: seven-model H100-47 results

Source commit: `7e4b68d0fc8b26fcacf6a9126bee8e88775eed7f`. Frozen manifest SHA256: `d843b2624908f8027ef606506ff9e97baea421b5f7fe46075a97608756cfdec5`.

All seven runs exited 0 and have `COMPLETE.json`, 22/22 case results, and 88/88 raw calls. No infrastructure failure or truncation was recorded. Each model had 1–4 task-format failures, retained in the raw results. The archive contains complete run directories: raw requests/completions, per-case results, summaries, protocols, serving profiles, server logs, and completion markers. Both launcher files are included: the v9 wrapper calls the parameterized v8-named serving launcher.

Configuration: one H100-47 GPU per job, vLLM 0.28.0, BF16, TP=1, `VLLM_BATCH_INVARIANT=1`, `max_num_seqs=32`, prefix caching on, chunked prefill off, cascade attention off, eager mode, temperature 0, max output 4096, runner concurrency 4, seed 42, one repeat. Node `xgpi17` was excluded following prior GPU-memory contention. Protocol `checkpoint_hash` values were reused from the same exports in the prior runs: SHA256 of a sorted per-shard SHA256 listing, not a direct single-file hash.

| Model (job) | B joint /22 | O /22 | P gold B /22 | P model B /22 | Repair-sensitive P gold/model /9 |
|---|---:|---:|---:|---:|---:|
| Q0 (`882149`) | 11 | 11 | 11 | 11 | 3 / 3 |
| Old BP-99 (`882153`) | 11 | 13 | 14 | 13 | 5 / 4 |
| SP-39 (`882146`) | 14 | 10 | 11 | 10 | 1 / 1 |
| SP-41 (`882147`) | 9 | 12 | 16 | 11 | 6 / 1 |
| O-99 (`882148`) | 11 | 15 | 12 | 13 | 4 / 4 |
| D-39 (`882151`) | 12 | 14 | 14 | 14 | 5 / 4 |
| micro24-39 (`882150`) | 12 | 14 | 12 | 12 | 4 / 3 |

`D-39` is `decomposed-step39`, distinct from `micro24-step39`. All models scored 6/6 on direct-feedback B, but only 2–4/6 on direct-feedback P with gold B. For single-elimination B, SP-39 scored 2/6 and all others 0/6. For multi-update B, SP-41 scored 1/4 and all others 0/4. These counts do not by themselves distinguish inference failures from set-expression failures.

Report the 12 basic and 10 challenge cases separately, along with evidence layers and the 9 repair-sensitive/13 action-control panels. Multi-update cases are controls, not evidence of belief-to-action transfer. Paired repair gains use model-specific valid-pair denominators; SP-41's repair-sensitive mean gain is +0.8375 over 8 valid pairs. Raw summaries retain all denominators and failures.

This is a development diagnostic, not an untouched transfer benchmark. v9 changes both cases and B prompts relative to v8; cross-version score changes are not model learning. Extract `raw_runs.tar.gz` into a scratch directory, not over a live checkout. Archive checksum is in `SHA256SUMS`.
