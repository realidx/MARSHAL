# NUS single-GPU outcome rollout smoke test

This is an inference-only entrypoint. It starts one local vLLM server, runs
three complete-game attempts (two 2-player games and one 3-player game), saves
requests and native replay checks, then stops its own server. No training runs.
Existing rollout interfaces are unchanged.

## Run on NUS

Log in through the jump host, update this Git branch, and submit from the repo root:

```bash
ssh -J e1300530@stujump.comp.nus.edu.sg e1300530@xlogin.comp.nus.edu.sg
cd /home/e/e1300530/MARSHAL
git fetch origin
git switch --track origin/codex/outcome-rollout-nus-1gpu
git pull --ff-only
sbatch examples/outcome_selfplay_nus/sbatch_smoke.sh
```

If the local branch already exists, use `git switch codex/outcome-rollout-nus-1gpu`.
Do not discard local changes to switch branches.

The Slurm resource selection and environment paths reuse the recorded NUS
`examples/item_game/sbatch_probe_vllm_native_reason.sh` setup:

- One `gpu:h100-47:1` allocation; scheduler GPU visibility is preserved.
- Python: `/home/e/e1300530/tmp/marshal-vllm09/bin/python`.
- Model: `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`.
- Hermes tool parser, context 8192, response limit 2048, request timeout 180 s.
- One game at a time, one rollout per reset, vLLM memory utilization 0.40.

These are historical paths, checked for existence when the job starts. Override
them if needed through `OUTCOME_PYTHON` and `OUTCOME_MODEL` before `sbatch`.
`bash examples/outcome_selfplay_nus/run_smoke.sh --help` lists other overrides.
The launcher rejects more than one visible GPU and binds only localhost. It
does not install packages, modify the environment, or stop existing services.

## Outputs and interpretation

Slurm stdout is `slurm-outcome-rollout-smoke-<jobid>.out`. The launcher prints
`OUTCOME_RUN_DIR`, a unique directory under `runs/outcome_selfplay_nus/` containing:

- `server_manifest.json`, `models.json`: environment and model-service identity.
- `server.log`, `client.log`: inference and rollout logs.
- `rollout/summary.json`, plus detailed episode and request records.
- The verified runtime source used by that run.

A completed shell command alone does not establish success: inspect the summary
for terminal games, request failures, invalid calls, retries, and replay checks.
Incomplete games have no terminal outcome reward. The frozen v2 runtime allows
one retry for invalid tool output or truncation, charging -0.1 per such failure;
transport timeouts are recorded separately without that penalty. Player terminal
outcome and format penalty remain separately recorded. HTTP rollouts are for
integration testing, not token/logprob-ready training batches.

## Frozen dependency reuse

`runtime_v2.tar.gz` is an unchanged copy of the existing
`runs/outcome_selfplay_screen/outcome_rollout_runtime_v2.tar.gz`, built by
`runs/outcome_selfplay_screen/package_rollout.py`. The original lives under
Git-ignored `runs/`; this tracked snapshot makes a remote Git checkout sufficient
and avoids missing local `training.b_sft` imports. Its dependency closure includes
teacher modules for shared environment definitions, but rollout does not invoke
teacher solving or B/P gold supervision. It contains source and curriculum, not
model weights or experimental result directories.

`unpack_runtime.py` verifies both the archive checksum and the internal per-file
manifest before launching inference. Each run unpacks into a fresh directory,
isolating it from concurrent teacher changes in the checkout. Updating this
snapshot later must be an explicit versioned change, not an automatic rebuild
from a potentially changing working tree.
