#!/usr/bin/env bash
set -euo pipefail

# Run only inference/protocol smoke tests.  This script does not launch the
# model and does not run the ItemGame self-play suite.
MODEL="${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
BASE_URL="${VLLM_BASE_URL:-http://localhost:8000/v1}"
API_KEY="${VLLM_API_KEY:-EMPTY}"
PARSER="${VLLM_TOOL_CALL_PARSER:-qwen3}"
EXPECTED_VERSION="${VLLM_EXPECTED_VERSION:-0.28.0}"
CASES="${VLLM_SMOKE_CASES:-100}"
MAX_TOKENS="${VLLM_SMOKE_MAX_TOKENS:-256}"
READY_TIMEOUT="${VLLM_READY_TIMEOUT:-600}"
READY_INTERVAL="${VLLM_READY_INTERVAL:-5}"
PYTHON_BIN="${PYTHON_BIN:-python}"

run_test() {
  local label="$1"
  shift
  echo "=== ${label} ==="
  "${PYTHON_BIN}" examples/item_game/smoke_test_vllm_tool_calling.py \
    --model "${MODEL}" \
    --base-url "${BASE_URL}" \
    --api-key "${API_KEY}" \
    --cases "${CASES}" \
    --max-tokens "${MAX_TOKENS}" \
    --tool-call-parser "${PARSER}" \
    --parallel-tool-calls false \
    --expected-vllm-version "${EXPECTED_VERSION}" \
    --ready-timeout "${READY_TIMEOUT}" \
    --ready-interval "${READY_INTERVAL}" \
    "$@"
}

# 1. Normal automatic tool selection over 100 trivial intents.
STATUS=0
run_test "auto / all trivial cases" --tool-choice auto --case-set all || STATUS=1

# 2. Required selection, including typed-argument cases that
# previously exercised vLLM's Invalid JSON path.
run_test "required / previous Invalid JSON coverage" --tool-choice required --case-set all || STATUS=1

# 3. Explicit no-op path under auto.  No tool call is the PASS path.
run_test "auto / no-op PASS" --tool-choice auto --case-set pass-only || STATUS=1

if [[ "${STATUS}" != "0" ]]; then
  echo "vLLM 0.28 tool-calling smoke matrix FAILED" >&2
  exit "${STATUS}"
fi
echo "vLLM 0.28 tool-calling smoke matrix passed"
