#!/usr/bin/env bash
set -euo pipefail
native800_repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$native800_repo"
native800_python="${SLICES_D_PYTHON:-python}"
export PYTHONPATH="$native800_repo:$native800_repo/third_party/negotiation_benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec "$native800_python" -u -m examples.strategic_slices.run_native800_d_v1_1 "$@"
