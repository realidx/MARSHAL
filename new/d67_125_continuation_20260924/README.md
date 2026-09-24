# D training continuation: updates 68–125

This bundle archives the original output of Slurm job `876729`, resumed from
`checkpoint-66` of job `876617`. The source checkout was clean at commit
`5110db0ebc8515eda3d82495cf3b7b3c1de58075`.

- Run: `runs/social_mixed/decomposed-seed42-876729`
- Result: `paused` at 125 completed updates (last zero-based token block 124),
  5,343,723 training response tokens against a 6,553,600-token budget.
- Final native checkpoint: `checkpoint-124`. Its `COMPLETE.json` listed 18
  files; every file was checked for existence and exact size. Weights and
  optimizer state are deliberately excluded from Git.
- Scheduled static validations: steps 80, 100, and 120. The final update 125
  was not separately validated.
- The archive contains original per-step metrics and calls, validation
  trajectories, O monitoring, probability warnings, resolved configuration,
  phase timing, topology, and `RESULT.json`/`EXIT_CODE`. No log fields were
  rewritten. To unpack: `tar -xzf d67-125-continuation.tar.gz`.
- Archive SHA256:
  `3cc339a3345b580bc26608c90837b877388759edb80191a9799328e54881b1b5`.

The `calbench/` subdirectories preserve results and execution metadata for
the frozen 24-game, batch-invariant profile at D-67, D-79, D-99, and D-119.
All four have `EXIT_CODE=0` and 24/24 finished games:

| Checkpoint | Coordinated | Successful and optimal | Mean headline | Untruncated | Strict envelope failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| D-67 | 8/24 | 4/24 | 0.573506 | 22/24 | 3 |
| D-79 | 4/24 | 3/24 | 0.435929 | 22/24 | 3 |
| D-99 | 6/24 | 5/24 | 0.555818 | 20/24 | 6 |
| D-119 | 6/24 | 3/24 | 0.527802 | 21/24 | 7 |

These checkpoints show no monotonic CalBench improvement. D-119 ties D-99
on coordinated success but has fewer optimal games and a lower mean score.
The D-67 training logs are in `new/d67_training_20260924`; do not interpret
the CalBench counts as a smooth learning curve.
