# D24v1 + partner-choice D training and evaluations (job 881010)

This is the raw evidence package for the new 40-update D training run and its
checkpoint-19 and checkpoint-39 evaluations. Model weights are deliberately not
stored in Git; the final native checkpoint and both HF exports remain at the
absolute paths recorded in `training/decomposed-seed42-881010/` and
`checkpoint_metadata/`.

## Provenance and contents

- Training source checkout: `b9b99397294bf3cffa8f6a4fa82c07c729c5adb6`,
  clean when submitted. The two local commits relative to `fd93e72` are archived
  as ordered patches under `source/`. They are **not** silently merged into `new`.
- Model: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`.
- Dataset: `data_reasoning_v6`, manifest SHA256
  `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`.
  Training pool: `micro24_v1_partner_choice_v1`; detailed micro-bank and paired-bank
  hashes are in `training/decomposed-seed42-881010/experiment.json`.
- Training profile: H200-141, seed 42, O/B/P+ exposure 1:1:1, fixed 16 candidate
  groups per update, `VLLM_BATCH_INVARIANT=0`, one retained native checkpoint.
  The planned response-token budget was 5,242,880, but this job was explicitly
  capped at 40 updates and stopped after **2,438,815** response tokens. Do not
  describe it as reaching the planned token budget.
- `training/` contains the resolved config, environment, all 40 per-step metrics
  and training calls, Q0 and every 10-update validation (including per-question
  data), phase timings, warnings, checkpoint retention metadata, and full logs.
- `checkpoint_metadata/` contains the final native completeness manifest and the
  D19/D39 HF weight-load verification reports (SHA256 of exported weights).
- `source/launchers/` and `scheduler_logs/` record the actual training, export,
  and frozen evaluation launchers and Slurm stdout/stderr.
- `calbench/` and `shapefactory/` contain complete raw game results, traces,
  transport/actions/events/probes, serving profiles, server logs, and exit codes.
  Only checkpoint/model weights and regenerable CalBench `triton-*` caches were
  excluded.

## Fixed training validation (descriptive)

| Completed updates | Cumulative response tokens | B strict correct | O accuracy | P+ conditional accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 0.36 | 0.56 | 0.571 |
| 10 | 592,628 | 0.40 | 0.60 | 0.571 |
| 20 | 1,203,922 | 0.44 | 0.52 | 0.810 |
| 30 | 1,802,772 | 0.64 | 0.60 | 0.762 |
| 40 | 2,438,815 | 0.64 | 0.52 | 0.762 |

These are different conditional/denominator definitions, not interchangeable
scores. See the JSON files for coverage, truncation, pair-level outcomes, and
each question. In particular, O does not improve monotonically.

## Frozen external evaluations

CalBench used the same 24-game batch-invariant stream protocol on H100-47, with
8 parallel games, `max_num_seqs=32`, and 4,096 output tokens. ShapeFactory used
the native frozen three-player 4-game protocol on H100-47, TP=1 and 98,304
context. Both evaluation profiles set `VLLM_BATCH_INVARIANT=1`.

| Checkpoint | CalBench job | Coordinated success | Successful and optimal | Mean headline score | ShapeFactory job | Fulfilled order items | Fully fulfilled games |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 19 | 881339 | 4/24 | 2/24 | 0.448373 | 881343 | 1/12 | 0/4 |
| 39 | 881481 | 7/24 | 5/24 | 0.504938 | 881483 | 0/12 | 0/4 |

All four evaluations exited 0 and all ShapeFactory games were infrastructure
valid. All 24 CalBench games had healthy transport at each checkpoint. D19 had
22/24 untruncated games and 11 strict-envelope failures; D39 had 22/24
untruncated games and 5 strict-envelope failures. D39 retained all four D19
CalBench successes and added three, but ShapeFactory did not improve. These
observations should not be collapsed into one generalized social-reasoning gain.
