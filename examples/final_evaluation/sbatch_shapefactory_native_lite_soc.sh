#!/usr/bin/env bash
#SBATCH --job-name=sf-native-lite
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
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose the assigned GPU}"
: "${SHAPEFACTORY_MODEL:?Missing model path}"
: "${SHAPEFACTORY_LABEL:?Missing output label}"
runner="${SHAPEFACTORY_RUNNER_PYTHON:-/home/e/e1300530/tmp/collabsim-native-lite-venv/bin/python}"
"$runner" -c 'import yaml,litellm,httpx; from examples.final_evaluation.shapefactory_lite import verify_source; verify_source()'
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1 LITELLM_API_KEY=EMPTY
nvcc_path="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
export PATH="$CUDA_HOME/bin:$PATH"
site_path="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_path/nvidia/cuda_runtime/lib:$site_path/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
port=$((20000 + (SLURM_JOB_ID % 10000)*2))
out="$PWD/runs/shapefactory_native_lite/${SHAPEFACTORY_LABEL}-${SLURM_JOB_ID}"
mkdir -p runs/shapefactory_native_lite
exec python -u -m examples.final_evaluation.launch_calbench_local \
  --runtime soc --suite shapefactory_native_lite \
  --model "$SHAPEFACTORY_MODEL" --runner-python "$runner" \
  --ports "$port" --parallel-games 1 --max-num-seqs 32 \
  --disable-chunked-prefill --disable-cascade-attn \
  --max-tokens 4096 --output "$out"
