#!/usr/bin/env bash
#SBATCH --job-name=three-player-H2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=three-player-%j.out
set -euo pipefail
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python -m new.three_player_complexity_v1_20261023.remote doctor
STUDY_ARM=${STUDY_ARM:-H2}
STUDY_OUTPUT=${STUDY_OUTPUT:-remote_runs/${STUDY_ARM}}
STUDY_WORKERS=${STUDY_WORKERS:-2}
STUDY_RESUME=${STUDY_RESUME:-0}
mkdir -p remote_runs
STUDY_FLAGS=()
if [[ "$STUDY_RESUME" == "1" ]]; then STUDY_FLAGS+=(--resume); fi
python -u -m new.three_player_complexity_v1_20261023.remote run \
  --jobs "data/${STUDY_ARM}.jsonl" --output "$STUDY_OUTPUT" \
  --workers "$STUDY_WORKERS" "${STUDY_FLAGS[@]}"
