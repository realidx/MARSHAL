# CalBench v12-inbox scaffold diagnostic data

This archive contains the raw outputs for the two user-authorized v12-inbox tests on the frozen `calbench_stream_v1` 24-case suite.

| Directory | Job | Checkpoint | Attempted / engine-finished | Unresolved |
|---|---:|---|---:|---|
| `qwen_base_1063524/` | 1063524 | Qwen3-4B-Instruct-2507 base | 24 / 24 | none |
| `outcome99_step99_1063527/` | 1063527 | outcome-99 step99 | 24 / 22 | `replan_varied_s2`, `replan_varied_s3` |

Each run preserves raw per-case MS/ACTION requests and responses, scenarios/references, events, traces, results, case ledgers, model/runtime identity, submission metadata, root/per-case `pipeline_snapshot.json`, `trace_audit.json`, vLLM server logs and Slurm stdout/stderr. Unresolved utilities remain missing, not zero-filled.

Regenerable Triton/compiler caches and model weights are excluded. See the [v12 H100-47 report](../../../CALBENCH_V12_INBOX_H10047_20261102.md), [v12 registration snapshot](../../../../strategic_slices/versions/general_ms_calbench_v12_inbox_20261102/SNAPSHOT.json), and [parent CalBench data index](../README.md). The older v11 package remains separately identified.
