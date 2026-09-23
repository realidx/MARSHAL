# D training and evaluation raw evidence (2026-09-24)

This directory preserves the available raw evidence for the D (O/B/Pplus)
experiments. Each `.tar.gz` is rooted at the corresponding run directory:
`tar -xzf ARCHIVE -C DESTINATION`. Verify downloads with
`sha256sum -c SHA256SUMS` from this directory.

## Training

| Archive | Slurm run | Contents and provenance |
| --- | --- | --- |
| `training/d0-11-873477.tar.gz` | 873477 | Earlier D chain, Q0 through update 12; recorded source commit `eb71f78be3a36fc531c6a448a667666dfd9aa332`. |
| `training/d53-873641.tar.gz` | 873641 | Earlier D chain, updates 13–54, resumed from checkpoint-11 of 873477; recorded source commit `2965091d4e1de1ee2d88c095ad87d71f6e49c270`. |
| `training/d0-72-874127.tar.gz` | 874127 | New fixed-coverage D chain, Q0 through update 73; recorded source commit `0ac09eb3b7bca7d15711d1c9f3293d6b42f89917`. |
| `training/d72-148-875169.tar.gz` | 875169 | Continuation, updates 74–148, resumed from checkpoint-72 of 874127; same recorded source commit. |

Training archives contain the original `calls/`, `games/`, `validation/`,
`static_o_monitor/`, `units/`, `logs/`, per-update `metrics.jsonl`,
`phases.jsonl`, probability warnings, resolved/experiment/environment
configuration, and train logs where present. The native checkpoint tensor
directories (`checkpoints/` and `actor_train-0/`) and transient pipeline
checkpoint directory are intentionally excluded. The archives are **raw logs,
not resumable model checkpoints**. The `experiment.json` inside each archive
is authoritative for that run's data manifest hash, source bundle hash,
actual options, and resume source.

## Formal 24-game CalBench

| Archive | Model | Full successes | Meetings completed | Mean headline |
| --- | --- | ---: | ---: | ---: |
| `calbench/d53-874013.tar.gz` | Older D-53 | 5/24 | 38/72 | 0.488 |
| `calbench/d19-874430.tar.gz` | New D-19 | 5/24 | 37/72 | 0.504 |
| `calbench/d39-874492.tar.gz` | New D-39 | 6/24 | 37/72 | 0.488 |
| `calbench/d72-875168.tar.gz` | New D-72 | 6/24 | 40/72 | 0.522 |
| `calbench/d119-875538.tar.gz` | New D-119 | 5/24 | 37/72 | 0.476 |
| `calbench/d148-876196.tar.gz` | New D-148 | 4/24 | 36/72 | 0.474 |

These contain every saved game `trace.json`, transport log, scenario and
manifest, plus run identity, runtime settings, server log, and completion
marker. Generated `triton-0/` compilation caches are excluded. D-148 ran
on H100-47; the run-specific metadata records the exact environment.
The training-internal eight-game validation is in the training archives and
must not be treated as the same measurement as this formal 24-game suite.

## Strengthened diagnostic v6

| Archive | Model | Slurm job |
| --- | --- | ---: |
| `diagnostic/d53-876226.tar.gz` | Older D-53 | 876226 |
| `diagnostic/d72-876227.tar.gz` | New D-72 | 876227 |
| `diagnostic/d148-876228.tar.gz` | New D-148 | 876228 |

These preserve `structure_v6/calls.jsonl`, per-row results, protocol,
summary, completion audit, frozen profile, and server log. The diagnostic
used temperature 0, three repeats, and `VLLM_BATCH_INVARIANT=1`.
All three runs completed 96/96 structure replicas. Effective paired-planning
coverage differs because some controlled-P outputs failed formatting; use
the paired rows and weights in each `summary.json` when comparing B repair.

No HF weight files are included. In particular, the D-119 HF export had
already been deleted at the user's request, but its previously completed
CalBench raw trace remains archived.
