#!/usr/bin/env bash
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python="${BP_PYTHON:-/home/e/e1300530/tmp/marshal-vllm09/bin/python}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
export BP_WORKERS="${BP_WORKERS:-4}"
exec "$probe_python" -u "$entry_dir/run_probe.py" "$@"
