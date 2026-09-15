#!/usr/bin/env bash
#SBATCH --job-name=bp-grpo-pilot
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:6
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=0
#SBATCH --time=08:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
bash examples/social_bp/run_train.sh
