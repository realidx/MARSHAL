#!/usr/bin/env bash
#SBATCH --job-name=native800-D
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR:?Submit from repository or extracted bundle root}}"
# Activate the existing working vLLM environment BEFORE sbatch; it is inherited.
# Supply partition/account/GPU type through sbatch flags for your server.
bash examples/strategic_slices/run_native800_d_v1_1.sh "$@"
