# New-D strengthened v6 diagnosis (completed runs)

These are raw outputs from the frozen strengthened `diagnostic_v6` profile,
source commit `2965091d4e1de1ee2d88c095ad87d71f6e49c270`.
Each run used one H100-47, `VLLM_BATCH_INVARIANT=1`, temperature 0,
`max_num_seqs=32`, concurrency 8, 4096 output tokens, prefix caching on,
chunked prefill and cascade attention off, and three repeats. The exact
profile, model-weight hash, calls, results, summary, completion certificate,
and server log are preserved in each directory.

All four archived runs have `EXIT_CODE=0`, 96/96 returned rows, zero missing
rows, and a `structure_v6/COMPLETE.json` certificate.

| Model | Job | B exact | Gold-B P regret | End-to-end P regret | Paired B repair gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| D-40 | 877002 | 0.09375 | 0.788889 | 0.854167 | -0.018519 |
| D-67 | 877003 | 0.12500 | 0.802083 | 0.807292 | -0.141026 |
| D-79 | 877004 | 0.12500 | 0.796875 | 0.932292 | -0.255952 |
| D-99 | 877005 | 0.09375 | 0.854167 | 0.729167 | -0.310606 |

The condition-specific regrets can have different valid subsets; do not
subtract them to reconstruct repair gain. The latter is computed on paired
rows, as documented in each `summary.json`. D-119 (job 877006) was still
running when this archive was made and is intentionally excluded.
