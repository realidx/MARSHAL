#!/usr/bin/env bash
set -euo pipefail
set +x
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/third_party/negotiation_benchmark/src:${REPO_ROOT}:${PYTHONPATH:-}"
OUTPUT_DIR="${BENAC_CALIBRATION_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_reasoning_calibration/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUTPUT_DIR"
"${PYTHON_BIN:-python}" -m benac_p.reasoning_calibration \
  --output-dir "$OUTPUT_DIR" \
  --base-url "${BENAC_P_VLLM_BASE_URL:-${VLLM_BASE_URL:-http://localhost:8000/v1}}" \
  --model "${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}}" \
  --workers "${BENAC_DIAGNOSE_WORKERS:-4}" \
  "$@" | tee -a "$OUTPUT_DIR/run.log"
