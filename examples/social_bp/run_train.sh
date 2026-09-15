#!/usr/bin/env bash
set -euo pipefail
bp_python="${BP_TRAIN_PYTHON:-$HOME/tmp/marshal-bp-grpo/bin/python}"
export BP_MODEL="${BP_MODEL:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
export BP_RUN_DIR="${BP_RUN_DIR:-$PWD/runs/bp_grpo_pilot/${SLURM_JOB_ID:-local}}"
export BP_EXPORT_DIR="${BP_EXPORT_DIR:-$BP_RUN_DIR/export}"
export ROLL_OUTPUT_DIR="$BP_RUN_DIR" ROLL_LOG_DIR="$BP_RUN_DIR/logs"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
export RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1 RAY_USAGE_STATS_ENABLED=0
export NCCL_CUMEM_ENABLE=0 NCCL_NVLS_ENABLE=0
export ROLL_ASSIGNED_CUDA_DEVICES="${CUDA_VISIBLE_DEVICES:?Run inside a six-GPU Slurm allocation}"
export MASTER_ADDR=127.0.0.1
export MASTER_PORT="${BP_RAY_PORT:-$((26000 + ${SLURM_JOB_ID:-0} % 10000))}"
export RAY_NUM_GPUS_PER_NODE=6 MULTI_TENANT=1
export RAY_ADDRESS="$MASTER_ADDR:$MASTER_PORT"
export PATH="$(dirname -- "$bp_python"):$PATH"
if [[ -e "$BP_RUN_DIR" ]]; then echo "Preserve existing run $BP_RUN_DIR; choose a fresh BP_RUN_DIR." >&2; exit 1; fi
"$bp_python" -m training.b_sft.check_bp_training_env
"$bp_python" - <<'PY'
import os,socket,torch
if torch.cuda.device_count()!=6: raise SystemExit('Pilot mapping requires exactly six allocated GPUs: four train, one rollout, one reference.')
with socket.socket() as s: s.bind((os.environ['MASTER_ADDR'],int(os.environ['MASTER_PORT'])))
for i in range(6):
    if torch.cuda.get_device_properties(i).total_memory < 40*1024**3: raise SystemExit('This config requires >=40 GiB per allocated GPU.')
PY
mkdir -p "$BP_RUN_DIR"
"$bp_python" -m training.b_sft.social_bp_grpo --data examples/social_bp/data --out "$BP_EXPORT_DIR" --model "$BP_MODEL"
"$bp_python" -m training.b_sft.bp_training_preflight
# Slurm releases the allocation. Do not run a global ray stop or kill another
# user task. The driver selects the job-specific head port checked above.
"$bp_python" -u examples/start_rlvr_pipeline.py --config_path social_bp --config_name grpo 2>&1 | tee "$BP_RUN_DIR/driver.log"
