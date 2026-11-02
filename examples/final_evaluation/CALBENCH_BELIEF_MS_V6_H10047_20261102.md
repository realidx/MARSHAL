# CalBench24 belief-MS v6 H100-47 evaluation

Status: both jobs ended early after a single MS length truncation each. Qwen produced 16/24 case records (15 engine-finished and scaffold-healthy, 1 failed; the remaining 8 were not started) in 14:08. outcome-99 produced 8/24 records (7 engine-finished and scaffold-healthy, 1 failed; 16 were not started) in 7:52. Both workers passed preflight and all result records report healthy transport.

## Code reviewed and registered

Pulled `origin/game-slice` commit `bae0a3bef14a6dd7661ce7d950d7fe425727f188`. The registered version is [general-belief-ms-v6-user-prompt](../strategic_slices/versions/general_ms_calbench_v6_20261102/SNAPSHOT.json); its full request preview and CPU-only validation evidence are in that version directory.

The v6 protocol uses two calls within each native action request. It appends the exact registered brief belief/MS prompt as a separate user message after the complete native request. The actual first response is then carried as an assistant message, followed by a user Action Stage prompt that asks the model not to repeat the MS or narrate future execution. Only the final native action is returned to the environment. Stage messages do not persist into later native history. The total generation budget is 4096 per native request, shared by MS and action using provider `completion_tokens`; no fixed split or action reservation. Truncated/unfinished MS still aborts without fallback.

This directly tests whether the revised request order and shorter, user-specified MS prompt reduce the long repetitive completions observed in the earlier 4096 and 8192 Base+MS runs. v6 has CPU fixture validation only; this is its first real-model evaluation.

## Submitted conditions

| Job | Model / condition | Output |
|---|---|---|
| 1060153 | Qwen3-4B-Instruct-2507, belief-MS v6 | [pipeline snapshot](calbench_diagnostic_data/20261102/qwen_base_v6_1060153/pipeline_snapshot.json) · [partial results](calbench_diagnostic_data/20261102/qwen_base_v6_1060153/games/results.json) |
| 1060154 | outcome-99 step99, belief-MS v6 | [pipeline snapshot](calbench_diagnostic_data/20261102/outcome99_v6_1060154/pipeline_snapshot.json) · [partial results](calbench_diagnostic_data/20261102/outcome99_v6_1060154/games/results.json) |

Both request one H100-47, 8 CPUs, 64 GB, 3 hours, parallel-games 8, max-num-seqs 32, context 32768, BF16, vLLM 0.28.0, utilization 0.65, eager mode, prefix caching, disabled chunked prefill/cascade attention, `VLLM_BATCH_INVARIANT=1`, and temperature 0. Qwen native job 1059395 is the already completed 4096-token baseline; it is not rerun.

Both workers passed the registered v6 source and frozen CalBench manifest checks before model requests. The per-run pipeline snapshots record resolved routes, checkpoint identity, job allocation, CLI overrides, and completion budget.


## Completed partial runs

- Qwen job 1060153: 16 case records; 15 engine-finished/scaffold-healthy, one MS failure at `blocked_uniform_s3`, Agent 2, call 11. It used all 4096 completion tokens, ended `finish_reason=length` after 97.3 seconds, and returned 16,332 visible characters. The remaining 8 cases were not started. The 613 successful MS replies averaged 219.62 tokens (median 208; range 110–499) and 972 visible characters on average (median 907; range 527–2,160).
- outcome-99 job 1060154: 8 case records; 7 engine-finished/scaffold-healthy, one MS failure at `loose_varied_s1`, Agent 2, call 9. It used all 4096 completion tokens, ended `finish_reason=length` after 98.8 seconds, and returned 15,144 visible characters. The remaining 16 cases were not started. The 288 successful MS replies averaged 218.55 tokens (median 206.5; range 119–459) and 958 visible characters on average (median 904; range 552–1,992).
- Both jobs had healthy transport. Both failures are visible MS loops, not action-stage truncations or scheduler/network errors. Their `message.reasoning` and `completion_tokens_details` fields are null; the API exposed no separately metered reasoning channel.

## outcome-99 response-length audit

Across 288 successful MS replies in its first 8 cases, completion length averaged 218.55 tokens (median 206.5; range 119–459; p90 306). Visible `message.content` averaged 958 characters (median 904; range 552–1,992). The failed `loose_varied_s1` MS call used all 4,096 completion tokens, returned 15,144 characters, and had `finish_reason=length`. A text-level repeated 8-gram occurrence diagnostic was 85.6% for that body; it ends by repeating “I will not reschedule / I will now proceed / I will schedule in slot 4.” `message.reasoning` and `completion_tokens_details` were null, so the provider exposed no separately metered reasoning channel. This is one pathological visible-text loop among the first-batch responses; it does not show that most replies are long.
