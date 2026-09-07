#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export BENAC_DIAGNOSE_OUTPUT_DIR="${BENAC_DIAGNOSE_OUTPUT_DIR:-${REPO_ROOT}/runs/benac_native_endgame/functional-dependency-$(date +%Y%m%d-%H%M%S)}"
FIXTURE_ARGS=(--fixtures "${REPO_ROOT}/examples/benac_p/fixtures/functional_dependency.json")
for arg in "$@"; do
  case "$arg" in
    --generate|--fixtures|--fixtures=*) FIXTURE_ARGS=() ;;
  esac
done
bash "${REPO_ROOT}/examples/benac_p/run_full_diagnose.sh" \
  --functional-dependency --seed 41000 --candidate-seeds 64 \
  --n-goals 6 --max-remaining-turns 3 --max-query-sets 2 \
  --min-games-per-condition 3 --preflight-policy protocol "${FIXTURE_ARGS[@]}" "$@"
