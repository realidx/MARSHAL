#!/usr/bin/env bash
#SBATCH --job-name=diag-v6s-biinv
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-47:1
#SBATCH --time=00:15:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/e/e1300530/tmp/diag-v6s-biinv-%j.out
#SBATCH --error=/home/e/e1300530/tmp/diag-v6s-biinv-%j.err

set -euo pipefail
if [[ $# -ne 3 ]]; then
  echo "usage: sbatch $0 MODEL_DIR LABEL CHECKPOINT_SHA256" >&2
  exit 2
fi
model_dir=$1
label=$2
checkpoint_hash=$3
repo=/home/e/e1300530/tmp/MARSHAL-benac-results-push
env_dir=/home/e/e1300530/tmp/marshal-vllm09
expected_commit=6467c50f6e0f9a4216c0b6527914aab0ebefff66
served_model="diagnostic-${label}"

cd "$repo"
[[ "$(git rev-parse HEAD)" == "$expected_commit" ]]
git diff --quiet
git diff --cached --quiet
[[ -f "$model_dir/config.json" && -f "$model_dir/model.safetensors" && -f "$model_dir/tokenizer.json" ]]
[[ "$label" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "$checkpoint_hash" =~ ^[0-9a-f]{64}$ ]]
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose one assigned GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]

source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate "$env_dir"
export PYTHONPATH="$repo:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH OPENAI_API_KEY
nvcc_path="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
site_dir="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

out="$repo/runs/diagnostic/${label}-v6s-biinv-v1-${SLURM_JOB_ID}"
mkdir -p "$out"
port=$((23000 + SLURM_JOB_ID % 7000))
printf '%s\n' \
  'profile=diagnostic-v6-strengthened-batch-invariant-v1' \
  'VLLM_BATCH_INVARIANT=1' \
  'tensor_parallel_size=1' \
  'max_num_seqs=32' \
  'concurrency_per_endpoint=8' \
  'temperature=0' \
  'prefix_caching=true' \
  'chunked_prefill=false' \
  'cascade_attention=false' \
  'speculative_decoding=false' \
  'enforce_eager=true' \
  "checkpoint_hash=$checkpoint_hash" > "$out/FROZEN_PROFILE.txt"

setsid python -u -m vllm.entrypoints.openai.api_server \
  --model "$model_dir" --served-model-name "$served_model" \
  --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 \
  --dtype bfloat16 --max-model-len 32768 --max-num-seqs 32 \
  --gpu-memory-utilization 0.65 --enable-prefix-caching \
  --no-enable-chunked-prefill --disable-cascade-attn --enforce-eager \
  --generation-config vllm \
  --enable-auto-tool-choice --tool-call-parser hermes \
  > "$out/server.log" 2>&1 &
server_pid=$!

cleanup() {
  if kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM -- "-$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT TERM INT

python - "$port" "$server_pid" <<'PY'
import json, os, sys, time
from urllib.request import urlopen
assert os.environ.get('VLLM_BATCH_INVARIANT') == '1'
port, pid = int(sys.argv[1]), int(sys.argv[2])
started = time.monotonic()
while True:
    try:
        with urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2) as response:
            json.load(response)
        break
    except OSError:
        try: os.kill(pid, 0)
        except OSError: raise RuntimeError('vLLM server exited during startup')
        if time.monotonic() - started > 600:
            raise TimeoutError('vLLM startup exceeded 600 seconds')
        time.sleep(2)
PY

grep -F "enable_prefix_caching=True" "$out/server.log"
grep -F "enable_chunked_prefill=False" "$out/server.log"

python -u new/diagnostic_v6/experiment.py \
  --base-url "http://127.0.0.1:$port/v1" --model "$served_model" \
  --output "$out/structure_v6" --repeats 3 --max-tokens 4096 \
  --temperature 0 --top-p 1 --top-k -1 \
  --concurrency-per-endpoint 8 --seed 42 --timeout 180 \
  --checkpoint-hash "$checkpoint_hash"

printf '0\n' > "$out/EXIT_CODE"
