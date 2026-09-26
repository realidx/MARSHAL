# Diagnostic v7p: seven-model comparison

Source commit: `6aeecffdcd0b8e4e7cbca325ba63f050ad7ee846` (`origin/new` at submission). Frozen diagnostic manifest SHA256: `1d551ccb6a2825e71f709e6e52a21dd8b3f321dad2dbe14be472969b5c1ca676`.

All seven successful H100-47 runs exited 0 and have `COMPLETE.json`, 32/32 case results, and 128/128 raw calls. The archive includes the complete run directories (`calls.jsonl`, per-case results, summaries, protocols, service logs, completion markers) and the submission wrapper. The original SP-39 and SP-41 attempts (`882077`, `882078`) failed during vLLM startup on `xgpi17` because only 22.13/93.09 GiB GPU memory was free; their replacement runs below excluded that node. These startup failures are not model outcomes.

Each run used one H100-47 GPU, vLLM 0.28.0, BF16, TP=1, `VLLM_BATCH_INVARIANT=1`, `max_num_seqs=32`, prefix caching on, chunked prefill off, cascade attention off, eager mode, temperature 0, max output 4096, concurrency 4, seed 42, and one repeat per case. `checkpoint_hash` in each protocol is the SHA256 of the sorted per-shard SHA256 listing; it is a weight identity, not the raw model-file SHA256.

| Model (job) | B exact /32 | O correct /32 | P with gold B /32 | P with model B /32 | Mean paired repair gain (valid pairs) |
|---|---:|---:|---:|---:|---:|
| Q0 (`882075`) | 5 | 20 | 7 | 11 | -0.085 (27) |
| Old BP-99 (`882076`) | 5 | 20 | 16 | 13 | +0.407 (26) |
| SP-39 (`882079`) | 5 | 15 | 14 | 13 | +0.166 (30) |
| SP-41 (`882080`) | 5 | 19 | 15 | 13 | +0.187 (29) |
| O-99 (`882081`) | 5 | 22 | 19 | 19 | -0.031 (32) |
| D-39 (`882082`) | 5 | 18 | 17 | 13 | +0.400 (30) |
| micro24-39 (`882084`) | 5 | 16 | 16 | 16 | +0.119 (30) |

`D-39` is `decomposed-step39`, distinct from `micro24-step39`. B exact is 5/32 for every model, but the five correct cases are not identical. Paired repair gain is computed only where both P interventions are valid; its denominator varies by model. The 16 repair-sensitive cases and 16 action controls are reported separately in each `summary.json` and should not be collapsed for mechanism claims.

This is a development diagnostic using reused validation structures, not an untouched transfer benchmark. v7p aligns the P interface with training while keeping B/O at the v7 diagnostic interface. It does not establish that all three interfaces match training or that a difference is caused by one P prompt field alone. Extract `raw_runs.tar.gz` into a scratch directory, not over a live checkout.
