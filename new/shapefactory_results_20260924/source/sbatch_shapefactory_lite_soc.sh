#!/usr/bin/env bash
#SBATCH --job-name=sf-lite-q0
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=64G
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from repository root}"
source "${CONDA_HOME:-/home/e/e1300530/miniconda3}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose assigned GPUs}"
: "${SHAPEFACTORY_MODEL:?Missing model path}"
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
export SHAPEFACTORY_RUNNER_MODULE=examples.final_evaluation.shapefactory_lite
SHAPEFACTORY_NVCC="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$SHAPEFACTORY_NVCC")")"
export PATH="$CUDA_HOME/bin:$PATH"
SHAPEFACTORY_SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$SHAPEFACTORY_SITE/nvidia/cuda_runtime/lib:$SHAPEFACTORY_SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
runner="${SHAPEFACTORY_RUNNER_PYTHON:-$CONDA_PREFIX/bin/python}"
"$runner" -c 'from examples.final_evaluation.shapefactory_lite import CASES,witness; [witness(c) for c in CASES]'
base_port=$((20000 + (SLURM_JOB_ID % 10000)*2))
out="$PWD/runs/shapefactory_soc/${SHAPEFACTORY_LABEL:-q0}-lite-v2-${SLURM_JOB_ID}"
mkdir -p runs/shapefactory_soc
exec python -u -m examples.final_evaluation.launch_shapefactory_local \
  --runtime soc --model "$SHAPEFACTORY_MODEL" --max-tokens 4096 \
  --runner-python "$runner" --ports "$base_port" --parallel-games 2 \
  --max-num-seqs 32 --disable-chunked-prefill --disable-cascade-attn --output "$out"
