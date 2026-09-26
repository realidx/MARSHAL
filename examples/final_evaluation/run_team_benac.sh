#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# Requires an already running batch-invariant OpenAI-compatible vLLM service.
python -m examples.final_evaluation.team_benac \
  --base-url "${1:?base URL, e.g. http://localhost:8000/v1}" \
  --model "${2:?served model name}" \
  --checkpoint-hash "${3:?verified checkpoint hash}" \
  --output "${4:?new output directory}" \
  --suite "${TEAM_SUITE:-examples/final_evaluation/team_benac_v1}" \
  --parallel-games "${TEAM_PARALLEL_GAMES:-4}" --batch-invariant-confirmed
