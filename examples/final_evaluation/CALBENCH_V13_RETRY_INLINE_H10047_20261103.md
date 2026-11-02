# CalBench v13 retry and inline-MS evaluation on H100-47

## Scope and registered prompt

The code was fast-forward pulled from `origin/game-slice` to commit `709bea92f9fc329360ebf4549edb2146936c25ff`. The registered prompt version is `general-ms-v13-retry-inline`; its immutable snapshot remains marked `AWAITING_USER_REVIEW`, and the user explicitly authorized these evaluations.

The four conditions use the same frozen `calbench_stream_v1` set of 24 case IDs, scenario seeds, game configuration, native rules, and final-state scoring:

- `belief-ms`: separate belief and action calls. The v13 retry contract removes belief-content and format validation while retaining empty-output, finish-state, and budget checks. A failed prompt is retried once in place. Accepted belief and action outputs share a 4096-token budget.
- `inline-ms`: one native request per action. The native system, history, and user message remain intact; the registered mental-state instruction is appended to the final native user message. The response puts the belief and brief reasoning in JSON `thinking`, and the action in `actions`.

The complete request examples are in the [belief-MS preview](../strategic_slices/versions/general_ms_calbench_v13_retry_inline_20261103/preview/PROMPT_PREVIEW.md) and [inline-MS preview](../strategic_slices/versions/general_ms_calbench_v13_retry_inline_20261103/inline-preview/PROMPT_PREVIEW.md). The [registered snapshot](../strategic_slices/versions/general_ms_calbench_v13_retry_inline_20261103/SNAPSHOT.json) and [offline evidence](../strategic_slices/versions/general_ms_calbench_v13_retry_inline_20261103/EVIDENCE.json) define the implementation; offline checks are not model-effect evidence.

## Jobs and results

Every job attempted all 24 cases and exited successfully. Transport was healthy in all 24 cases for every job. Failed games are unresolved and their final-state utilities remain missing, not zero-filled. Meeting and semantic-invalid counts below include only engine-finished cases; token and physical-call totals include failed attempts.

| Model | Mode | Job / node | Observed GPU | Engine-finished | Final-valid meetings | Full-stream cases | Semantic-invalid actions | Strict envelope / schema | Calls | Prompt + completion tokens | Retries / exhausted / failed attempts | Suite time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | belief-MS | [1065394 / xgpi14](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/) | H100 NVL MIG 3g.47gb | 23/24 | 21/69 | 2/23 | 29 | 1 / 0 | 2,164 | 7,879,792 + 334,627 = 8,214,419 | 1 / 1 / 2 | 1,256.8 s |
| outcome-99 step99 | belief-MS | [1065395 / xgpi15](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/) | H100 NVL, full device observed | 23/24 | 28/69 | 4/23 | 32 | 1 / 0 | 2,069 | 7,356,335 + 312,961 = 7,669,296 | 1 / 1 / 2 | 974.9 s |
| Qwen3-4B-Instruct-2507 | inline-MS | [1065396 / xgpi14](../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/) | H100 NVL MIG 3g.47gb | 19/24 | 35/57 | 5/19 | 33 | 0 / 0 | 958 | 4,768,997 + 296,835 = 5,065,832 | 5 / 5 / 10 | 1,355.3 s |
| outcome-99 step99 | inline-MS | [1065397 / xgpi13](../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/) | H100 NVL MIG 3g.47gb | 20/24 | 34/60 | 5/20 | 39 | 0 / 0 | 944 | 4,570,629 + 277,648 = 4,848,277 | 4 / 4 / 8 | 1,305.3 s |

“Full stream” means every requested meeting is valid in the final state and blocked items remain intact. The two belief-MS runs each had one strict-envelope failure and no native-schema rejection; inline-MS had neither. Semantic-invalid action counts are distinct from envelope and schema errors.

## Unresolved cases

| Model and mode | Unresolved case(s) | Recorded failure |
|---|---|---|
| Qwen belief-MS | `replan_varied_s2` | Agent 2 belief output hit the 4096-token cap in both identical attempts; the repeated reasoning did not finish. |
| outcome-99 belief-MS | `replan_varied_s3` | Agent 1 action output hit its remaining 3959-token cap in both attempts after an accepted 137-token belief output. |
| Qwen inline-MS | `dense_varied_s3`, `blocked_uniform_s3`, `replan_uniform_s2`, `replan_uniform_s3`, `replan_varied_s1` | All five exhausted retries at the 4096-token cap; the repeated outputs were identical and did not finish. |
| outcome-99 inline-MS | `dense_uniform_s2`, `dense_varied_s2`, `dense_varied_s3`, `replan_uniform_s2` | All four exhausted retries at the 4096-token cap; the repeated outputs were identical and did not finish. |

The physical call-status ledgers contain 2, 2, 10, and 8 truncated calls respectively. These are generation cutoffs, not transport failures. Inline-MS had no recovered prompt failures in either model.

## Paired comparison and interpretation

Among case IDs that finished in both modes, Qwen has 18 paired cases and outcome-99 has 19:

| Model | Paired finished cases | belief-MS → inline-MS final-valid meetings | Full-stream cases | Semantic-invalid actions |
|---|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | 18 | 16/54 → 33/54 | 1/18 → 5/18 | 25 → 33 |
| outcome-99 step99 | 19 | 20/57 → 33/57 | 3/19 → 5/19 | 23 → 37 |

Inline-MS used 38.3% fewer total tokens and 55.7% fewer physical calls for Qwen; it used 36.8% fewer tokens and 54.4% fewer calls for outcome-99. However, it finished fewer total games (Qwen 19 versus 23; outcome-99 20 versus 23), accumulated more semantic-invalid actions, and had substantially more exhausted truncation retries. Its end-to-end suite time was not shorter in either model.

Thus inline-MS improved meeting completion and full-stream counts on the common finished cases in this small run, while reducing coverage and increasing action errors and unfinished games. This is descriptive evidence, not a broad performance claim. The outcome-99 belief-MS job was allocated to the full H100 NVL device despite requesting `gpu:h100-47:1`; the other three jobs logged the 47-GB MIG device. Keep that hardware difference in view when comparing outcome-99 modes.

## Runtime, startup attempts, and retained artifacts

The four successful jobs requested partition `gpu`, GRES `gpu:h100-47:1`, 3-hour walltime, 8 CPUs, 64 GB host memory, BF16, context 32768, `max_num_seqs=32`, 8 parallel games, GPU utilization 0.65, eager mode, prefix caching, no chunked prefill or cascade attention, `VLLM_BATCH_INVARIANT=1`, temperature 0, and max output 4096. Each retained root `pipeline_snapshot.json` preserves the resolved CLI/configuration, prompt identity, source commit, model identity, inputs, and scheduler allocation.

The first four submissions (jobs 1065390–1065393) failed in the submission metadata heredoc with `NameError: subprocess_head is not defined`. They stopped before the launcher and made no model requests. The helper was corrected, verified, and the four successful jobs above were resubmitted. Those startup-failure artifacts are separate from these four completed run directories and are excluded from all metrics.

At the user's request, each successful experiment root now retains only `pipeline_snapshot.json` and `execution_identity.json`. Each of its 24 case directories retains `scenario.json`, `result.json`, `events.jsonl`, and all `transport-agent-*.jsonl` files. Belief-MS cases also retain `ms/transport-agent-*.jsonl`; inline-MS cases do not retain an `ms/` directory. Duplicate summary ledgers, per-case snapshots/manifests/traces, submission/runtime metadata, and copied server/Slurm logs were removed from these four roots.

Every one of the 6,135 physical model-call attempts has a unique `call_id` in its transport record and a matching ID in the related environment event's `call_ids`/`model_calls`. Full outgoing JSON request bodies are preserved unchanged in each transport record's `request` field; these are the bodies passed to `json.dumps(body).encode()` by the sender, not prompt previews. The request URL, method, and content type are stored alongside it. Authorization values are redacted. The post-hoc `call_id` was not inserted into the historical request body because it was not sent during the run.

Environment `turn_end`/`decide_end` links use an exact match between transport `response.id` and `raw_api_response.id`. Independent-MS calls and native validation retries are associated by the per-agent call index, scaffold `native_call_index`, ordered environment start events, and `batch_rejected` retry events. Each physical prompt retry has its own ID, while all retries point to the same environment decision context. The one Qwen belief-MS call with no action-stage request is preserved as an explicit failed MS context in `result.json`.

The table's observed GPU identity was transcribed from the copied server/Slurm logs before cleanup and is recorded in each `execution_identity.json`. Those raw copied logs were removed under the requested retention policy, so their original stdout is not included for independent reinspection. The outcome-99 belief-MS allocation differs from the requested 47-GB GRES as noted above.

- Qwen belief-MS: [root snapshot](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/pipeline_snapshot.json) · [execution identity](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/execution_identity.json) · [sample case events](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/games/blocked_uniform_s1/events.jsonl) · [full action request records](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/games/blocked_uniform_s1/transport-agent-0.jsonl) · [full MS request records](../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/games/blocked_uniform_s1/ms/transport-agent-0.jsonl)
- outcome-99 belief-MS: [root snapshot](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/pipeline_snapshot.json) · [execution identity](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/execution_identity.json) · [sample case events](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/blocked_uniform_s1/events.jsonl) · [full action request records](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/blocked_uniform_s1/transport-agent-0.jsonl) · [full MS request records](../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/blocked_uniform_s1/ms/transport-agent-0.jsonl)
- Qwen inline-MS: [root snapshot](../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/pipeline_snapshot.json) · [execution identity](../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/execution_identity.json) · [sample case events](../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/games/blocked_uniform_s1/events.jsonl) · [full native request records](../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/games/blocked_uniform_s1/transport-agent-0.jsonl)
- outcome-99 inline-MS: [root snapshot](../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/pipeline_snapshot.json) · [execution identity](../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/execution_identity.json) · [sample case events](../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/games/blocked_uniform_s1/events.jsonl) · [full native request records](../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/games/blocked_uniform_s1/transport-agent-0.jsonl)

No D measurement or training was run. Production remains on `terminal-node-regret-grpo-readable-v8`; these CalBench results do not activate v13 or change the production prompt.
