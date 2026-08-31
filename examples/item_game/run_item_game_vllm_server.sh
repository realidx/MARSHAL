#!/usr/bin/env bash
set -euo pipefail

# Qwen3's advertised context window can be much larger than an A100-40 can
# reserve for KV cache. Keep the ItemGame server's safe default explicit.
MODEL="${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-${MODEL}}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"

echo "starting vLLM model=${MODEL} served_model=${SERVED_MODEL_NAME}"
echo "host=${HOST} port=${PORT} max_model_len=${MAX_MODEL_LEN} native_reasoning=disabled"

exec vllm serve "${MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --guided-decoding-backend xgrammar \
  --max-model-len "${MAX_MODEL_LEN}"
