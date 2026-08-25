#!/bin/bash
#SBATCH --job-name=marshal-trust
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
CONDA_ENV="${CONDA_ENV:-marshal}"
BASE_MODEL="${BASE_MODEL:-/home/e/e1300530/models/Qwen3-4B}"
TREATMENT_MODEL="${TREATMENT_MODEL:-nics-efc/MARSHAL-Generalist-Qwen3-4B}"
SEED="${SEED:-26042026}"
NUM_EPISODES="${NUM_EPISODES:-50}"
NUM_ROUNDS="${NUM_ROUNDS:-12}"
PORT="${PORT:-$((18000 + SLURM_JOB_ID % 1000))}"
RUN_DIR="${RUN_DIR:-${REPO_DIR}/runs/trust_calibration/jobs/${SLURM_JOB_ID}}"

cd "${REPO_DIR}"
source "${CONDA_HOME}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false

mkdir -p "${RUN_DIR}/logs"
SUITE="${RUN_DIR}/suite.jsonl"
SERVER_PID=""

stop_server() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  SERVER_PID=""
}
trap stop_server EXIT INT TERM

start_server() {
  local model="$1"
  local label="$2"
  srun --cpu-bind=none --mem=0 --ntasks=1 \
    vllm serve "${model}" \
      --served-model-name qwen3-4b-focal \
      --port "${PORT}" \
      --max-model-len 32768 \
      --dtype bfloat16 \
      --gpu-memory-utilization 0.90 \
      --generation-config vllm \
      --seed "${SEED}" \
      >"${RUN_DIR}/logs/vllm-${label}.log" 2>&1 &
  SERVER_PID=$!

  for attempt in $(seq 1 720); do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
      echo "vLLM exited before becoming ready for ${label}" >&2
      tail -n 100 "${RUN_DIR}/logs/vllm-${label}.log" >&2 || true
      return 1
    fi
    if (( attempt % 12 == 0 )); then
      echo "waiting for ${label} server (${attempt}/720)"
    fi
    sleep 5
  done
  echo "timed out waiting for ${label} server" >&2
  return 1
}

run_condition() {
  local label="$1"
  local model="$2"
  start_server "${model}" "${label}"
  python -m examples.strategic_transfer.trust_calibration run \
    --suite "${SUITE}" \
    --output "${RUN_DIR}/${label}.jsonl" \
    --api-base "http://127.0.0.1:${PORT}/v1" \
    --api-key EMPTY \
    --model qwen3-4b-focal \
    --temperature 0.2 \
    | tee "${RUN_DIR}/logs/${label}-run.log"
  python -m examples.strategic_transfer.trust_calibration score \
    --input "${RUN_DIR}/${label}.jsonl" \
    --output "${RUN_DIR}/${label}-metrics.json"
  stop_server
}

echo "commit=$(git rev-parse HEAD)"
echo "host=$(hostname)"
echo "run_dir=${RUN_DIR}"
echo "base_model=${BASE_MODEL}"
echo "treatment_model=${TREATMENT_MODEL}"
test -f "${BASE_MODEL}/config.json"

python -m examples.strategic_transfer.trust_calibration generate \
  --output "${SUITE}" \
  --num-episodes "${NUM_EPISODES}" \
  --num-rounds "${NUM_ROUNDS}" \
  --seed-base "${SEED}"

run_condition base "${BASE_MODEL}"
run_condition treatment "${TREATMENT_MODEL}"

echo "TRUST CALIBRATION COMPLETE: ${RUN_DIR}"
