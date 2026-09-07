#!/usr/bin/env bash
set -euo pipefail
set +x
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/third_party/negotiation_benchmark/src:${REPO_ROOT}:${PYTHONPATH:-}"
OUTPUT_DIR="${BENAC_BELIEF_AUDIT_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_belief_interface_audit/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUTPUT_DIR"
"${PYTHON_BIN:-python}" -m benac_p.belief_interface_audit \
  --output-dir "$OUTPUT_DIR" \
  --base-url "${BENAC_P_VLLM_BASE_URL:-${VLLM_BASE_URL:-http://localhost:8000/v1}}" \
  --model "${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}}" \
  "$@" | tee -a "$OUTPUT_DIR/run.log"
