#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --signal=B:USR1@900
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from repository root}"
source "${CONDA_HOME:-/home/e/e1300530/miniconda3}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MODEL="${SOCIAL_MODEL:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose GPUs}"
export ROLL_ASSIGNED_CUDA_DEVICES="$CUDA_VISIBLE_DEVICES" RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1
unset VLLM_USE_V1
export TOKENIZERS_PARALLELISM=false CUDA_DEVICE_MAX_CONNECTIONS=1 VLLM_TOOL_CALL_PARSER=hermes
export VLLM_BATCH_INVARIANT=0 NCCL_SOCKET_IFNAME=lo GLOO_SOCKET_IFNAME=lo
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 ROLL_LOCAL_COMM_ADDR=127.0.0.1 BP_STARTUP_DIAGNOSTICS=1
export SOCIAL_GPU_PREFLIGHT=1
if command -v nvcc >/dev/null 2>&1; then
  TASK_NVCC="$(readlink -f "$(command -v nvcc)")"
  export CUDA_HOME="$(dirname "$(dirname "$TASK_NVCC")")"
elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
  export CUDA_HOME=/usr/local/cuda
else
  echo 'Existing environment has no CUDA toolkit' >&2; exit 42
fi
export PATH="$CUDA_HOME/bin:$PATH"
TASK_SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$TASK_SITE/nvidia/cuda_runtime/lib:$TASK_SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
TASK_OUTPUT="$PWD/runs/strategic_slices/${STRATEGIC_ARM}-seed${STRATEGIC_SEED:-42}-${SLURM_JOB_ID}"
mkdir -p "$(dirname "$TASK_OUTPUT")"
args=(--arm "$STRATEGIC_ARM" --data "$STRATEGIC_DATA" --model "$SOCIAL_MODEL" --output "$TASK_OUTPUT"
      --profile "$SOCIAL_GPU_PROFILE" --seed "${STRATEGIC_SEED:-42}"
      --total-tokens "${STRATEGIC_TOTAL_TOKENS:-6553600}" --tokens-per-update "${STRATEGIC_TOKENS_PER_UPDATE:-65536}"
      --replicas "${STRATEGIC_REPLICAS:-4}" --eval-every "${STRATEGIC_EVAL_EVERY:-10}")
if [[ -n "${STRATEGIC_RESUME:-}" ]]; then args+=(--resume "$STRATEGIC_RESUME"); fi
if [[ -n "${STRATEGIC_PAUSE_AFTER_UPDATES:-}" ]]; then args+=(--pause-after-updates "$STRATEGIC_PAUSE_AFTER_UPDATES"); fi
python -u -m training.strategic_slices.train "${args[@]}" > "${TASK_OUTPUT}.log" 2>&1 &
TASK_PID=$!
trap 'kill -USR1 "$TASK_PID" 2>/dev/null || true' USR1 TERM
set +e
while true; do
  wait "$TASK_PID"; TASK_STATUS=$?
  kill -0 "$TASK_PID" 2>/dev/null || break
done
set -e
printf '%s\n' "$TASK_STATUS" > "${TASK_OUTPUT}.EXIT_CODE"
tail -n 30 "${TASK_OUTPUT}.log"
exit "$TASK_STATUS"
