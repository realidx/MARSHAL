# CalBench diagnostic run data

This bundle retains the two native/base-prompt baseline conditions and the separately requested v11-minimal scaffold runs. Older MS experiment records, including v6/v8 outputs, remain excluded; the v11-minimal data below is the new scaffold-prompt evaluation recorded on 2026-11-02.

| Directory | Job | Checkpoint / prompt | Completed cases |
|---|---:|---|---:|
| `qwen_base_prompt_1059395/` | 1059395 | Qwen3-4B-Instruct-2507, native/base prompt | 24/24 |
| `outcome99_base_prompt_872963/` | 872963 | outcome-99 step99, native/base prompt | 24/24 |

Both saved frozen manifests have identical case IDs, scenario seeds and game configuration. Both use a4096-token output cap, temperature0, and record prompt_changed=false.

The original raw requests/responses, scenario/reference files, events, traces, results and available model/runtime metadata are retained unchanged. The outcome-99 archive did not contain pipeline_snapshot.json or job_submission.json; neither was invented. Qwen's original full pipeline snapshot is retained. No weights or runtime compilation caches are included.

See the [native run report](../../CALBENCH_NATIVE_BASE_PROMPT_H10047_20261102.md). No model calls, training, reward change or D measurement were added when packaging these archived results.

## v11-minimal scaffold runs

The raw diagnostic package is in [v11-minimal results](v11_minimal/README.md). It contains Qwen base job 1063236 (23/24 engine-finished) and outcome-99 step99 job 1063239 (22/24), along with the two pre-launch failure logs. Regenerable Triton/compiler caches and model weights are excluded. See the [v11 run report](../../CALBENCH_V11_MINIMAL_H10047_20261102.md).


## v12-inbox scaffold runs

The raw data is in [v12-inbox results](v12_inbox/README.md): Qwen base job 1063524 (24/24 engine-finished) and outcome-99 step99 job 1063527 (22/24). The package preserves per-case requests/responses, traces, pipeline snapshots, audits and Slurm/vLLM logs; weights and regenerable compiler caches are excluded. See the [v12 report](../../CALBENCH_V12_INBOX_H10047_20261102.md).
