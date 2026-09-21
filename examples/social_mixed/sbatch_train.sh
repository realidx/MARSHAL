#!/usr/bin/env bash
#SBATCH --job-name=marshal-social
#SBATCH --partition=gpu-long
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-96:2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --time=3-00:00:00
#SBATCH --signal=B:USR1@900
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the MARSHAL repository}"
SOCIAL_ARM="${SOCIAL_ARM:-bp}"
export SOCIAL_DATA_DIR="${SOCIAL_DATA_DIR:-$PWD/examples/social_mixed/data_reasoning_v6}"
SOCIAL_SEED="${SOCIAL_SEED:-42}"
source "${CONDA_HOME:-/home/e/e1300530/miniconda3}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MODEL="${SOCIAL_MODEL:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose the assigned GPUs}"
export ROLL_ASSIGNED_CUDA_DEVICES="$CUDA_VISIBLE_DEVICES"
export RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1
unset VLLM_USE_V1  # vLLM 0.28 uses V1; this retired variable cannot select V0.
export TOKENIZERS_PARALLELISM=false CUDA_DEVICE_MAX_CONNECTIONS=1
export VLLM_TOOL_CALL_PARSER=hermes
export VLLM_BATCH_INVARIANT=1
export NCCL_SOCKET_IFNAME=lo GLOO_SOCKET_IFNAME=lo
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export ROLL_LOCAL_COMM_ADDR=127.0.0.1
export BP_STARTUP_DIAGNOSTICS=1
export SOCIAL_GPU_PREFLIGHT=1
export SOCIAL_GPU_PROFILE="${SOCIAL_GPU_PROFILE:-h100-96}"
if command -v nvcc >/dev/null 2>&1; then
  SOCIAL_NVCC="$(readlink -f "$(command -v nvcc)")"
  export CUDA_HOME="$(dirname "$(dirname "$SOCIAL_NVCC")")"
elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
  export CUDA_HOME=/usr/local/cuda
else
  echo 'CUDA toolkit unavailable in the existing SoC environment' >&2
  exit 42
fi
export PATH="$CUDA_HOME/bin:$PATH"
SOCIAL_SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$SOCIAL_SITE/nvidia/cuda_runtime/lib:$SOCIAL_SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
# Transformer Engine uses CUDA 13 while vLLM also installs a CUDA 12 runtime.
# Keep cuDNN frontend from selecting the incompatible libcudart.so.12.
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
export ROLL_OUTPUT_DIR="$PWD/runs/social_mixed/${SOCIAL_ARM}-seed${SOCIAL_SEED}-${SLURM_JOB_ID}"
export ROLL_LOG_DIR="$ROLL_OUTPUT_DIR/logs" BP_DIAGNOSTICS_DIR="$ROLL_OUTPUT_DIR"
mkdir -p "$ROLL_LOG_DIR"
printf '%s\n' "$ROLL_OUTPUT_DIR" > "runs/social_mixed/${SOCIAL_ARM}_latest.txt"
args=(--arm "$SOCIAL_ARM" --seed "$SOCIAL_SEED" --total-tokens "${SOCIAL_TOTAL_TOKENS:-6553600}")
if [[ -n "${SOCIAL_RECIPE:-}" ]]; then args+=(--recipe "$SOCIAL_RECIPE"); fi
args+=(--normalization "${SOCIAL_NORMALIZATION:-centered_fixed}")
args+=(--tokens-per-update "${SOCIAL_TOKENS_PER_UPDATE:-65536}")
if [[ "${SOCIAL_DIAGNOSE_PROBABILITIES:-0}" == 1 ]]; then args+=(--diagnose-probabilities); fi
args+=(--keep-checkpoints 2 --protocol-coefficient "${SOCIAL_PROTOCOL_COEFFICIENT:-0.2}")
if [[ -n "${SOCIAL_RESUME:-}" ]]; then args+=(--resume "$SOCIAL_RESUME"); fi
# No ray stop --force: this job owns a private local head.
python -u -m training.social_mixed.run "${args[@]}" > "$ROLL_OUTPUT_DIR/train.log" 2>&1 &
SOCIAL_PID=$!
trap 'kill -USR1 "$SOCIAL_PID" 2>/dev/null || true' USR1 TERM
set +e
while true; do
  wait "$SOCIAL_PID"
  SOCIAL_STATUS=$?
  kill -0 "$SOCIAL_PID" 2>/dev/null || break
done
set -e
printf '%s\n' "$SOCIAL_STATUS" > "$ROLL_OUTPUT_DIR/EXIT_CODE"
tail -n 30 "$ROLL_OUTPUT_DIR/train.log"
exit "$SOCIAL_STATUS"
