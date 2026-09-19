#!/usr/bin/env bash
# Usage: submit_benac_a_soc.sh h100-96|h200-141 q0|/absolute/HF/model label [smoke|formal]
set -euo pipefail
cd "$(dirname "$0")/../.."
profile="${1:?Choose h100-96 or h200-141}"
model="${2:?Choose q0 or absolute HF model path}"
export BENAC_A_LABEL="${3:?Provide unique model label}"
export BENAC_A_PROTOCOL="${BENAC_A_PROTOCOL:-v2}"
export BENAC_A_STAGE="${4:-smoke}"
export BENAC_A_Q0="${BENAC_A_Q0:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
case "$profile" in h100-96) partition=gpu-long; limit=06:00:00;; h200-141) partition=gpu; limit=03:00:00;; *) exit 2;; esac
case "$BENAC_A_STAGE" in smoke|formal);; *) exit 2;; esac
case "$model" in q0) export BENAC_A_MODEL="$BENAC_A_Q0";; /*) export BENAC_A_MODEL="$model";; *) exit 2;; esac
[[ "$BENAC_A_LABEL" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid label' >&2; exit 2; }
for path in "$BENAC_A_MODEL" "$BENAC_A_Q0"; do
  [[ -f "$path/config.json" ]] || { echo "Missing HF model: $path" >&2; exit 2; }
done
sbatch --job-name="benac-a-${BENAC_A_LABEL}" --partition="$partition" \
  --gres="gpu:${profile}:2" --time="$limit" --export=ALL \
  examples/final_evaluation/sbatch_benac_a_soc.sh
