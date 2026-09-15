#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export CUDA_VISIBLE_DEVICES="${BP_GPUS:-6,7}"
export ROLL_ASSIGNED_CUDA_DEVICES="$CUDA_VISIBLE_DEVICES"
export RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1
export VLLM_USE_V1=0
export VLLM_ATTENTION_BACKEND=XFORMERS
export TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=2
export TOKENIZERS_PARALLELISM=false
export BP_RAY_TMP_ROOT="${BP_RAY_TMP_ROOT:-/raid/chenjiahao/ray}"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_DEVICE_MAX_CONNECTIONS=1
export BP_MODEL="${BP_MODEL:-/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507}"
BP_PYTHON="${BP_PYTHON:-/raid/chenjiahao/conda_envs/mas/bin/python}"
BP_OUTPUT="${1:-$PWD/runs/bp_deepspeed_two_a100_train/$(date +%Y%m%d-%H%M%S)}"
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export LD_LIBRARY_PATH="/raid/chenjiahao/conda_envs/mas/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/raid/chenjiahao/conda_envs/mas/bin:$PATH"
export NCCL_LIBRARY="$PWD/new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2"
if [[ ! -f "$NCCL_LIBRARY" ]]; then
  echo "Missing NCCL binary from the completed B run: $NCCL_LIBRARY" >&2
  exit 1
fi
"$BP_PYTHON" -c 'import os; from training.b_sft.prepare_b_grpo_nccl import verify_library; print(verify_library(os.environ["NCCL_LIBRARY"]))'
export LD_PRELOAD="$NCCL_LIBRARY${LD_PRELOAD:+:$LD_PRELOAD}"
export NCCL_CUMEM_ENABLE=0 NCCL_NVLS_ENABLE=0
export ROLL_LOCAL_COMM_ADDR=127.0.0.1 GLOO_SOCKET_IFNAME=lo NCCL_SOCKET_IFNAME=lo
test -x "$TRITON_PTXAS_PATH"
"$BP_PYTHON" -m training.b_sft.build_bp_training_bundle --verify .
exec "$BP_PYTHON" -u -m training.b_sft.bp_two_gpu_train --output "$BP_OUTPUT" --model "$BP_MODEL"
