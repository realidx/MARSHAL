# CalBench base-prompt and v8 comparison

This report collects the requested two conditions for each checkpoint: native/base prompt and the latest registered belief-MS v8 run. It replaces the earlier push that grouped v6 and v8 MS runs.

## Results

| Checkpoint | Condition | Job | Cases completed | Final-valid meetings | Full-stream cases |
|---|---|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | Native/base prompt | 1059395 | 24/24 | 37/72 (51.4%) | 5/24 |
| Qwen3-4B-Instruct-2507 | Belief-MS v8 | 1060433 | 20/24 | 16/60 (26.7%) | 1/20 |
| outcome-99 step99 | Native/base prompt | 872963 | 24/24 | 38/72 (52.8%) | 8/24 |
| outcome-99 step99 | Belief-MS v8 | 1060434 | 20/24 | 17/60 (28.3%) | 0/20 |

The base-prompt conditions completed all 24 cases. Each v8 condition attempted all 24 and completed 20; the four aborted outcomes per model remain missing. The v8 percentages use only completed cases and must not be presented as full 24-case scores. All four saved manifests have equal case IDs, scenario seeds, and game configuration; base-prompt and v8 routes use the same 4096 output cap and temperature 0. The Qwen base-prompt and Qwen v8 conditions ran with the same H100-47 profile. O99 base-prompt job 872963 is an earlier archived run with a 45-minute scheduler limit; its recorded H100-47 inference profile matches the later comparison profile, but its archive did not retain a submission JSON or full pipeline snapshot.

## Diagnostic details

The two native runs record `prompt_changed=false` and no chat-template change. The two v8 runs use the same registered independent MS→action prompt protocol. Each v8 model had four MS truncation cases. The failed prompt and its one retry each consumed 4096 completion tokens and returned `finish_reason=length`; all four retries per model reproduced the first response byte-for-byte. There were no transport failures. The response logs expose no separate `message.reasoning` or `completion_tokens_details` values for these calls, so the evidence is visible MS text looping, not separately observed hidden reasoning.

Among accepted MS outputs, Qwen produced 842 responses averaging 220.02 tokens and 974.8 visible characters. outcome-99 produced 785 averaging 218 tokens and 958.7 characters. Four failed cases per model are excluded from the meeting-rate denominators above.

## Raw data

The [diagnostic bundle README](calbench_diagnostic_data/20261102/README.md) links the four complete raw run folders. They include full transport request/response JSONL, model and runtime metadata, scenario/reference files, events, traces, results, and the available pipeline snapshots. The archived O99 native run lacks a pipeline snapshot; its original available metadata and Slurm log are included without fabricating missing fields.

The registered v8 method, exact request previews, and offline evidence are in [the v8 snapshot](../strategic_slices/versions/general_ms_calbench_v8_20261102/SNAPSHOT.json). No training, reward change, or D measurement was performed.
