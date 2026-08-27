#!/bin/bash
set -euo pipefail
: "${EVAL_MODEL_DIR:?Set EVAL_MODEL_DIR to the local model directory}"
ray stop --force || true
CONFIG_PATH=$(basename "$(dirname "$0")")
ROLL_PATH=${PWD}
export PYTHONPATH="$ROLL_PATH:${PYTHONPATH:-}"
ROLL_OUTPUT_DIR="./runs/pivotal_query_source_aware/$(date +%Y%m%d-%H%M%S)"
export ROLL_OUTPUT_DIR
export ROLL_LOG_DIR="$ROLL_OUTPUT_DIR/logs"
export ROLL_RENDER_DIR="$ROLL_OUTPUT_DIR/render"
mkdir -p "$ROLL_LOG_DIR"
python examples/start_agentic_rollout_pipeline.py --config_path "$CONFIG_PATH" --config_name agentic_rollout_pivotal_query_source_aware | tee "$ROLL_LOG_DIR/custom_logs.log"
