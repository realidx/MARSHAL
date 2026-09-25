#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
source "${CONDA_HOME:-/home/e/e1300530/miniconda3}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MICRO_BANK=1 SOCIAL_INTERACTION_BANK=0 SOCIAL_RECIPE=reasoning
export SOCIAL_NORMALIZATION=standard_sequence SOCIAL_KEEP_CHECKPOINTS="${SOCIAL_KEEP_CHECKPOINTS:-4}"
# Per-variant response-token caps are safety upper bounds, not target doses.
export SOCIAL_MICRO_VARIANT="${SOCIAL_MICRO_VARIANT:-13}"
case "$SOCIAL_MICRO_VARIANT" in
  13) export SOCIAL_TOTAL_TOKENS=4259840;;
  24|24v2|24v1_d|24v1_partner_c) export SOCIAL_TOTAL_TOKENS=3932160;;
  24v1_partner_o) export SOCIAL_TOTAL_TOKENS=1966080;;
  24v1_partner) export SOCIAL_TOTAL_TOKENS=5242880;;
  24v2_no_b|24v1_c) export SOCIAL_TOTAL_TOKENS=2621440;;
  24v1_o) export SOCIAL_TOTAL_TOKENS=1310720;;
  *) echo 'Unknown micro variant' >&2; exit 2;;
esac
unset SOCIAL_PAUSE_AFTER_UPDATES
python -m unittest training.social_mixed.test_micro_training -q
exec bash examples/social_mixed/start_training.sh "${1:-h100-96}" decomposed
