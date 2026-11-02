# CalBench v11-minimal scaffold evaluation on H100-47

## Scope and version

This evaluates the registered `general-belief-ms-v11-minimal` scaffold, not the native/base-prompt condition. Its full actual request preview and example are [here](../strategic_slices/versions/general_ms_calbench_v11_minimal_20261102/preview/PROMPT_PREVIEW.md) and [here](../strategic_slices/versions/general_ms_calbench_v11_minimal_20261102/EXAMPLE.md). The frozen prompt snapshot says `AWAITING_USER_REVIEW` and records 90 CPU/offline checks; the user explicitly requested these two real-model evaluations. This does not change the production default or measure D.

The test suite is `calbench_stream_v1`, 24 frozen cases with the same IDs, scenario seeds, game configuration and original scoring used by the native baseline. Both conditions use temperature 0, a 4096-token total accepted MS-plus-action budget, context 32768 and the native model chat template.

## Jobs

| Checkpoint | Job | State at report update | Node | Output directory |
|---|---:|---|---|---|
| Qwen3-4B-Instruct-2507 base checkpoint | 1063236 | RUNNING; inference active | xgpi13 | `runs/calbench_soc/qwen3-4b-instruct-2507-ms-v11-minimal-r1-stream-1063236/` |
| outcome-99 step99 | 1063239 | RUNNING; inference active | xgpi16 | `runs/calbench_soc/outcome99-step99-ms-v11-minimal-r1-stream-1063239/` |

Each job requests `gpu:h100-47:1`, 8 CPUs, 64 GB and 3 hours. The observed device is an H100 NVL MIG 3g.47gb allocation. Runtime settings are vLLM 0.28.0, BF16, `max_num_seqs=32`, `parallel-games=8`, utilization 0.65, eager mode, prefix caching enabled, chunked prefill and cascade attention disabled, `VLLM_BATCH_INVARIANT=1`, OMP threads 4, OpenBLAS threads 1. Model identity, routes and runtime environment are recorded in each run directory. At the latest progress check, both model servers reported eight concurrent requests with no waiting requests; each run had eight in-progress case directories and 0/24 completed game rows. These are live counts, not final results.

## Startup attempts

The first submissions, jobs 1063222 (Qwen) and 1063224 (outcome-99), failed before model launch because the newly created batch script had a syntax error in its metadata heredoc. Both exited with code 1 before the launcher was invoked, so they made no model requests and produced no evaluation outcomes. The script was corrected, its shell and embedded Python syntax checked, the registered v11 source reverified, and the frozen 24-case suite preflight passed before submitting jobs 1063236 and 1063239. The corrected helper source is local commit `2a6504c44f10a12a72131fffa31375c8d0f4e9c7`.

## Interpretation

This is an in-progress evaluation; there are no outcome metrics to report yet. Failed v11 prompts will be retried once in place, with no whole-game replay; failed generations count toward actual cost, while missing case outcomes remain missing. The full runtime and per-case `pipeline_snapshot.json` files will be finalized in each run directory when each job exits. Training and D measurement were not run.
