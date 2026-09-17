#!/usr/bin/env bash
# Usage: submit_calbench_soc.sh h100-96|h200-141 q0|marshal|socialr1|/HF/model structures|formal [768|4096]
set -euo pipefail
cd "$(dirname "$0")/../.."
profile="${1:?Choose h100-96 or h200-141}"
model="${2:?Choose model alias or absolute Hugging Face model directory}"
export CALBENCH_SUITE="${3:-structures}"
export CALBENCH_MAX_TOKENS="${4:-4096}"
case "$CALBENCH_SUITE" in structures|formal);; *) echo 'Suite must be structures or formal' >&2; exit 2;; esac
case "$CALBENCH_MAX_TOKENS" in 768|4096);; *) echo 'Budget must be 768 or 4096' >&2; exit 2;; esac
case "$profile" in
  h100-96) partition=gpu-long; gpus=2; limit=06:00:00;;
  h200-141) partition=gpu; gpus=1; limit=03:00:00;;
  *) echo 'Supported: h100-96 (2 GPUs), h200-141 (1 GPU)' >&2; exit 2;;
esac
model_root="${CALBENCH_MODEL_ROOT:-/home/e/e1300530/models}"
case "$model" in
  q0) export CALBENCH_MODEL="$model_root/Qwen3-4B-Instruct-2507"; label=q0;;
  marshal) export CALBENCH_MODEL="$model_root/MARSHAL-Generalist-Qwen3-4B"; label=marshal;;
  socialr1) export CALBENCH_MODEL="$model_root/SocialR1-4B"; label=socialr1;;
  /*) export CALBENCH_MODEL="$model"; label=custom;;
  *) echo 'Use a known alias or absolute HF model directory' >&2; exit 2;;
esac
export CALBENCH_LABEL="${CALBENCH_LABEL:-$label}"
[[ "$CALBENCH_LABEL" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid run label' >&2; exit 2; }
[[ -f "$CALBENCH_MODEL/config.json" ]] || { echo "Missing HF config: $CALBENCH_MODEL" >&2; exit 2; }
[[ -x "${CALBENCH_RUNNER_PYTHON:-$PWD/.venv-calbench/bin/python}" ]] || { echo 'Prepare isolated CalBench venv first' >&2; exit 2; }
sbatch --job-name="calbench-${CALBENCH_LABEL}" --partition="$partition" \
  --gres="gpu:${profile}:${gpus}" --time="$limit" --export=ALL \
  examples/final_evaluation/sbatch_calbench_soc.sh
