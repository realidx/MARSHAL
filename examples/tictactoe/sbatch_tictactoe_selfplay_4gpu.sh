#!/bin/bash
#SBATCH --job-name=marshal-tictactoe-4gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:4
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=48
#SBATCH --mem=0
#SBATCH --time=10:00:00
#SBATCH --output=slurm-%x-%j.out


set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
CONDA_ENV="${CONDA_ENV:-marshal}"

cd "${REPO_DIR}"

source "${CONDA_HOME}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"

export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
export TOKENIZERS_PARALLELISM=false

ray stop --force || true

ROLL_OUTPUT_DIR="./runs/tictactoe_selfplay_4gpu/${SLURM_JOB_ID:-manual}-$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="${ROLL_OUTPUT_DIR}/logs"
ROLL_RENDER_DIR="${ROLL_OUTPUT_DIR}/render"
export ROLL_OUTPUT_DIR ROLL_LOG_DIR ROLL_RENDER_DIR
mkdir -p "${ROLL_LOG_DIR}" "${ROLL_RENDER_DIR}"

python examples/start_agentic_pipeline.py \
  --config_path tictactoe \
  --config_name agentic_val_tictactoe_selfplay_4gpu \
  2>&1 | tee "${ROLL_LOG_DIR}/custom_logs.log"

ray stop --force || true
