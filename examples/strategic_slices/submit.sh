#!/usr/bin/env bash
# submit.sh <h100-96|h100-47|h200-141> <slices|selfplay> <dataset> [checkpoint]
set -euo pipefail
cd "$(dirname "$0")/../.."
PROFILE="${1:?GPU profile required}"
ARM="${2:?slices or selfplay required}"
case "$ARM" in slices|selfplay);; *) exit 2;; esac
DATA="$(cd "${3:?Frozen dataset directory required}" && pwd)"
[[ -f "$DATA/COMPLETE.json" ]] || { echo 'Dataset is incomplete' >&2; exit 2; }
case "$PROFILE" in
  h100-96) PARTITION=gpu-long; LIMIT=3-00:00:00; GPUS=2;;
  h100-47) PARTITION=gpu; LIMIT=03:00:00; GPUS=2;;
  h200-141) PARTITION=gpu; LIMIT=03:00:00; GPUS=1;;
  *) echo 'Unknown GPU profile' >&2; exit 2;;
esac
export STRATEGIC_DATA="$DATA" STRATEGIC_ARM="$ARM" SOCIAL_GPU_PROFILE="$PROFILE"
if [[ -n "${4:-}" ]]; then
  STRATEGIC_RESUME="$(cd "$4" && pwd)"
  [[ -f "$STRATEGIC_RESUME/COMPLETE.json" ]] || { echo 'Incomplete checkpoint' >&2; exit 2; }
  export STRATEGIC_RESUME
else
  unset STRATEGIC_RESUME
fi
sbatch --job-name="slices-${ARM}-${PROFILE}" --partition="$PARTITION" \
  --gres="gpu:${PROFILE}:${GPUS}" --time="$LIMIT" --export=ALL examples/strategic_slices/sbatch_train.sh
