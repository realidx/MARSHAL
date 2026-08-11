#!/bin/bash
#SBATCH --job-name=marshal-geo-d3d5-full
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-96:2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --time=24:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
CONDA_ENV="${CONDA_ENV:-marshal}"
CONFIG_NAME="${CONFIG_NAME:-agentic_train_geography_counterfactual_distance3_5_2gpu}"

cd "${REPO_DIR}"

source "${CONDA_HOME}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
TASK_CUDNN_LIB="${CONDA_PREFIX}/lib/python3.10/site-packages/nvidia/cudnn/lib"
TASK_CUDA_LIB="${CONDA_PREFIX}/lib"
TASK_CUDA_TARGET_LIB="${CONDA_PREFIX}/targets/x86_64-linux/lib"
TASK_PYPI_CUDA_RUNTIME_LIB="${CONDA_PREFIX}/lib/python3.10/site-packages/nvidia/cuda_runtime/lib"
export LD_LIBRARY_PATH="${TASK_CUDA_LIB}:${TASK_CUDA_TARGET_LIB}:${TASK_PYPI_CUDA_RUNTIME_LIB}:${TASK_CUDNN_LIB}:${LD_LIBRARY_PATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
export RAY_NUM_GPUS_PER_NODE="${RAY_NUM_GPUS_PER_NODE:-2}"
export TOKENIZERS_PARALLELISM=false

echo "host=$(hostname)"
echo "commit=$(git rev-parse HEAD)"
echo "conda_prefix=${CONDA_PREFIX}"
echo "python=$(command -v python)"
git status --short

if command -v nvcc >/dev/null 2>&1; then
  TASK_NVCC="$(readlink -f "$(command -v nvcc)")"
  export CUDA_HOME="$(dirname "$(dirname "${TASK_NVCC}")")"
elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
  export CUDA_HOME=/usr/local/cuda
else
  echo "CUDA toolkit/nvcc is unavailable on $(hostname)" >&2
  exit 42
fi
export PATH="${CUDA_HOME}/bin:${PATH}"

echo "cuda_home=${CUDA_HOME}"
echo "nvcc=$(command -v nvcc)"
python -c 'import ctypes, torch, deepspeed; from torch.utils.cpp_extension import CUDA_HOME; ctypes.CDLL("libcudart.so"); print(f"torch={torch.__version__} torch_cuda={torch.version.cuda} cuda_home={CUDA_HOME} deepspeed={deepspeed.__version__} libcudart=ok")'

srun --cpu-bind=none --mem=0 --ntasks=1 ray stop --force || true

ROLL_OUTPUT_DIR="./runs/geography_counterfactual_distance3_5/${SLURM_JOB_ID:-manual}-$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="${ROLL_OUTPUT_DIR}/logs"
ROLL_RENDER_DIR="${ROLL_OUTPUT_DIR}/render"
export ROLL_OUTPUT_DIR ROLL_LOG_DIR ROLL_RENDER_DIR CONFIG_NAME
mkdir -p "${ROLL_LOG_DIR}"

MASTER_ADDR="$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | head -n 1)"
MASTER_PORT="$((30000 + SLURM_JOB_ID % 20000))"
export MASTER_ADDR MASTER_PORT

srun --cpu-bind=none --mem=0 --ntasks=1 \
  bash -c '
    export RANK=0
    export WORLD_SIZE=1
    export WORKER_ID="${SLURMD_NODENAME}"
    python examples/start_agentic_pipeline.py \
      --config_path . \
      --config_name "geography/${CONFIG_NAME}"
  ' \
  2>&1 | tee "${ROLL_LOG_DIR}/custom_logs.log"

srun --cpu-bind=none --mem=0 --ntasks=1 ray stop --force || true
