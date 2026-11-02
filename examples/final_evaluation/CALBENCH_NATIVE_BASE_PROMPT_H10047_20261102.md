# CalBench native/base-prompt results

These are retained historical runs, not new evaluations.

| Checkpoint | Job | Completed cases | Final-valid meetings | Full-stream cases |
|---|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | 1059395 | 24/24 | 37/72 (51.4%) | 5/24 |
| outcome-99 step99 | 872963 | 24/24 | 38/72 (52.8%) | 8/24 |

Both conditions use the native/base prompt, the same frozen CalBench stream24 cases and game configuration, max_tokens4096 and temperature0. The original requests record no chat-template override. Input, model and runtime identities remain in their original run files. The outcome-99 run is an earlier H100-47 archive with a45-minute scheduler limit and lacks pipeline_snapshot.json/job_submission.json; missing metadata was not reconstructed from later defaults.

[Raw run bundle](calbench_diagnostic_data/20261102/README.md). Old MS run records are excluded as requested. No new model evaluation, training, reward change or D measurement was performed.
