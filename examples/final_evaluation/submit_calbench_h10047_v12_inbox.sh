#!/usr/bin/env bash
# Submit one registered v12_inbox belief-MS CalBench24 condition on the archived H100-47 profile.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ $# -ne 2 ]]; then
  echo "usage: bash $0 MODEL_DIR LABEL" >&2
  exit 2
fi

model=$1
label=$2
scaffold=belief-ms
prompt_version=general-belief-ms-v12-inbox
max_tokens=4096
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid run label' >&2; exit 2; }
[[ -f "$model/config.json" ]] || { echo "Missing HF config: $model" >&2; exit 2; }
compgen -G "$model/*.safetensors" >/dev/null || { echo "Missing safetensors weights: $model" >&2; exit 2; }

export CALBENCH_MODEL="$model"
export CALBENCH_SCAFFOLD="$scaffold"
export CALBENCH_PROMPT_VERSION="$prompt_version"
export CALBENCH_LABEL="$label"
export CALBENCH_SUITE=stream
export CALBENCH_MAX_TOKENS="$max_tokens"
export CALBENCH_MAX_MODEL_LEN=32768
export CALBENCH_MAX_NUM_SEQS=32
export CALBENCH_PARALLEL_GAMES=8
export CALBENCH_DISABLE_CHUNKED_PREFILL=1
export CALBENCH_DISABLE_CASCADE_ATTN=1
export VLLM_BATCH_INVARIANT=1

sbatch --parsable --job-name="cb24-${label}" --partition=gpu \
  --gres=gpu:h100-47:1 --time=03:00:00 --cpus-per-task=8 --mem=64G \
  --export=ALL examples/final_evaluation/sbatch_calbench_h10047_v12_inbox.sh
