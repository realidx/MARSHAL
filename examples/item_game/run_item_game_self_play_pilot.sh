#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_MODEL_DIR:?Set EVAL_MODEL_DIR to the local HuggingFace model directory}"
test -f "${EVAL_MODEL_DIR}/config.json"

ROLL_PATH=${PWD}
export PYTHONPATH="${ROLL_PATH}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false

OUTPUT_DIR="${ROLL_OUTPUT_DIR:-./runs/item_game_self_play/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "${OUTPUT_DIR}"

echo "model=${EVAL_MODEL_DIR}"
echo "output=${OUTPUT_DIR}/trajectories.jsonl"
EPISODES="${SELF_PLAY_EPISODES:-5}"
echo "episodes=$((EPISODES * 3)) (${EPISODES} per subtype: Collaboration + RequestSurplusReroute + RespondToGiveRequest)"

"${PYTHON_BIN:-python}" -m roll.agentic.env.item_game.synchronous_self_play \
  --model "${EVAL_MODEL_DIR}" \
  --episodes "${EPISODES}" \
  --max-new-tokens "${SELF_PLAY_MAX_NEW_TOKENS:-1024}" \
  --max-rounds "${SELF_PLAY_MAX_ROUNDS:-6}" \
  --output "${OUTPUT_DIR}/trajectories.jsonl"

echo "ITEM GAME SELF-PLAY PILOT COMPLETE: ${OUTPUT_DIR}"
