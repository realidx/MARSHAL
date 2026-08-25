#!/bin/bash
#SBATCH --job-name=marshal-c2c
#SBATCH --partition=gpu-long
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=96G
#SBATCH --time=3-00:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
CONDA_ENV="${CONDA_ENV:-marshal}"
BASE_MODEL="${BASE_MODEL:-/home/e/e1300530/models/Qwen3-4B}"
TREATMENT_MODEL="${TREATMENT_MODEL:-nics-efc/MARSHAL-Generalist-Qwen3-4B}"
SEED="${SEED:-26042026}"
PORT="${PORT:-$((19000 + SLURM_JOB_ID % 1000))}"
PLAN="${PLAN:-${REPO_DIR}/runs/c2c_marshal_poc/plan.json}"
RUN_DIR="${RUN_DIR:-${REPO_DIR}/runs/c2c_marshal_poc/jobs/${SLURM_JOB_ID}}"
NUM_WORKERS="${NUM_WORKERS:-4}"
C2C_DIR="${C2C_DIR:-${REPO_DIR}/third_party/cooperate-to-compete}"

cd "${REPO_DIR}"
source "${CONDA_HOME}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false
export DEBUG_LLM_CALLS=true
export OPENAI_API_BASE="http://127.0.0.1:${PORT}/v1"
export OPENAI_API_KEY=EMPTY

for required_key in OPENROUTER_API_KEY XAI_API_KEY GEMINI_API_KEY; do
  if [[ -z "${!required_key:-}" ]]; then
    echo "${required_key} must be exported when this job is submitted" >&2
    exit 2
  fi
done

mkdir -p "${RUN_DIR}/logs"
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
  python -m examples.strategic_transfer.c2c_paired run-condition \
    --plan "${PLAN}" \
    --condition "${label}" \
    --focal-model openai/qwen3-4b-focal \
    --output-dir "${RUN_DIR}" \
    --c2c-dir "${C2C_DIR}" \
    --max-turns 50 \
    --num-workers "${NUM_WORKERS}" \
    | tee "${RUN_DIR}/logs/${label}-run.log"
  if [[ "${FAIL_ON_GAME_ERROR:-false}" == "true" ]]; then
    FIRST_ERROR="$(find "${RUN_DIR}/${label}" -name error.json -print -quit)"
    if [[ -n "${FIRST_ERROR}" ]]; then
      echo "C2C infrastructure failure in ${FIRST_ERROR}" >&2
      sed -n '1,240p' "${FIRST_ERROR}" >&2
      return 3
    fi
  fi
  stop_server
}

echo "commit=$(git rev-parse HEAD)"
echo "host=$(hostname)"
echo "run_dir=${RUN_DIR}"
echo "plan=${PLAN}"
echo "base_model=${BASE_MODEL}"
echo "treatment_model=${TREATMENT_MODEL}"
test -f "${BASE_MODEL}/config.json"
test -f "${PLAN}"
test "$(git -C "${C2C_DIR}" rev-parse HEAD)" = "2f7eb4a163d21e139a3ea8b9f7d625b470594f00"

run_condition base "${BASE_MODEL}"
run_condition treatment "${TREATMENT_MODEL}"

python -m examples.strategic_transfer.c2c_paired summarize \
  --base-dir "${RUN_DIR}/base" \
  --treatment-dir "${RUN_DIR}/treatment" \
  --output "${RUN_DIR}/paired_summary.json"

echo "C2C PAIRED EVALUATION COMPLETE: ${RUN_DIR}"
