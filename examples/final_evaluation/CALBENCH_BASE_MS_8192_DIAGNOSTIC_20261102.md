# CalBench24 Base+MS 8192-token diagnostic

Status: both jobs stopped after the first 8-case batch because the registered MS stage still hit the 8192-token ceiling. Both had healthy transport and passed worker source/version preflight. The remaining 16 cases in each condition were not started.

## Registered change

Version: [general-ms-conditioning-v3-shared-budget-8192](../strategic_slices/versions/general_ms_calbench_v3_8192_20261102/SNAPSHOT.json), with exact archived implementation source and evidence beside it. The only protocol change from v2 is the explicit total output cap: 4096 → 8192. The MS can use up to 8192; the action cap is 8192 minus actual provider `completion_tokens`. There is still no fixed split, action reservation, or truncation fallback. Prompt text, request construction, frozen CalBench24 cases, rules, scoring, temperature, context, and serving settings are unchanged.

## Results

| Job | Model | First 8 cases | MS truncations at 8192 | Elapsed | Full 24? |
|---|---|---:|---:|---:|---|
| 1059574 | Qwen3-4B-Instruct-2507 | 7 scaffold-healthy / 1 failed | 1 | 7:42 | No |
| 1059575 | outcome-99 step99 | 4 scaffold-healthy / 4 failed | 4 | 7:32 | No |

All five failed MS calls exhausted exactly 8192 provider `completion_tokens` and ended with `finish_reason=length`. Their transport was healthy. Qwen failed at `loose_uniform_s1`, Agent 0, MS call 2 (211.2 s). Outcome-99 failed at `loose_varied_s1` Agent 1 call 1 (203.6 s), `loose_varied_s2` Agent 1 call 1 (204.0 s), `loose_uniform_s1` Agent 1 call 5 (206.3 s), and `dense_uniform_s1` Agent 1 call 6 (206.7 s). The scaffold correctly stopped without executing an action for each incomplete analysis; after each first 8-case batch, the remaining 16 cases were not run.

This means doubling the cap did not remove the failure mode for either model. It allowed the failing analyses to run for about 204–211 seconds before exhausting the larger cap. The failure is not a GPU, scheduler, or transport error.

## What the truncated responses contain

The raw vLLM records show `finish_reason=length` and `completion_tokens=8192` for all five failed calls. Each returned 30,578–35,534 characters in ordinary assistant `content`. The response has `message.reasoning=null`, `completion_tokens_details=null`, no `<think>` tags, no tool calls, and `output_normalization=plain`. Thus the logs show no separately emitted or separately counted reasoning channel. They cannot measure any internal computation that the API does not expose, but the observable token budget is accompanied by a very long visible MS text.

The text is highly repetitive. The column below is a simple textual recurrence diagnostic: among lowercased word/punctuation 8-gram windows, the share of window occurrences beyond the unique 8-grams. It is **not** a model-token usage percentage.

| Model / case | Visible content | Repeated 8-gram occurrences | Observed pattern |
|---|---:|---:|---|
| Qwen `loose_uniform_s1`, Agent 0 call 2 | 35,534 chars | 83.8% | 33 occurrences of “Final action” and 69 of “Action: send”; ends `I will not send` |
| outcome-99 `loose_varied_s1`, Agent 1 call 1 | 31,245 chars | 77.5% | Repeatedly revisits confirming/sending a message; 32 “Final internal analysis” phrases |
| outcome-99 `loose_varied_s2`, Agent 1 call 1 | 33,359 chars | 75.6% | Repeatedly restates the same slot analysis; ends mid-sentence |
| outcome-99 `loose_uniform_s1`, Agent 1 call 5 | 31,260 chars | 68.3% | Cycles through send/end-talk/final-action statements; ends at `Therefore,` |
| outcome-99 `dense_uniform_s1`, Agent 1 call 6 | 30,578 chars | 86.9% | “I will now send” appears 429 times and “But I already did” 216 times; ends at `But I` |

The API role stayed `assistant`; there was no tool call or action JSON envelope. However, several MS bodies drift into narrating operational actions (“Action: send…”, “Final action…”) despite the stage instruction to return a short private analysis and not execute or communicate an action. These are text inside the failed MS response, not actions sent to the environment. All five stop at the generation ceiling rather than with a normal stop reason, and the endings are visibly incomplete. This points to runaway/repeated analysis text, not a hidden reasoning-token allocation or a transport interruption.

## Artifacts and comparison boundary

- Qwen run: [pipeline snapshot](../../runs/calbench_soc/qwen3-4b-instruct-2507-base-ms-v3-8192-stream-1059574/pipeline_snapshot.json), [partial results](../../runs/calbench_soc/qwen3-4b-instruct-2507-base-ms-v3-8192-stream-1059574/games/results.json), [failure summary](../../runs/calbench_soc/qwen3-4b-instruct-2507-base-ms-v3-8192-stream-1059574/LAUNCH_FAILED.json).
- outcome-99 run: [pipeline snapshot](../../runs/calbench_soc/outcome99-step99-base-ms-v3-8192-stream-1059575/pipeline_snapshot.json), [partial results](../../runs/calbench_soc/outcome99-step99-base-ms-v3-8192-stream-1059575/games/results.json), [failure summary](../../runs/calbench_soc/outcome99-step99-base-ms-v3-8192-stream-1059575/LAUNCH_FAILED.json).

The completed Qwen native/base-prompt baseline used 4096 tokens. These 8192-token Base+MS runs are diagnostic and do not provide a generation-budget-matched scaffold comparison. Missing cases are not zeros. Production active remains v8; no training or D measurement was performed.
