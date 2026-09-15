#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
: "${CUDA_VISIBLE_DEVICES:?Explicitly set CUDA_VISIBLE_DEVICES to GPUs allocated for your shared run}"
export CUDA_VISIBLE_DEVICES
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
# Read-only admission check immediately before launch. No automatic GPU selection.
nproc="$(python -m training.b_sft.preflight --min-free-mib "${B_SFT_MIN_FREE_MIB:-0}")"
exec torchrun --standalone --nnodes=1 --nproc-per-node="$nproc" \
  --module training.b_sft.train "$@"
