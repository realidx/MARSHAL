#!/usr/bin/env bash
# Four-arm social reasoning; legacy BP remains available explicitly.
set -euo pipefail
cd "$(dirname "$0")/../.."
PROFILE="${1:-h100-96}"
ARM="${2:?Usage: start_training.sh <GPU profile> <selfplay|bp|b_only|p_only|outcome|conditioned|decomposed|four|sp_o|both>}"
case "$ARM" in selfplay|bp|b_only|p_only|outcome|conditioned|decomposed|four|sp_o|both);; *) echo 'Unknown social training arm' >&2; exit 2;; esac
if [[ "$ARM" == four || "$ARM" == sp_o ]]; then export SOCIAL_RECIPE=reasoning; fi
case "$PROFILE" in h100-47|h100-96|h200-141);; *) echo 'Unknown GPU profile' >&2; exit 2;; esac
export CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
export CONDA_ENV="${CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"
source "$CONDA_HOME/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MODEL="${SOCIAL_MODEL:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
unset VLLM_USE_V1  # vLLM 0.28 uses V1; this retired variable cannot select V0.
export VLLM_TOOL_CALL_PARSER=hermes TOKENIZERS_PARALLELISM=false
export VLLM_BATCH_INVARIANT=0
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export SOCIAL_GPU_PROFILE="$PROFILE" SOCIAL_ARM="$ARM"
export SOCIAL_SEED="${SOCIAL_SEED:-42}"
export SOCIAL_TOTAL_TOKENS="${SOCIAL_TOTAL_TOKENS:-6553600}" SOCIAL_TOKENS_PER_UPDATE="${SOCIAL_TOKENS_PER_UPDATE:-65536}" SOCIAL_KEEP_CHECKPOINTS="${SOCIAL_KEEP_CHECKPOINTS:-1}"
export SOCIAL_DATA_DIR="${SOCIAL_DATA_DIR:-$PWD/examples/social_mixed/data_reasoning_v6}"
unset SOCIAL_RESUME SOCIAL_SOURCE_COMMIT SOCIAL_DIAGNOSE_PROBABILITIES
[[ -f "$SOCIAL_MODEL/config.json" ]] || { echo 'Missing local model' >&2; exit 2; }
mkdir -p submission
SOCIAL_SUBMISSION_DIR="$(mktemp -d "$PWD/submission/reasoning-four-arm-${PROFILE}-XXXXXX")"
python -c 'import json,sys; from pathlib import Path; from training.social_mixed.run import verify_bundle; Path(sys.argv[1]).write_text(json.dumps(verify_bundle(),indent=2)+"\n")' "$SOCIAL_SUBMISSION_DIR/source.json"
python -m training.social_mixed.preflight --output "$SOCIAL_SUBMISSION_DIR/data-preflight.json"
if [[ "${SOCIAL_RECIPE:-reasoning}" == reasoning && ( "$ARM" == four || "$ARM" == sp_o || "$ARM" == both || "$ARM" == selfplay || "$ARM" == outcome || "$ARM" == conditioned || "$ARM" == decomposed ) ]]; then
  python -m training.social_mixed.reasoning_preflight --tokenizer "$SOCIAL_MODEL" --output "$SOCIAL_SUBMISSION_DIR/reasoning-preflight.json"
fi
if [[ "$ARM" == sp_o ]]; then
  python -m training.social_mixed.sp_o_preflight --tokenizer "$SOCIAL_MODEL" --output "$SOCIAL_SUBMISSION_DIR/sp-o-preflight.json"
fi
if [[ "${SOCIAL_INTERACTION_BANK:-0}" == 1 ]]; then
  python -m unittest training.social_mixed.test_interaction_contract training.social_mixed.test_interaction_entry -q
  python -m training.social_mixed.interaction_preflight --tokenizer "$SOCIAL_MODEL" --output "$SOCIAL_SUBMISSION_DIR/interaction-preflight.json"
fi
echo 'Binary/linear-only data verified; checking hardware profiles and training configurations'
if ! python -m unittest training.social_mixed.test_configuration -q > "$SOCIAL_SUBMISSION_DIR/configuration.log" 2>&1; then
  cat "$SOCIAL_SUBMISSION_DIR/configuration.log"
  exit 1
fi
echo "Checking existing SoC dependencies; details in $SOCIAL_SUBMISSION_DIR/dependencies.log"
if ! python -u -m training.social_mixed.check_dependencies > "$SOCIAL_SUBMISSION_DIR/dependencies.json" 2> "$SOCIAL_SUBMISSION_DIR/dependencies.log"; then
  cat "$SOCIAL_SUBMISSION_DIR/dependencies.json"
  tail -n 40 "$SOCIAL_SUBMISSION_DIR/dependencies.log"
  exit 1
fi
# A receipt is saved after each successful submission, including partial success.
ARMS=("$ARM")
[[ "$ARM" == both ]] && ARMS=(bp selfplay)
[[ "$ARM" == sp_o ]] && ARMS=(selfplay outcome)
[[ "$ARM" == four ]] && ARMS=(selfplay outcome conditioned decomposed)
export SOCIAL_SUBMIT_PARSABLE=1
for SOCIAL_SELECTED_ARM in "${ARMS[@]}"; do
  SOCIAL_JOB_ID="$(bash examples/social_mixed/submit_soc.sh "$PROFILE" "$SOCIAL_SELECTED_ARM")"
  printf '%s\n' "$SOCIAL_JOB_ID" > "$SOCIAL_SUBMISSION_DIR/$SOCIAL_SELECTED_ARM.jobid"
  python - "$SOCIAL_SUBMISSION_DIR" "$SOCIAL_SELECTED_ARM" "$SOCIAL_JOB_ID" <<'PYRECEIPT'
import json,os,sys
from pathlib import Path
from training.social_mixed.run import data_manifest_sha256
folder,arm,job=sys.argv[1:]
record=dict(job_id=job,arm=arm,runtime=os.getcwd(),profile=os.environ['SOCIAL_GPU_PROFILE'],
            seed=int(os.environ['SOCIAL_SEED']),total_tokens=int(os.environ['SOCIAL_TOTAL_TOKENS']),
            tokens_per_update=int(os.environ['SOCIAL_TOKENS_PER_UPDATE']),
            keep_checkpoints=int(os.environ['SOCIAL_KEEP_CHECKPOINTS']),
            data_manifest_sha256=data_manifest_sha256(),fresh_start=True,
            dataset=__import__('training.social_mixed.core',fromlist=['DATA']).DATA.name,allowed_completion_modes=['binary','linear'],
            source_version=json.loads((Path(folder)/'source.json').read_text()))
if arm in ('selfplay','outcome','conditioned','decomposed') and os.environ.get('SOCIAL_RECIPE','reasoning')=='reasoning':
    from training.social_mixed.reasoning_bank import PATH,sha
    record.update(recipe='reasoning',normalization=os.environ.get('SOCIAL_NORMALIZATION','standard_sequence'),paired_bank_sha256=sha((PATH/'manifest.json').read_bytes()))
if os.environ.get('SOCIAL_INTERACTION_BANK')=='1':
    from training.social_mixed.interaction_bank import load as interaction_load
    record.update(interaction_bank=True,interaction_bank_sha256=interaction_load()[1])
(Path(folder)/(arm+'.json')).write_text(json.dumps(record,indent=2)+'\n')
PYRECEIPT
  printf 'SUBMITTED arm=%s job=%s receipt=%s\n' "$SOCIAL_SELECTED_ARM" "$SOCIAL_JOB_ID" "$SOCIAL_SUBMISSION_DIR/$SOCIAL_SELECTED_ARM.json"
done
printf 'RUNTIME=%s\n' "$PWD"
