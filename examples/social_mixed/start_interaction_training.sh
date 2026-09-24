#!/usr/bin/env bash
set -euo pipefail
# Fresh stage, existing hardware launcher. No job is submitted by installing this file.
PROFILE="${1:-h100-96}"
ARM="${2:-decomposed}"
case "$ARM" in outcome|conditioned|decomposed);; *) echo 'Use outcome, conditioned or decomposed' >&2; exit 2;; esac
export SOCIAL_INTERACTION_BANK=1 SOCIAL_RECIPE=reasoning
export SOCIAL_NORMALIZATION=standard_sequence SOCIAL_KEEP_CHECKPOINTS=1
exec bash examples/social_mixed/start_training.sh "$PROFILE" "$ARM"
