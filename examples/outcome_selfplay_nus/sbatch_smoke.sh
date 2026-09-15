#!/usr/bin/env bash
#SBATCH --job-name=outcome-rollout-smoke
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=0
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
echo "commit=$(git rev-parse HEAD)"
bash examples/outcome_selfplay_nus/run_smoke.sh
