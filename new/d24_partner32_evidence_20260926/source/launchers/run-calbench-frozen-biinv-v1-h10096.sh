#!/usr/bin/env bash
# Frozen CalBench stream profile, validated by jobs 868929 and 868930.
#SBATCH --job-name=cb-biinv-v1
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-96:1
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/e/e1300530/tmp/calbench-biinv-v1-%j.out
#SBATCH --error=/home/e/e1300530/tmp/calbench-biinv-v1-%j.err

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: sbatch $0 MODEL_DIR LABEL" >&2
  exit 2
fi
model=$1
label=$2
repo=/home/e/e1300530/tmp/MARSHAL-calbench-stream-20260920
env_dir=/home/e/e1300530/tmp/marshal-vllm09
runner=/home/e/e1300530/tmp/MARSHAL-calbench-20260918/.venv-calbench/bin/python

[[ -f "$model/config.json" && -f "$model/model.safetensors" && -f "$model/tokenizer.json" ]]
[[ "$label" =~ ^[a-zA-Z0-9._-]+$ ]]

cd "$repo"
source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate "$env_dir"
export PYTHONPATH="$repo:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
nvcc_path="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
site_dir="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

: "${CUDA_VISIBLE_DEVICES:?Slurm must expose one assigned GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]
"$runner" -c 'from examples.final_evaluation.calbench_local import verify_source; verify_source()'
python - <<'PY'
import os, torch
assert os.environ.get('VLLM_BATCH_INVARIANT') == '1'
assert torch.cuda.is_available() and torch.cuda.device_count() == 1
print('FROZEN_PROFILE=calbench-stream-batch-invariant-v1')
print('VLLM_BATCH_INVARIANT=', os.environ['VLLM_BATCH_INVARIANT'])
print('Visible GPU:', torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory)
PY

port=$((20000 + SLURM_JOB_ID % 10000))
out="$repo/runs/calbench_soc/${label}-biinv-v1-stream-${SLURM_JOB_ID}"
python -u -m examples.final_evaluation.launch_calbench_local \
  --runtime soc --suite stream --model "$model" \
  --max-tokens 4096 --runner-python "$runner" \
  --ports "$port" --parallel-games 8 --max-num-seqs 32 \
  --disable-chunked-prefill --disable-cascade-attn \
  --output "$out"
