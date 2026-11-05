# native800-terminal-D-v1.1

## Parent and scope

Parent: native800-terminal-D-v1. This revision fixes the transfer package's omitted runtime dependency after job 1077848 failed before evaluation. The D method, visible prompt, tool schema, scorer, dataset, model sampling, scheduler, and resource request do not change.

## Change

The v1 launcher imported examples.strategic_slices.run_terminal_d for model_identity, server_command, and stop_server, but the v1 package did not include or pin that module. v1.1 adds its exact source hash and packages it. Versioned runner and launcher copies point at this v1.1 registration snapshot so the attempted run identity records the dependency.

## Failure evidence

Job 1077848 on xgpi18 ran for 8 seconds and exited 1 with ModuleNotFoundError for examples.strategic_slices.run_terminal_d. The failure happened during module import, before dataset loading, model identity hashing, vLLM startup, or any model call. No D values or run output were produced. Original v1 bundle and job logs remain unchanged.

## Validation boundary

No CPU tests, mock, GPU smoke test, or model test is run for package preparation. Static file/hash checks only. The authorized H100 job is the first actual v1.1 execution; its result will distinguish startup failure, infrastructure failure, invalid model output, and completed D.
