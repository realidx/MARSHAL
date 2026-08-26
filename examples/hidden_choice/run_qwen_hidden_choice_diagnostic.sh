#!/bin/bash
set -euo pipefail
set +x
: "${EVAL_MODEL_DIR:?Set EVAL_MODEL_DIR to the local model directory}"
ray stop --force || true

CONFIG_PATH=$(basename $(dirname "$0"))

ROLL_PATH=${PWD}
export PYTHONPATH="$ROLL_PATH:${PYTHONPATH:-}"

ROLL_OUTPUT_DIR="./runs/hidden_choice_qwen_diagnostic/$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="$ROLL_OUTPUT_DIR/logs"
ROLL_RENDER_DIR="$ROLL_OUTPUT_DIR/render"
export ROLL_OUTPUT_DIR
export ROLL_LOG_DIR
export ROLL_RENDER_DIR
mkdir -p "$ROLL_LOG_DIR"

python examples/start_agentic_rollout_pipeline.py \
  --config_path "$CONFIG_PATH" \
  --config_name agentic_rollout_hidden_choice_qwen_diagnostic \
  | tee "$ROLL_LOG_DIR/custom_logs.log"

python examples/hidden_choice/analyze_hidden_choice_run.py "$ROLL_OUTPUT_DIR"
