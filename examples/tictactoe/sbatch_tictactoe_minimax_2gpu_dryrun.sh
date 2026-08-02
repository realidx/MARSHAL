#!/bin/bash
#SBATCH --job-name=marshal-ttt-minimax-dry
#SBATCH --partition=gpu
#SBATCH --nodes=2
#SBATCH --gres=gpu:a100-80:1
#SBATCH --constraint=xgph
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
TASK_CONDA_ENV_DIR="${TASK_CONDA_ENV_DIR:-${CONDA_HOME}/envs/marshal}"

cd "${REPO_DIR}"
export PATH="${TASK_CONDA_ENV_DIR}/bin:${PATH}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
TASK_CUDNN_LIB="${TASK_CONDA_ENV_DIR}/lib/python3.10/site-packages/nvidia/cudnn/lib"
export LD_LIBRARY_PATH="${TASK_CUDNN_LIB}:${LD_LIBRARY_PATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
export TOKENIZERS_PARALLELISM=false

srun --cpu-bind=none --mem=0 --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 ray stop --force || true

ROLL_OUTPUT_DIR="./runs/tictactoe_minimax_2gpu_dryrun/${SLURM_JOB_ID:-manual}-$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="${ROLL_OUTPUT_DIR}/logs"
ROLL_RENDER_DIR="${ROLL_OUTPUT_DIR}/render"
export ROLL_OUTPUT_DIR ROLL_LOG_DIR ROLL_RENDER_DIR
mkdir -p "${ROLL_LOG_DIR}"

MASTER_ADDR="$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | head -n 1)"
MASTER_PORT="$((30000 + SLURM_JOB_ID % 20000))"
export MASTER_ADDR MASTER_PORT

srun --cpu-bind=none --mem=0 --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 \
  bash -c '
    export RANK="${SLURM_PROCID}"
    export WORLD_SIZE="${SLURM_NTASKS}"
    export WORKER_ID="${SLURMD_NODENAME}"
    python examples/start_agentic_pipeline.py \
      --config_path tictactoe \
      --config_name agentic_train_tictactoe_minimax_selfplay_2gpu_dryrun
  ' \
  2>&1 | tee "${ROLL_LOG_DIR}/custom_logs.log"

srun --cpu-bind=none --mem=0 --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 ray stop --force || true
