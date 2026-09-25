# Diagnostic v7: Q0 versus D24v1-step39

Source commit: `0d85f43dec75b63eb71604c19f186d2cda9c8ce9`.
Frozen case manifest SHA256: `0ae7b7247091d23c57f8a5f7983b77334337e375d701cd33e6c8947e9af5e9f6`.

Runs: D24v1-step39 job `881891`; Q0 job `881892`. Both exited 0 and produced `COMPLETE.json`, 32/32 case results and 128/128 raw calls. No truncation or infrastructure failure was recorded. The archive contains both complete run directories, including `calls.jsonl`, `results.json`, `summary.json`, `protocol.json`, service logs, completion markers, and the submission wrapper.

Both used one H100-47 MIG, vLLM 0.28.0, BF16, TP=1, `VLLM_BATCH_INVARIANT=1`, `max_num_seqs=32`, prefix caching on, chunked prefill off, cascade attention off, eager mode, temperature 0, max output 4096, concurrency 4, seed 42, and one repeat per case. Model weight identity hashes are recorded in each run's protocol.

| Metric (32 cases) | Q0 | D24v1-step39 |
|---|---:|---:|
| B exact | 5 | 5 |
| O correct | 20 | 16 |
| P with gold B correct | 9 | 11 |
| P with model B correct | 7 | 7 |

This is a development diagnostic, not an untouched transfer benchmark. The 16 repair-sensitive cases and 16 action controls must be reported separately. On repair-sensitive cases, B exact was 2/16 for both; O correct was 7/16 for Q0 versus 4/16 for D24v1; P with model B correct was 1/16 versus 0/16. The apparent gain with gold B does not establish improved model-generated partner beliefs.

Archive: `raw_runs.tar.gz` (SHA256 listed in `SHA256SUMS`). Extract at a scratch directory to recover the original `runs/diagnostic_v7/...` paths. Do not extract over a live training checkout.
