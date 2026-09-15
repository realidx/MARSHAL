#!/usr/bin/env bash
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python="${PROBE_PYTHON:-/raid/chenjiahao/conda_envs/mas/bin/python}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"
export VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND:-XFORMERS}"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/home/chenjiahao/cuda-11.8/bin/ptxas}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
exec "$probe_python" -u "$entry_dir/run_remote.py" "$@"
