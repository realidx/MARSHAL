#!/usr/bin/env bash
#SBATCH --job-name=terminal-step-binary
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-47:2
#SBATCH --time=03:00:00
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
export SOCIAL_GPU_PROFILE="${SOCIAL_GPU_PROFILE:-h100-47}"
TASK_OUTPUT="${TERMINAL_OUTPUT:-$PWD/runs/terminal_step_binary/seed${TERMINAL_SEED:-42}-${SLURM_JOB_ID}}"
mkdir -p "$(dirname "$TASK_OUTPUT")"
args=(--model "$SOCIAL_MODEL" --output "$TASK_OUTPUT"
      --profile "$SOCIAL_GPU_PROFILE" --seed "${TERMINAL_SEED:-42}"
      --total-tokens "${TERMINAL_TOTAL_TOKENS:-6000000}" --questions-per-update "${TERMINAL_QUESTIONS_PER_UPDATE:-4}"
      --replicas "${TERMINAL_REPLICAS:-8}" --concurrency "${TERMINAL_CONCURRENCY:-32}"
      --max-tokens "${TERMINAL_MAX_TOKENS:-1024}" --context "${TERMINAL_CONTEXT:-16384}"
      --eval-every "${TERMINAL_EVAL_EVERY:-10}" --max-steps "${TERMINAL_MAX_STEPS:-10000}"
      --test-repeats "${TERMINAL_TEST_REPEATS:-8}")
if [[ -n "${TERMINAL_POOL:-}" ]]; then args+=(--pool "$TERMINAL_POOL"); fi
if [[ -n "${TERMINAL_SELECTION:-}" ]]; then args+=(--selection "$TERMINAL_SELECTION"); fi
if [[ -n "${TERMINAL_RESUME:-}" ]]; then args+=(--resume "$TERMINAL_RESUME"); fi
if [[ -n "${TERMINAL_PAUSE_AFTER_UPDATES:-}" ]]; then args+=(--pause-after-updates "$TERMINAL_PAUSE_AFTER_UPDATES"); fi
if [[ -n "${TERMINAL_VALIDATION_LIMIT:-}" ]]; then args+=(--validation-limit "$TERMINAL_VALIDATION_LIMIT"); fi
python -u -m training.strategic_slices.train_terminal "${args[@]}" > "${TASK_OUTPUT}.log" 2>&1 &
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
