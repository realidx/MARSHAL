#!/usr/bin/env bash
set -euo pipefail
set +x

: "${EVAL_MODEL_DIR:?Set EVAL_MODEL_DIR to the Qwen3-4B-Instruct model directory}"
test -f "${EVAL_MODEL_DIR}/config.json"

ray stop --force || true

CONFIG_PATH=$(basename "$(dirname "$0")")
ROLL_PATH=${PWD}
export PYTHONPATH="${ROLL_PATH}:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false

ROLL_OUTPUT_DIR="./runs/item_game_qwen3_4b_instruct_request_surplus_reroute_pilot/$(date +%Y%m%d-%H%M%S)"
export ROLL_OUTPUT_DIR
export ROLL_LOG_DIR="${ROLL_OUTPUT_DIR}/logs"
export ROLL_RENDER_DIR="${ROLL_OUTPUT_DIR}/render"
mkdir -p "${ROLL_LOG_DIR}"

echo "model=${EVAL_MODEL_DIR}"
echo "output=${ROLL_OUTPUT_DIR}"
echo "episodes=240"
echo "env=ItemGame-RequestSurplusReroute only"
python examples/start_agentic_rollout_pipeline.py \
  --config_path "${CONFIG_PATH}" \
  --config_name agentic_rollout_item_game_request_surplus_reroute \
  | tee "${ROLL_LOG_DIR}/custom_logs.log"

echo "ITEM GAME REQUEST-SURPLUS-REROUTE PILOT COMPLETE: ${ROLL_OUTPUT_DIR}"
