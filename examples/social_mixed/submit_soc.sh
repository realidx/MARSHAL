#!/usr/bin/env bash
# Usage: bash examples/social_mixed/submit_soc.sh h200-141 mixed [checkpoint]
set -euo pipefail
cd "$(dirname "$0")/../.."
PROFILE="${1:?Choose h100-47, h100-96 or h200-141}"
ARM="${2:-mixed}"
case "$ARM" in mixed|selfplay);; *) echo 'ARM must be mixed or selfplay' >&2; exit 2;; esac
GPUS=2
case "$PROFILE" in
  h100-47)
    AVAILABLE="$(sinfo -h -p gpu-long -o '%G')"
    case "$AVAILABLE" in
      *gpu:h100-47:*) PARTITION=gpu-long; LIMIT=3-00:00:00;;
      *) PARTITION=gpu; LIMIT=03:00:00;;
    esac;;
  h100-96) PARTITION=gpu-long; LIMIT=3-00:00:00;;
  h200-141) GPUS=1; PARTITION=gpu; LIMIT=03:00:00;;
  *) echo 'Unknown GPU profile' >&2; exit 2;;
esac
if [[ -n "${SOCIAL_SUBMIT_PARTITION:-}" ]]; then
  case "$SOCIAL_SUBMIT_PARTITION" in
    gpu|gpu-long) PARTITION="$SOCIAL_SUBMIT_PARTITION";;
    *) echo 'SOCIAL_SUBMIT_PARTITION must be gpu or gpu-long' >&2; exit 2;;
  esac
  [[ "$PARTITION" == gpu ]] && LIMIT=03:00:00
fi
export SOCIAL_GPU_PROFILE="$PROFILE" SOCIAL_ARM="$ARM"
export SOCIAL_SEED="${SOCIAL_SEED:-42}"
if [[ -n "${3:-}" ]]; then
  SOCIAL_RESUME="$(cd "$3" && pwd)"
  [[ -f "$SOCIAL_RESUME/COMPLETE.json" ]] || { echo 'Incomplete resume checkpoint' >&2; exit 2; }
  export SOCIAL_RESUME
else
  unset SOCIAL_RESUME
fi
# Freeze the submitted Git revision; checked again before model loading.
if [[ -e .git ]]; then
  export SOCIAL_SOURCE_COMMIT="$(git rev-parse HEAD)"
else
  unset SOCIAL_SOURCE_COMMIT
fi
# Single H200; dual H100.
sbatch --job-name="social-${ARM}-${PROFILE}" --partition="$PARTITION" \
 --gres="gpu:${PROFILE}:${GPUS}" --time="$LIMIT" --export=ALL \
 examples/social_mixed/sbatch_train.sh
