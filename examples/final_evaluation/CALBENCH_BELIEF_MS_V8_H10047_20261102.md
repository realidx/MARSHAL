# CalBench24 belief-MS v8 H100-47 submission

Final status: both jobs exited cleanly after attempting all 24 cases. Each has 20 completed game executions and 4 cases aborted after both attempts at a single MS prompt were truncated. The Slurm and batch exit codes are zero because v8 completed the suite protocol and recorded all case outcomes; this does not mean every game completed. The startup observation below is retained as the initial status.

## Reviewed version

Pulled `origin/game-slice` at commit `8f4e3055` and reviewed the registered `general-belief-ms-v8-prompt-retry-once` snapshot, full request preview, v8 execution guide, retry implementation, and offline evidence. The v8 retry change preserves the v6 MS/action prompts and shared accepted-output budget. It retries only the failed prompt once at the current game position, keeps any already accepted MS, does not append failed output, does not replay a game, and continues the remaining cases after an unrecoverable case. Failed attempts add actual compute beyond the accepted MS/action 4096-token cap and remain in the transport logs and cost records. CPU/offline validation is not model evidence; these are the first real-model runs of v8.

The local registered-source and frozen-suite preflight passed. Both jobs use the same frozen `calbench_stream_v1` 24-case suite. The source and registered snapshot identities, resolved routes, checkpoint identities, CLI, scheduler allocation, sampling, and full per-run configuration are recorded in the finalized run-root and per-game `pipeline_snapshot.json` files.

## Submitted conditions

| Job | Condition | Current output |
|---|---|---|
| 1060433 | Qwen3-4B-Instruct-2507, belief-MS v8 | [pipeline snapshot](calbench_diagnostic_data/20261102/qwen_base_v8_1060433/pipeline_snapshot.json) · [case ledger](calbench_diagnostic_data/20261102/qwen_base_v8_1060433/games/case_results.json) |
| 1060434 | outcome-99 step99, belief-MS v8 | [pipeline snapshot](calbench_diagnostic_data/20261102/outcome99_v8_1060434/pipeline_snapshot.json) · [case ledger](calbench_diagnostic_data/20261102/outcome99_v8_1060434/games/case_results.json) |

Both request one H100-47, 8 CPUs, 64 GB, 3 hours, `parallel-games=8`, `max_num_seqs=32`, context 32768, BF16, vLLM 0.28.0, utilization 0.65, eager mode, prefix caching, disabled chunked prefill/cascade attention, `VLLM_BATCH_INVARIANT=1`, and temperature 0. Each has an independent output directory.

The completed Qwen native/base-prompt job 1059395 remains the existing comparator; it is not repeated in this batch. The registered v8 policy also applies prompt retry to native stream24 comparisons, so this batch should not be described as having rerun that comparator.

No training, reward/advantage change, or D measurement was performed. Production remains unchanged. Prior v2/v3/v6 execution records and reports remain preserved under their original identities.


## Final results

| Model | Case executions | Engine/scaffold complete | Unresolved cases | MS prompt retries | Recovered retries |
|---|---:|---:|---|---:|---:|
| Qwen3-4B-Instruct-2507 | 24/24 attempted | 20/24 | `blocked_uniform_s3`, `replan_uniform_s1`, `replan_uniform_s3`, `replan_varied_s1` | 4 | 0 |
| outcome-99 step99 | 24/24 attempted | 20/24 | `loose_varied_s1`, `blocked_uniform_s1`, `blocked_varied_s3`, `replan_varied_s1` | 4 | 0 |

All eight failed physical attempts were MS calls, not action calls or transport failures. Each first attempt and same-prompt retry used all 4096 completion tokens and returned `finish_reason=length`. For every failed prompt the retry's visible body was byte-identical to the first attempt. `message.reasoning` and `completion_tokens_details` were null; the logs expose no separate hidden reasoning stream or separately metered reasoning tokens. A lowercased word/punctuation repeated-8-gram diagnostic ranged from 78.6% to 90.0% for Qwen and 84.0% to 89.0% for outcome-99. This is a text-recurrence heuristic, not a token-share estimate. The retries therefore did not break these loops; they did let the suite continue and attempt all 24 cases.

Among accepted MS outputs (including successful MS stages earlier in the four aborted cases), Qwen has 842 outputs averaging 220.02 completion tokens and 974.8 visible characters (medians 207 tokens and 913 characters). outcome-99 has 785 averaging 218.00 tokens and 958.7 characters (medians 203 tokens and 900 characters). These are MS-stage lengths, not total action-answer lengths.

For the 20 completed cases only, Qwen retained 16 of 60 requested meetings in final calendars (26.7%) and completed all three meetings in 1/20 cases; outcome-99 retained 17/60 (28.3%) and completed all three in 0/20. Both had 17 native-round meeting resolutions among those 20 cases. Qwen recorded 31 semantic-invalid actions and no strict-envelope failures; outcome-99 recorded 41 semantic-invalid actions, one strict-envelope failure, and no native schema rejection. These partial results are not 24-case scores: the four aborted cases per model remain missing, not zero-filled. The earlier Qwen native 24-case baseline (37/72 final-valid meetings, 5/24 full-stream completions) has a different denominator here and must not be treated as a paired 24-case comparison.

All recorded physical costs include discarded failed outputs. Qwen logged 1,692 physical calls, 298,322 completion tokens and 7,282,757 total tokens in 21:24 wall time; outcome-99 logged 1,578 physical calls, 276,956 completion tokens and 6,686,423 total tokens in 19:21. There were no transport failures and no missing usage fields. Run-root and per-game `pipeline_snapshot.json` files are finalized; the model/data/source identity and runtime configuration remain linked above.
