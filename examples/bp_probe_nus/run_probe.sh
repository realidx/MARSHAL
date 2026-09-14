#!/usr/bin/env bash
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python="${BP_PYTHON:-/home/e/e1300530/tmp/marshal-vllm09/bin/python}"
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Submit from the repository root:
  sbatch examples/bp_probe_nus/sbatch_probe.sh
Defaults (override through environment variables before sbatch):
  BP_PYTHON=/home/e/e1300530/tmp/marshal-vllm09/bin/python
  BP_MODEL=/home/e/e1300530/models/Qwen3-4B-Instruct-2507
  BP_PORT=18081, BP_GPU_MEMORY=0.40, BP_CONTEXT=16384
  BP_WORKERS=2 (HTTP workers on the same single-GPU service)
  BP_RUN_ROOT=<repo>/runs/bp_probe_nus
Frozen test: 32 conditions x 2 samples, plus 2 preflight requests.
No training, text-JSON answer mode, retries, or automatic package installation.
Offline bundle validation (no GPU or model needed):
  BP_PYTHON=python3 bash examples/bp_probe_nus/run_probe.sh --check
HELP
  exit 0
fi
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
exec "$probe_python" -u "$entry_dir/run_probe.py" "$@"
