# CalBench v11-minimal scaffold diagnostic data

This archive supplements the [native/base-prompt baseline data](../README.md) with the two explicitly requested v11-minimal scaffold runs. The 24-case suite and scoring are the same frozen `calbench_stream_v1` used for the native baseline.

| Directory | Job | Cases attempted / engine-finished | Unresolved cases |
|---|---:|---:|---|
| `qwen_base_1063236/` | 1063236 | 24 / 23 | `blocked_varied_s3` |
| `outcome99_step99_1063239/` | 1063239 | 24 / 22 | `replan_uniform_s1`, `replan_varied_s1` |

Each run directory preserves the raw per-case requests and responses, frozen scenarios and references, result ledgers, traces, event logs, runtime/model identity, submission metadata when present, and root/per-case `pipeline_snapshot.json` files. `trace_audit.json` is the corresponding read-only canonical metrics audit. The two runs exited successfully after recording all 24 case outcomes; unresolved cases are documented as missing, not zero-valued.

`startup_failures/` contains stdout/stderr for the initial submissions 1063222 and 1063224. Both failed before model launch due to a submission-script syntax error and made no model requests.

Reproducible Triton/compiler caches and model-weight files are excluded. This archive does not include training data, checkpoint weights, or generated binaries. The retry-controller label in run ledgers (`calbench-prompt-retry-once-v8`) refers to the unchanged retry implementation; the evaluated scaffold prompt is v11-minimal.

See the [v11-minimal run report](../../CALBENCH_V11_MINIMAL_H10047_20261102.md) and [registered execution record](../../../../strategic_slices/versions/index.json).
