#!/usr/bin/env bash
set -euo pipefail

: "${ITEM_GAME_BACKEND:=vllm}"
if [[ "${ITEM_GAME_BACKEND}" == "hf" ]]; then
  : "${EVAL_MODEL_DIR:?Set EVAL_MODEL_DIR to the local HuggingFace model directory}"
  test -f "${EVAL_MODEL_DIR}/config.json"
  ITEM_GAME_MODEL="${EVAL_MODEL_DIR}"
else
  ITEM_GAME_MODEL="${VLLM_MODEL:-${EVAL_MODEL_DIR:-Qwen/Qwen3-4B-Instruct}}"
fi

ROLL_PATH=${PWD}
export PYTHONPATH="${ROLL_PATH}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false

OUTPUT_DIR="${ROLL_OUTPUT_DIR:-./runs/item_game_self_play/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "${OUTPUT_DIR}"

VLLM_BASE_URL="${VLLM_BASE_URL:-http://localhost:8000/v1}"
VLLM_API_KEY="${VLLM_API_KEY:-EMPTY}"
if [[ "${ITEM_GAME_BACKEND}" == "vllm" ]]; then
  command -v curl >/dev/null 2>&1 || {
    echo "ERROR: vLLM backend requires curl for the readiness check" >&2
    exit 1
  }
  READY_TIMEOUT="${VLLM_READY_TIMEOUT:-600}"
  READY_INTERVAL="${VLLM_READY_INTERVAL:-5}"
  [[ "${READY_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: VLLM_READY_TIMEOUT must be a positive integer" >&2
    exit 1
  }
  [[ "${READY_INTERVAL}" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: VLLM_READY_INTERVAL must be a positive integer" >&2
    exit 1
  }
  READY_BASE_URL="${VLLM_BASE_URL%/}"
  if [[ "${READY_BASE_URL}" != */v1 ]]; then
    READY_BASE_URL="${READY_BASE_URL}/v1"
  fi
  READY_URL="${READY_BASE_URL}/models"
  READY_START="$(date +%s)"
  READY_LAST_LOG=-30
  echo "waiting for vLLM readiness at ${READY_URL} (timeout=${READY_TIMEOUT}s)"
  while ! curl --silent --fail --max-time 5 \
      -H "Authorization: Bearer ${VLLM_API_KEY}" \
      "${READY_URL}" >/dev/null; do
    READY_NOW="$(date +%s)"
    READY_ELAPSED=$((READY_NOW - READY_START))
    if (( READY_ELAPSED >= READY_TIMEOUT )); then
      echo "ERROR: vLLM did not become ready within ${READY_TIMEOUT}s: ${READY_URL}" >&2
      exit 1
    fi
    if (( READY_ELAPSED >= READY_LAST_LOG + 30 )); then
      echo "still waiting for vLLM readiness (${READY_ELAPSED}/${READY_TIMEOUT}s)"
      READY_LAST_LOG=${READY_ELAPSED}
    fi
    sleep "${READY_INTERVAL}"
  done
  READY_NOW="$(date +%s)"
  echo "vLLM ready after $((READY_NOW - READY_START))s"
fi

echo "backend=${ITEM_GAME_BACKEND}"
echo "model=${ITEM_GAME_MODEL}"
echo "output=${OUTPUT_DIR}/trajectories.jsonl"
EPISODES="${SELF_PLAY_EPISODES:-5}"
echo "episodes=$((EPISODES * 3)) (${EPISODES} per subtype: Collaboration + RequestSurplusReroute + RespondToGiveRequest)"

"${PYTHON_BIN:-python}" -m roll.agentic.env.item_game.synchronous_self_play \
  --model "${ITEM_GAME_MODEL}" \
  --backend "${ITEM_GAME_BACKEND}" \
  --vllm-base-url "${VLLM_BASE_URL}" \
  --vllm-api-key "${VLLM_API_KEY}" \
  --episodes "${EPISODES}" \
  --max-new-tokens "${SELF_PLAY_MAX_NEW_TOKENS:-1024}" \
  --max-rounds "${SELF_PLAY_MAX_ROUNDS:-6}" \
  --output "${OUTPUT_DIR}/trajectories.jsonl"

echo "ITEM GAME SELF-PLAY PILOT COMPLETE: ${OUTPUT_DIR}"
