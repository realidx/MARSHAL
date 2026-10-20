#!/usr/bin/env bash
#SBATCH --job-name=slice-oracle-cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=oracle-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src${PYTHONPATH:+:$PYTHONPATH}"

oracle_output="${ORACLE_OUTPUT:-remote_runs/base}"
oracle_profile="${ORACLE_PROFILE:-base}"
oracle_workers="${ORACLE_WORKERS:-${SLURM_CPUS_PER_TASK:-0}}"
oracle_args=(--output "$oracle_output" --profile "$oracle_profile" --workers "$oracle_workers")
if [[ -f "$oracle_output/pipeline_snapshot.json" ]]; then
  oracle_args+=(--resume)
fi
if [[ -n "${ORACLE_FROM_RUN:-}" ]]; then
  oracle_args+=(--from-run "$ORACLE_FROM_RUN")
fi
python -u -m new.strategic_game_v1_20261021.remote_solver run "${oracle_args[@]}"
python -m new.strategic_game_v1_20261021.remote_solver audit --output "$oracle_output" --hash-only
