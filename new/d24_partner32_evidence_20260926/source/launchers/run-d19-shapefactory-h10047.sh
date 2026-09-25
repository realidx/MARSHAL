#!/usr/bin/env bash
# Runs the unchanged frozen ShapeFactory v3 launcher after a verified HF export.
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-47:1
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --output=/home/e/e1300530/tmp/d19-shapefactory-%j.out
#SBATCH --error=/home/e/e1300530/tmp/d19-shapefactory-%j.err
set -euo pipefail
[[ $# -eq 2 ]] || { echo 'usage: script LABEL MODEL_DIR' >&2; exit 2; }
label=$1
model=$2
[[ -f "$model/EXPORT_VERIFIED.json" && -f "$model/model.safetensors" ]]
checkpoint_id="$(jq -r '.weights_sha256' "$model/EXPORT_VERIFIED.json")"
[[ "$checkpoint_id" =~ ^[0-9a-f]{64}$ ]]
exec bash /home/e/e1300530/tmp/run-collabsim-frozen-v3-h200.sh "$label" "$model" "$checkpoint_id"
