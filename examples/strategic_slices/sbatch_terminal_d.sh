#!/usr/bin/env bash
#SBATCH --job-name=slices-base-D
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR:?Submit from the repository root}}"
bash examples/strategic_slices/run_terminal_d.sh "$@"
