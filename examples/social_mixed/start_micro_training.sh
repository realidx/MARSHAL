#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export SOCIAL_MICRO_BANK=1 SOCIAL_INTERACTION_BANK=0 SOCIAL_RECIPE=reasoning
export SOCIAL_NORMALIZATION=standard_sequence SOCIAL_KEEP_CHECKPOINTS=4
# 40 * 104 * 1024 is the maximum response-token consumption.
export SOCIAL_MICRO_VARIANT="${SOCIAL_MICRO_VARIANT:-13}"
case "$SOCIAL_MICRO_VARIANT" in
  13) export SOCIAL_TOTAL_TOKENS=4259840;;
  24|24v2) export SOCIAL_TOTAL_TOKENS=3932160;;
  24v2_no_b) export SOCIAL_TOTAL_TOKENS=2621440;;
  *) echo 'Micro variant must be 13, 24, 24v2 or 24v2_no_b' >&2; exit 2;;
esac
unset SOCIAL_PAUSE_AFTER_UPDATES
python -m unittest training.social_mixed.test_micro_training -q
exec bash examples/social_mixed/start_training.sh "${1:-h100-96}" decomposed
