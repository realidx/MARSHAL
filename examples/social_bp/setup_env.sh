#!/usr/bin/env bash
set -euo pipefail
bp_env="${BP_TRAIN_ENV:-$HOME/tmp/marshal-bp-grpo}"
bp_setup_python="${BP_SETUP_PYTHON:-python3.10}"
if [[ -e "$bp_env" ]]; then
  echo "Environment already exists: $bp_env. Inspect it; this script does not modify existing environments." >&2
  exit 1
fi
"$bp_setup_python" -m venv "$bp_env"
"$bp_env/bin/python" -m pip install --upgrade pip
DS_BUILD_OPS=0 "$bp_env/bin/python" -m pip install -r examples/social_bp/requirements.txt
VLLM_USE_V1=0 "$bp_env/bin/python" -m training.b_sft.check_bp_training_env
