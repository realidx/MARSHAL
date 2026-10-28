#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs
python -m new.three_player_complexity_v1_20261023.remote doctor
python -u -m new.three_player_complexity_v1_20261023.remote run --jobs data/H2.jsonl --output remote_runs/H2 --workers "${STUDY_WORKERS:-1}" "$@"
