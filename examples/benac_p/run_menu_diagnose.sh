#!/usr/bin/env bash
set -euo pipefail
set +x

# Run from any working directory, using the same HTTP Qwen deployment as ItemGame.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
MODEL="${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}}"
BASE_URL="${BENAC_P_VLLM_BASE_URL:-${VLLM_BASE_URL:-http://localhost:8000/v1}}"
OUTPUT_DIR="${BENAC_DIAGNOSE_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_menu_diagnose/$(date +%Y%m%d-%H%M%S)}"
export PYTHONPATH="${REPO_ROOT}/third_party/negotiation_benchmark/src:${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "$OUTPUT_DIR"

ARGS=(--output-dir "$OUTPUT_DIR")
if [[ "${1:-}" == "--export-only" ]]; then
  shift
else
  ARGS+=(--base-url "$BASE_URL" --model "$MODEL" --max-tokens "${BENAC_DIAGNOSE_MAX_TOKENS:-2048}")
fi
"$PYTHON_BIN" -m benac_p.menu_diagnose "${ARGS[@]}" "$@" | tee "$OUTPUT_DIR/run.log"
printf 'Diagnostic artifacts: %s\n' "$OUTPUT_DIR"
