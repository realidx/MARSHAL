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

echo "backend=${ITEM_GAME_BACKEND}"
echo "model=${ITEM_GAME_MODEL}"
echo "output=${OUTPUT_DIR}/trajectories.jsonl"
EPISODES="${SELF_PLAY_EPISODES:-5}"
echo "episodes=$((EPISODES * 3)) (${EPISODES} per subtype: Collaboration + RequestSurplusReroute + RespondToGiveRequest)"

"${PYTHON_BIN:-python}" -m roll.agentic.env.item_game.synchronous_self_play \
  --model "${ITEM_GAME_MODEL}" \
  --backend "${ITEM_GAME_BACKEND}" \
  --vllm-base-url "${VLLM_BASE_URL:-http://localhost:8000/v1}" \
  --vllm-api-key "${VLLM_API_KEY:-EMPTY}" \
  --episodes "${EPISODES}" \
  --max-new-tokens "${SELF_PLAY_MAX_NEW_TOKENS:-1024}" \
  --max-rounds "${SELF_PLAY_MAX_ROUNDS:-6}" \
  --output "${OUTPUT_DIR}/trajectories.jsonl"

echo "ITEM GAME SELF-PLAY PILOT COMPLETE: ${OUTPUT_DIR}"
