#!/usr/bin/env bash
#SBATCH --job-name=item-game-reason-probe
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=0
#SBATCH --time=00:30:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

cd /home/e/e1300530/MARSHAL

VLLM_ENV=/home/e/e1300530/tmp/marshal-vllm09
export PATH="${VLLM_ENV}/bin:${PATH}"
export PYTHON_BIN="${VLLM_ENV}/bin/python"
export VLLM_MODEL="/home/e/e1300530/models/Qwen3-4B-Instruct-2507"
export VLLM_SERVED_MODEL_NAME="Qwen/Qwen3-4B-Instruct-2507"
export VLLM_TOOL_CALL_PARSER="hermes"

SERVER_LOG="/tmp/item-game-reason-probe-vllm-${SLURM_JOB_ID}.log"
OUTPUT_DIR="runs/item_game_native_reason_probe/${SLURM_JOB_ID}"

echo "node=$(hostname) job=${SLURM_JOB_ID} output=${OUTPUT_DIR}"
echo "python=${PYTHON_BIN}"
"${PYTHON_BIN}" -c 'import vllm, torch, transformers; print({"vllm": vllm.__version__, "torch": torch.__version__, "transformers": transformers.__version__})'

bash examples/item_game/run_item_game_vllm_028_server.sh >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8000/v1/models >/tmp/item-game-reason-probe-models-${SLURM_JOB_ID}.json 2>/dev/null; then
    break
  fi
  sleep 5
done
curl -fsS http://127.0.0.1:8000/version || true
echo
cat /tmp/item-game-reason-probe-models-${SLURM_JOB_ID}.json

"${PYTHON_BIN}" examples/item_game/probe_vllm_native_reason_tool_choice.py \
  --model "${VLLM_SERVED_MODEL_NAME}" \
  --base-url http://127.0.0.1:8000/v1 \
  --output-dir "${OUTPUT_DIR}"

echo "server_log=${SERVER_LOG}"
