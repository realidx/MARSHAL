#!/usr/bin/env bash
#SBATCH --job-name=shapefactory
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
: "${SHAPEFACTORY_LABEL:?Missing output label}"
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
if command -v nvcc >/dev/null 2>&1; then
  SHAPEFACTORY_NVCC="$(readlink -f "$(command -v nvcc)")"
  export CUDA_HOME="$(dirname "$(dirname "$SHAPEFACTORY_NVCC")")"
else
  echo 'CUDA toolkit unavailable in existing SoC environment' >&2; exit 42
fi
export PATH="$CUDA_HOME/bin:$PATH"
SHAPEFACTORY_SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$SHAPEFACTORY_SITE/nvidia/cuda_runtime/lib:$SHAPEFACTORY_SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
runner="${SHAPEFACTORY_RUNNER_PYTHON:-$PWD/.venv-calbench/bin/python}"
"$runner" -c 'from examples.final_evaluation.shapefactory_references import audit; audit()'
python - <<'PY'
import torch
assert torch.cuda.is_available()
print('Visible GPUs:',torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print(i,torch.cuda.get_device_name(i),torch.cuda.get_device_properties(i).total_memory)
    x=torch.ones(8,device=f'cuda:{i}');assert x.sum().item()==8
PY
IFS=',' read -ra cards <<< "$CUDA_VISIBLE_DEVICES"
# Job-specific port pair; launcher rejects a collision without killing anything.
base_port=$((20000 + (SLURM_JOB_ID % 10000)*2))
ports=("$base_port")
if [[ ${#cards[@]} -eq 2 ]]; then ports+=("$((base_port+1))"); fi
out="$PWD/runs/shapefactory_soc/${SHAPEFACTORY_LABEL}-shape24-${SLURM_JOB_ID}"
mkdir -p runs/shapefactory_soc
printf '%s\n' "$out" > "runs/shapefactory_soc/${SHAPEFACTORY_LABEL}-shape24.latest"
exec python -u -m examples.final_evaluation.launch_shapefactory_local \
  --runtime soc --model "$SHAPEFACTORY_MODEL" \
  --max-tokens "${SHAPEFACTORY_MAX_TOKENS:-4096}" --runner-python "$runner" \
  --ports "${ports[@]}" --parallel-games "${#cards[@]}" --output "$out"
