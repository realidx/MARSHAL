# CalBench base-prompt and v8 diagnostic data

This bundle contains four conditions: base prompt/native and belief-MS v8 for each checkpoint.

| Directory | Job | Checkpoint / prompt | Completed cases |
|---|---:|---|---:|
| `qwen_base_prompt_1059395/` | 1059395 | Qwen3-4B-Instruct-2507, native/base prompt | 24/24 |
| `qwen_base_v8_1060433/` | 1060433 | Qwen3-4B-Instruct-2507, belief-MS v8 | 20/24; 4 MS prompts exhausted retry |
| `outcome99_base_prompt_872963/` | 872963 | outcome-99 step99, native/base prompt | 24/24 |
| `outcome99_v8_1060434/` | 1060434 | outcome-99 step99, belief-MS v8 | 20/24; 4 MS prompts exhausted retry |

The four saved frozen manifests have identical case IDs, scenario seeds, and game configuration. All use the native 4096-token output cap and temperature 0. The two base-prompt runs record `prompt_changed=false`; v8 adds the registered independent belief-MS stage and retries only a failed prompt once in place.

Each run folder contains its available original routes, model identity, runtime/server information, frozen manifest, result files, and per-case raw requests/responses and traces. The v8 folders also include `case_results.json` with each prompt attempt and physical cost. The O99 native run was recovered from its existing CalBench archive; that archive includes routes, runtime/server logs, model identity, the frozen manifest, all 24 results and game traces, and the original Slurm output. It did **not** include `pipeline_snapshot.json` or `job_submission.json`, so those files were not invented. The Qwen native and both v8 runs retain their original full pipeline snapshots.

Aborted v8 case outcomes remain missing, not zero-filled. Their four failures per model are MS-stage `finish_reason=length` at 4096 tokens; the single retries reproduce the first response exactly. For details see [the v8 run report](../../CALBENCH_BELIEF_MS_V8_H10047_20261102.md) and [the four-condition comparison](../../CALBENCH_BASE_PROMPT_AND_V8_H10047_20261102.md).

No model weights or runtime compilation caches are included. The package is plain JSON/JSONL and log files, approximately 159 MiB; the largest individual file is below 0.5 MiB. It uses ordinary Git files, not Git LFS or an external blob service.
