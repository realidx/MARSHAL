#!/usr/bin/env bash
#SBATCH --job-name=bp-heldout-test
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2
bp_python="${BP_TRAIN_PYTHON:-$HOME/tmp/marshal-bp-grpo/bin/python}"
"$bp_python" -m training.b_sft.evaluate_bp_pilot --model "${BP_TEST_MODEL:?Set BP_TEST_MODEL to the selected best_model directory}" --out "${BP_TEST_OUT:-$PWD/runs/bp_grpo_test/${SLURM_JOB_ID}}"
