#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH="$PWD"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-6,7}"
PY=/raid/chenjiahao/conda_envs/mas/bin/python
MODEL=/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507
RUN_BASE=/raid/chenjiahao/mas/runs/distribution_probe_v1
mkdir -p "$RUN_BASE"
JOB="$RUN_BASE/$(date +%Y%m%d-%H%M%S)"
mkdir "$JOB"
printf '%s\n' "$JOB" > "$RUN_BASE/latest.txt"
"$PY" -c 'from training.social_mixed.run import verify_bundle; verify_bundle()'
"$PY" -m training.social_mixed.distribution_probe --check
nvidia-smi --id="$CUDA_VISIBLE_DEVICES" --query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total,power.draw --format=csv -l 5 > "$JOB/gpu.csv" &
MONITOR=$!
trap 'kill "$MONITOR" 2>/dev/null || true' EXIT
printf 'OUTPUT=%s\n' "$JOB"
set +e
"$PY" -u examples/social_mixed/a100_evaluate.py --distribution-probe \
 --candidate "$MODEL" --base "$MODEL" --output "$JOB/run" 2>&1 | tee "$JOB/console.log"
STATUS=${PIPESTATUS[0]}
set -e
printf '%s\n' "$STATUS" > "$JOB/exit_code.txt"
exit "$STATUS"
