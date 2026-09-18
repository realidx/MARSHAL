#!/usr/bin/env bash
#SBATCH --job-name=benac-a
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
: "${BENAC_A_MODEL:?Missing model path}"
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
if command -v nvcc >/dev/null 2>&1; then
  CALBENCH_NVCC="$(readlink -f "$(command -v nvcc)")"
  export CUDA_HOME="$(dirname "$(dirname "$CALBENCH_NVCC")")"
else
  echo 'CUDA toolkit unavailable in existing SoC environment' >&2; exit 42
fi
export PATH="$CUDA_HOME/bin:$PATH"
CALBENCH_SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$CALBENCH_SITE/nvidia/cuda_runtime/lib:$CALBENCH_SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
python -m examples.final_evaluation.benac_a_suite
python - <<'CHECK'
import torch
assert torch.cuda.is_available() and torch.cuda.device_count()==2
for i in range(2):
    print(i,torch.cuda.get_device_name(i))
    assert torch.ones(8,device=f'cuda:{i}').sum().item()==8
CHECK
base_port=$((20000 + (SLURM_JOB_ID % 10000)*2))
out="$PWD/runs/benac_a_soc/${BENAC_A_LABEL}-${BENAC_A_STAGE}-${SLURM_JOB_ID}"
mkdir -p runs/benac_a_soc
printf '%s\n' "$out" > "runs/benac_a_soc/${BENAC_A_LABEL}-${BENAC_A_STAGE}.latest"
exec python -u -m examples.final_evaluation.launch_benac_a \
  --model "$BENAC_A_MODEL" --q0 "$BENAC_A_Q0" \
  --stage "$BENAC_A_STAGE" --ports "$base_port" "$((base_port+1))" \
  --parallel-games 4 --output "$out"
