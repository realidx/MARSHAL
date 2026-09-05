#!/usr/bin/env bash
set -euo pipefail

# v0.28 profile.  This is intentionally separate from
# run_item_game_vllm_server.sh so the older Hermes setup remains a fallback.
MODEL="${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-${MODEL}}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-qwen3}"
PYTHON_BIN="${PYTHON_BIN:-python}"

echo "starting vLLM 0.28 profile model=${MODEL} served_model=${SERVED_MODEL_NAME}"
echo "host=${HOST} port=${PORT} max_model_len=${MAX_MODEL_LEN}"
echo "tool_call_parser=${TOOL_CALL_PARSER} auto_tool_choice=enabled"
echo "native_reasoning=disabled (ItemGame stores application-level reason content)"

exec "${PYTHON_BIN}" -m vllm.entrypoints.cli.main serve "${MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --enable-auto-tool-choice \
  --tool-call-parser "${TOOL_CALL_PARSER}"
