#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export BENAC_DIAGNOSE_OUTPUT_DIR="${BENAC_DIAGNOSE_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_native_endgame/dependency-$(date +%Y%m%d-%H%M%S)}"
bash "${REPO_ROOT}/examples/benac_p/run_full_diagnose.sh" \
  --dependency-only --seed 40000 --candidate-seeds 64 \
  --n-goals 8 --max-remaining-turns 4 --min-games-per-condition 3 "$@"
