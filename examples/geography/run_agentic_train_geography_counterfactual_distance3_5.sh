#!/bin/bash
set -euo pipefail
set +x
ray stop --force || true

CONFIG_PATH=.
CONFIG_NAME=${CONFIG_NAME:-agentic_train_geography_counterfactual_distance3_5_2gpu}

ROLL_PATH=${PWD}
export PYTHONPATH="$ROLL_PATH:${PYTHONPATH:-}"

ROLL_OUTPUT_DIR="./runs/geography_counterfactual_distance3_5/$(date +%Y%m%d-%H%M%S)"
ROLL_LOG_DIR="$ROLL_OUTPUT_DIR/logs"
ROLL_RENDER_DIR="$ROLL_OUTPUT_DIR/render"
export ROLL_OUTPUT_DIR
export ROLL_LOG_DIR
export ROLL_RENDER_DIR
mkdir -p "$ROLL_LOG_DIR"

python examples/start_agentic_pipeline.py \
  --config_path "$CONFIG_PATH" \
  --config_name "geography/$CONFIG_NAME" \
  | tee "$ROLL_LOG_DIR/custom_logs.log"
