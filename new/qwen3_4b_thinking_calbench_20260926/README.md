# Qwen3-4B thinking-mode CalBench stream result

This package archives the complete 24-game run `877057`. The model was
`/home/e/e1300530/models/Qwen3-4B`, **not** the separate
`Qwen3-4B-Instruct-2507` non-thinking baseline. The launcher verified that
the model's default chat template equals `enable_thinking=True` and differs
from `enable_thinking=False`; raw responses include `<think>` blocks.

The run used the frozen 24-game stream suite, temperature 0, 4,096 output
tokens, one H100-47, TP=1, eight parallel games, `max_num_seqs=32`,
`VLLM_BATCH_INVARIANT=1`, prefix caching on, chunked prefill off, cascade
attention off, and eager execution. The recorded model-file hashes and runtime
details are in `execution_identity.json` and `runtime_environment.json` within
the raw archive.

| Completed meetings | Fully coordinated games | Successful and optimal | Mean headline score | Mean messages/game | Mean native `fairness_cost` |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 43/72 | 7/24 | 4/24 | 0.557326 | 24.333 | 0.557292 |

Verified excess team cost over the reference optimum totals 16 across the
seven fully successful games, or **2.285714 per successful game / 0.571429
per agent per successful game**. This cost is not assigned zero to failed
games. All 24 games finished with healthy transport, but only 10/24 were
fully untruncated; there were 23 strict-envelope failures across the panel.
These limitations matter when interpreting cooperation performance.

- `calbench_qwen3_4b_thinking_877057.tar.gz`: all raw game results, traces,
  events, transport logs, execution metadata, and server log. Only regenerable
  `triton-*` caches are omitted.
- `launcher_and_scheduler_877057.tar.gz`: the exact submission script and
  Slurm stdout/stderr.
- `SHA256SUMS`: integrity hashes for both archives.
