#!/bin/bash
#SBATCH --job-name=geo-to-ttt-eval
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-96:1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --time=08:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
CONDA_ENV="${CONDA_ENV:-marshal}"
EVAL_LABEL="${EVAL_LABEL:-727616-checkpoint-99}"
CHECKPOINT_RUN_DIR="${CHECKPOINT_RUN_DIR:-${REPO_DIR}/runs/geography_counterfactual_distance3_5/727616-20260812-133142}"

cd "${REPO_DIR}"

source "${CONDA_HOME}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export ROLL_ASSIGNED_CUDA_DEVICES="${CUDA_VISIBLE_DEVICES}"
export RAY_NUM_GPUS_PER_NODE=1

# The saved Megatron tensor-parallel ranks live in separate actor-worker
# directories. Build a lightweight merged view and export it once to the
# Hugging Face layout required by vLLM. Existing exports are never overwritten.
if [[ -z "${EVAL_MODEL_DIR:-}" ]]; then
  RANK0_CHECKPOINT="${CHECKPOINT_RUN_DIR}/actor_train-0/checkpoint-99"
  RANK1_CHECKPOINT="${CHECKPOINT_RUN_DIR}/actor_train-1/checkpoint-99"
  ITERATION_DIR="iter_0000001"
  MERGED_CHECKPOINT="${CHECKPOINT_RUN_DIR}/checkpoint-99-merged-mca"
  EXPORTED_CHECKPOINT="${CHECKPOINT_RUN_DIR}/checkpoint-99-hf"

  test -f "${RANK0_CHECKPOINT}/${ITERATION_DIR}/mp_rank_00/model_optim_rng.pt"
  test -f "${RANK1_CHECKPOINT}/${ITERATION_DIR}/mp_rank_01/model_optim_rng.pt"

  mkdir -p "${MERGED_CHECKPOINT}/${ITERATION_DIR}"
  if [[ ! -f "${MERGED_CHECKPOINT}/mca_config.json" ]]; then
    find "${RANK0_CHECKPOINT}" -maxdepth 1 -type f -exec cp -p {} "${MERGED_CHECKPOINT}/" \;
  fi
  if [[ ! -e "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_00" && ! -L "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_00" ]]; then
    ln -s "${RANK0_CHECKPOINT}/${ITERATION_DIR}/mp_rank_00" "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_00"
  fi
  if [[ ! -e "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_01" && ! -L "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_01" ]]; then
    ln -s "${RANK1_CHECKPOINT}/${ITERATION_DIR}/mp_rank_01" "${MERGED_CHECKPOINT}/${ITERATION_DIR}/mp_rank_01"
  fi

  if [[ ! -f "${EXPORTED_CHECKPOINT}/config.json" ]]; then
    BUILD_DIR="${CHECKPOINT_RUN_DIR}/checkpoint-99-hf-building-${SLURM_JOB_ID:-manual}"
    if [[ -e "${BUILD_DIR}" || -e "${EXPORTED_CHECKPOINT}" ]]; then
      echo "Refusing to replace an incomplete checkpoint export" >&2
      exit 46
    fi
    python - "${MERGED_CHECKPOINT}" "${BUILD_DIR}" <<'PY'
import sys
from mcore_adapter.models.converter.post_converter import convert_checkpoint_to_hf

convert_checkpoint_to_hf(sys.argv[1], sys.argv[2], verbose=False)
PY
    mv "${BUILD_DIR}" "${EXPORTED_CHECKPOINT}"
  fi
  EVAL_MODEL_DIR="${EXPORTED_CHECKPOINT}"
fi

test -f "${EVAL_MODEL_DIR}/config.json"
export EVAL_MODEL_DIR EVAL_LABEL

ROLL_OUTPUT_DIR="./runs/geography_transfer_tictactoe/${EVAL_LABEL}/${SLURM_JOB_ID:-manual}-$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="${ROLL_OUTPUT_DIR}/logs"
ROLL_RENDER_DIR="${ROLL_OUTPUT_DIR}/render"
export ROLL_OUTPUT_DIR ROLL_LOG_DIR ROLL_RENDER_DIR
mkdir -p "${ROLL_LOG_DIR}"

echo "model=${EVAL_MODEL_DIR}"
echo "label=${EVAL_LABEL}"
echo "output=${ROLL_OUTPUT_DIR}"

srun --cpu-bind=none --mem=0 --ntasks=1 ray stop --force || true
srun --cpu-bind=none --mem=0 --ntasks=1 \
  python examples/start_agentic_rollout_pipeline.py \
    --config_path . \
    --config_name tictactoe/agentic_eval_geography_transfer_tictactoe \
  2>&1 | tee "${ROLL_LOG_DIR}/custom_logs.log"
srun --cpu-bind=none --mem=0 --ntasks=1 ray stop --force || true
