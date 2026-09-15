#!/usr/bin/env bash
# Activate the existing SoC environment, verify, then submit exactly one selected arm.
set -euo pipefail
cd "$(dirname "$0")/../.."
PROFILE="${1:-h100-96}"
ARM="${2:?Usage: start_training.sh <GPU profile> <mixed|selfplay>}"
case "$ARM" in mixed|selfplay);; *) echo 'ARM must be mixed or selfplay' >&2; exit 2;; esac
case "$PROFILE" in h100-47|h100-96|h200-141);; *) echo 'Unknown GPU profile' >&2; exit 2;; esac
export CONDA_HOME=/home/e/e1300530/miniconda3
export CONDA_ENV=/home/e/e1300530/tmp/marshal-vllm09
source "$CONDA_HOME/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MODEL=/home/e/e1300530/models/Qwen3-4B-Instruct-2507
export VLLM_USE_V1=0 VLLM_TOOL_CALL_PARSER=hermes TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export SOCIAL_GPU_PROFILE="$PROFILE" SOCIAL_ARM="$ARM" SOCIAL_SEED=42
export SOCIAL_TOTAL_TOKENS=6553600 SOCIAL_TOKENS_PER_UPDATE=65536 SOCIAL_KEEP_CHECKPOINTS=2
unset SOCIAL_RESUME
[[ -f "$SOCIAL_MODEL/config.json" ]] || { echo 'Missing local model' >&2; exit 2; }
mkdir -p submission
python -c 'from training.social_mixed.run import verify_bundle; from training.social_mixed.core import load_data; verify_bundle(); load_data()'
echo 'Checking all three hardware profiles and both experiment configurations'
if ! python -m unittest training.social_mixed.test_configuration -q > submission/configuration.log 2>&1; then
  cat submission/configuration.log
  exit 1
fi
echo 'Checking existing SoC dependencies; details in submission/dependencies.log'
if ! python -u -m training.social_mixed.check_dependencies > submission/dependencies.json 2> submission/dependencies.log; then
  cat submission/dependencies.json
  tail -n 40 submission/dependencies.log
  exit 1
fi
bash examples/social_mixed/submit_soc.sh "$PROFILE" "$ARM" | tee "submission/$ARM.txt"
printf 'RUNTIME=%s\n' "$PWD"
