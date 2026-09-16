#!/usr/bin/env bash
# One diagnostic job, using the same initialization and GPU profile as training.
set -euo pipefail
cd "$(dirname "$0")/../.."
export SOCIAL_DIAGNOSE_PROBABILITIES=1
bash examples/social_mixed/start_training.sh "${1:-h100-96}" mixed
