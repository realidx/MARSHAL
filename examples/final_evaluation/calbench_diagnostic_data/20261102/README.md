# CalBench native/base-prompt run data

This bundle retains the two original ordinary-prompt conditions. Previous MS run records were removed at the user's request.

| Directory | Job | Checkpoint / prompt | Completed cases |
|---|---:|---|---:|
| `qwen_base_prompt_1059395/` | 1059395 | Qwen3-4B-Instruct-2507, native/base prompt | 24/24 |
| `outcome99_base_prompt_872963/` | 872963 | outcome-99 step99, native/base prompt | 24/24 |

Both saved frozen manifests have identical case IDs, scenario seeds and game configuration. Both use a4096-token output cap, temperature0, and record prompt_changed=false.

The original raw requests/responses, scenario/reference files, events, traces, results and available model/runtime metadata are retained unchanged. The outcome-99 archive did not contain pipeline_snapshot.json or job_submission.json; neither was invented. Qwen's original full pipeline snapshot is retained. No weights or runtime compilation caches are included.

See the [native run report](../../CALBENCH_NATIVE_BASE_PROMPT_H10047_20261102.md). No new model calls, training, reward change or D measurement were made.
