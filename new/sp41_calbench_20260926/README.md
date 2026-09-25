# SP-41 frozen CalBench stream run

This package archives the complete 24-game SP-41 evaluation, Slurm job
`874283`. The loaded HF model was
`/home/e/e1300530/tmp/hf-exports-873855/sp41-final`; model-file hashes are
recorded in the run's `execution_identity.json`. No model weights are stored
in Git.

The run used the frozen 24-game stream suite with temperature 0, 4,096 output
tokens, `VLLM_BATCH_INVARIANT=1`, one H100-96, TP=1, eight parallel games,
`max_num_seqs=32`, prefix caching enabled, chunked prefill disabled, cascade
attention disabled, and eager execution. See the raw protocol, server command,
and runtime metadata for the authoritative settings.

| Completed meetings | Fully coordinated games | Successful and optimal | Mean headline score | Mean messages/game | Mean native `fairness_cost` |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 37/72 | 6/24 | 4/24 | 0.486894 | 25.667 | 0.755208 |

The verified extra team cost across the six fully successful games is 15,
equivalent to **0.625 per agent per successful game**. No cost is imputed for
failed games. All 24 games finished with healthy transport, 21/24 were fully
untruncated, and the panel recorded five strict-envelope failures.

- `calbench_sp41_874283.tar.gz`: full raw game results, traces, events,
  transport logs, execution identity, server log, and protocol. Only
  regenerable `triton-*` caches are omitted.
- `launcher_and_scheduler_874283.tar.gz`: the frozen CalBench launcher and
  Slurm stdout/stderr.
- `SHA256SUMS`: archive integrity hashes.
