#!/usr/bin/env bash
set -euo pipefail
set +x

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
MODEL="${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}}"
BASE_URL="${BENAC_P_VLLM_BASE_URL:-${VLLM_BASE_URL:-http://localhost:8000/v1}}"
OUTPUT_DIR="${BENAC_DIAGNOSE_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_full_diagnose/$(date +%Y%m%d-%H%M%S)}"
export PYTHONPATH="${REPO_ROOT}/third_party/negotiation_benchmark/src:${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "$OUTPUT_DIR"

"$PYTHON_BIN" -m benac_p.diagnose_suite \
  --output-dir "$OUTPUT_DIR" \
  --base-url "$BASE_URL" --model "$MODEL" \
  --n-games "${BENAC_DIAGNOSE_GAMES:-24}" \
  --seed "${BENAC_DIAGNOSE_SEED:-10000}" \
  --workers "${BENAC_DIAGNOSE_WORKERS:-4}" \
  --max-tokens "${BENAC_DIAGNOSE_MAX_TOKENS:-2048}" \
  "$@" | tee -a "$OUTPUT_DIR/run.log"
printf 'Full diagnostic outputs: %s\n' "$OUTPUT_DIR"
