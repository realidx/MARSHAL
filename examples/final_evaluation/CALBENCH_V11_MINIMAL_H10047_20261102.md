# CalBench v11-minimal scaffold evaluation on H100-47

## Scope and version

This evaluates the registered `general-belief-ms-v11-minimal` scaffold, not the native/base-prompt condition. Its full actual request preview and example are [here](../strategic_slices/versions/general_ms_calbench_v11_minimal_20261102/preview/PROMPT_PREVIEW.md) and [here](../strategic_slices/versions/general_ms_calbench_v11_minimal_20261102/EXAMPLE.md). The frozen prompt snapshot says `AWAITING_USER_REVIEW` and records 90 CPU/offline checks; the user explicitly requested these two real-model evaluations. This does not change the production default or measure D.

The run ledgers label the unchanged prompt-retry controller `calbench-prompt-retry-once-v8`; that is the retry implementation inherited by v11, not the evaluated prompt version. The finalized pipeline snapshots identify the prompt condition as v11-minimal.

The test suite is `calbench_stream_v1`, 24 frozen cases with the same IDs, scenario seeds, game configuration and original scoring used by the native baseline. Both conditions use temperature 0, a 4096-token total accepted MS-plus-action budget, context 32768 and the native model chat template.

## Jobs

| Checkpoint | Job | State at report update | Node | Output directory |
|---|---:|---|---|---|
| Qwen3-4B-Instruct-2507 base checkpoint | 1063236 | COMPLETED; 23/24 games finished | xgpi13 | `runs/calbench_soc/qwen3-4b-instruct-2507-ms-v11-minimal-r1-stream-1063236/` |
| outcome-99 step99 | 1063239 | COMPLETED; 22/24 games finished | xgpi16 | `runs/calbench_soc/outcome99-step99-ms-v11-minimal-r1-stream-1063239/` |

Each job requested `gpu:h100-47:1`, 8 CPUs, 64 GB and 3 hours. Both used an H100 NVL MIG 3g.47gb allocation. Runtime settings were vLLM 0.28.0, BF16, `max_num_seqs=32`, `parallel-games=8`, utilization 0.65, eager mode, prefix caching enabled, chunked prefill and cascade attention disabled, `VLLM_BATCH_INVARIANT=1`, OMP threads 4, OpenBLAS threads 1. Both jobs exited 0 after attempting all 24 cases, but `RUN_FINISHED.engine_finished` is false because some cases exhausted the MS retry. Healthy transport was true and there were no transport failures. Thus exit 0 means the suite runner recorded all outcomes, not that all games finished.

## Results

| Checkpoint | Finished | Final-valid meetings | Full-stream games | Semantic-invalid actions | Strict-envelope / schema errors | Physical calls | Total tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | 23/24 | 23/69 (33.3%) | 1/23 | 65 | 0 / 0 | 2,082 | 7,792,041 |
| outcome-99 step99 | 22/24 | 25/66 (37.9%) | 1/22 | 42 | 0 / 0 | 2,008 | 7,289,957 |

Meeting and full-stream denominators use only engine-finished games. The unresolved cases remain missing, not zero-filled. The same frozen native/base-prompt runs completed all 24 cases: Qwen had 37/72 final-valid meetings and 5/24 full-stream games; outcome-99 had 38/72 and 8/24. On this small evaluation, the v11 completed-case results are descriptively lower than the native baselines; the missing v11 cases and changed scaffold mean this is not a complete all-case paired comparison.

The suite took 1,125 seconds for Qwen and 1,089 seconds for outcome-99. Actual usage, including discarded failed outputs, was 7,467,078 prompt + 324,963 completion tokens for Qwen and 6,987,452 prompt + 302,505 completion tokens for outcome-99.

## Unresolved cases

| Checkpoint | Case | Failure |
|---|---|---|
| Qwen | `blocked_varied_s3` | MS ended with `finish_reason=length` at 4096 completion tokens; 15,051 visible characters. The one identical-request retry produced exactly the same MS text. No separate `message.reasoning` field was present. |
| outcome-99 | `replan_uniform_s1` | Both MS attempts stopped normally but returned JSON instead of the required natural-language belief paragraph; the retry text was exactly identical. |
| outcome-99 | `replan_varied_s1` | Same failure: two normal-stop JSON MS outputs, identical on retry, rejected by the belief-format validator. |

All three unresolved games failed in the scaffold MS stage, not in transport or native action-envelope parsing. The prompt retry policy made one retry per failed prompt and did not replay any whole game. Qwen had 1 retry / 2 failed prompt attempts; outcome-99 had 2 retries / 4 failed prompt attempts; none recovered.

## Startup attempts

The first submissions, jobs 1063222 (Qwen) and 1063224 (outcome-99), failed before model launch because the newly created batch script had a syntax error in its metadata heredoc. Both exited with code 1 before the launcher was invoked, so they made no model requests and produced no evaluation outcomes. The script was corrected, its shell and embedded Python syntax checked, the registered v11 source reverified, and the frozen 24-case suite preflight passed before submitting jobs 1063236 and 1063239. The corrected helper source is local commit `2a6504c44f10a12a72131fffa31375c8d0f4e9c7`.

## Interpretation

The full runtime and per-case `pipeline_snapshot.json` files were finalized in each run directory. The read-only canonical trace audit is reproducible with `python -m examples.final_evaluation.calbench_stream_metrics <run-directory>/games`. Training and D measurement were not run; production remains on native prompting.
