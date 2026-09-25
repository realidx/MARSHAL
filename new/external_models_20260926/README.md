# MARSHAL Generalist and Social-R1 external-model evaluations (2026-09-25/26)

This directory archives the four completed raw runs, including per-game CalBench
results/traces/transport logs, ShapeFactory actions/events/probes/metrics, serving
logs, and execution metadata. Only regenerable `triton-*` cache directories from
CalBench were excluded. All four launchers reported `EXIT_CODE=0`.

| Model | Hugging Face repository | Pinned revision |
| --- | --- | --- |
| MARSHAL Generalist | `nics-efc/MARSHAL-Generalist-Qwen3-4B` | `267b80a4c6b6ba09a81fa7bdeacf11ebcdc3d78c` |
| Social-R1-4B | `Jincenzi/SocialR1-4B` | `878c3119cec1b903d2f482430935ebaa4b72e355` |

Both were served from complete local Hugging Face snapshots. Their default Qwen3
chat templates matched explicit `enable_thinking=True`; no model-specific benchmark
prompt was added. The frozen serving profile used `VLLM_BATCH_INVARIANT=1`, TP=1,
BF16, eager execution, prefix caching enabled, and chunked prefill and cascade
attention disabled. All jobs used one H100-47 MIG allocation on the `gpu` queue.

## CalBench frozen 24-game stream

The profile was `calbench-stream-batch-invariant-v1`: 8 parallel games,
`max_num_seqs=32`, and 4,096 output tokens. See the raw
`calbench/<run>/execution_identity.json` and `games/execution_protocol.json`.

| Model (job) | Coordinated success | Successful and optimal | Mean headline score | Healthy transport | Untruncated games | Strict-envelope failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MARSHAL Generalist (881115) | 6/24 | 1/24 | 0.438558 | 24/24 | 13/24 | 15 |
| Social-R1-4B (881116) | 5/24 | 1/24 | 0.466026 | 24/24 | 24/24 | 11 |

MARSHAL's 11 games with truncated generations make its score a censored test of
the thinking-mode model at this output cap. Do not interpret the difference as
an isolated model-capability effect. Raw data are under `calbench/`.

## ShapeFactory / frozen CollabSim v3, native three-player lite

Four games were run for each model: forward/reverse order and private/dashboard
information. The frozen serving profile had `max_model_len=98304`,
`max_num_seqs=32`, and `gpu_memory_utilization=0.65`. Both model configs declare
`max_position_embeddings=40960`; `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` was required
to keep the frozen 98,304-token protocol. This is **outside the models' declared
context**; long-context failures or behavior must be interpreted accordingly.
See `shapefactory/<run>/SERVING_PROFILE.txt` and the native protocol/results.

| Model (job) | Fulfilled order items | Games fulfilling all orders | Successful trades | Valid runs |
| --- | ---: | ---: | ---: | ---: |
| MARSHAL Generalist (881117) | 6/12 | 2/4 | 6 | 4/4 |
| Social-R1-4B (881119) | 5/12 | 0/4 | 8 | 4/4 |

The two MARSHAL fully fulfilled games were forward-private and reverse-dashboard.
Neither model consistently completed the four-game set. Raw native actions,
events, probes, traces, and per-game metrics are under `shapefactory/`.
