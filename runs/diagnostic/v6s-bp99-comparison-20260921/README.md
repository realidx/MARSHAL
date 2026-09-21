# Strengthened diagnostic v6: old versus new BP-99

These are the complete deterministic results for strengthened diagnostic v6 at source commit `6467c50f6e0f9a4216c0b6527914aab0ebefff66`.

| Model | Slurm job | Result directory | Checkpoint SHA256 |
|---|---:|---|---|
| old BP-99 | 870332 | `../old-bp99-v6s-biinv-v1-870332/` | `aab6fdb53542132f3818909f533678b5d01d31ce984e53674ebf90e14b737ab9` |
| new BP-99 | 870333 | `../new-bp99-v6s-biinv-v1-870333/` | `da1e2d41b3b041b64cf67a9961f6b9cab4e0338f490b6f2fb7747110070515d3` |

Both runs completed 96/96 rows and 408/408 model calls with exit code zero. All three repeats were exactly stable for B, correct-B planning, model-B planning, end-to-end planning, and the complete scored rows.

The frozen inference profile used `VLLM_BATCH_INVARIANT=1`, BF16, TP=1, eager mode, `max_num_seqs=32`, prefix caching enabled, chunked prefill disabled, cascade attention disabled, no speculative decoding, temperature zero, three repeats, 4096 maximum output tokens, and runner concurrency eight.

## Structure-level results

| Metric | old BP-99 | new BP-99 |
|---|---:|---:|
| B exact | 0.15625 | 0.15625 |
| B set exact | 0.43750 | 0.50000 |
| B favored exact | 0.15625 | 0.15625 |
| B false exclusions | 0.25000 | 0.12500 |
| B unsupported additions | 0.90625 | 0.87500 |
| correct-semantic-B planning regret | 0.828125 | 1.135417 |
| model-B planning regret | 0.568182 | 0.845238 |
| end-to-end P regret | 0.690476 | 0.854167 |
| B repair gain | -0.143939 | -0.309524 |

The paired-scoring identity uses identical valid rows and identical structure weights. Old BP-99 has 48 paired rows across 11 structures; model-B regret is 0.522727, correct-semantic-B regret is 0.666667, and repair gain is -0.143939. New BP-99 has 72 paired rows across 14 structures; the corresponding values are 0.839286, 1.148810, and -0.309524. Both have zero row identity failures and zero numerical identity residual up to floating-point roundoff.

Every retained semantic region is certified decision-sufficient by exact rational polytope vertex enumeration, and matched voluntary/preset invariant optimal-action sets are disjoint. Thus the negative repair gains cannot be attributed to missing posterior magnitudes in the deployed semantic B interface.

Each result directory contains the complete protocol, completion manifest, raw 408-call JSONL, 96 scored rows, summary, frozen profile, and server log. `SUBMISSION.sh` is the exact launcher used for both jobs.
