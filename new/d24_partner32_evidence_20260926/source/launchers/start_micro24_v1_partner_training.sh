#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export SOCIAL_MICRO_VARIANT=24v1_partner
exec bash examples/social_mixed/start_micro_training.sh "${1:-h200-141}"
