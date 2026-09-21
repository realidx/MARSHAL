#!/usr/bin/env bash
# Q0 O-only trainability gate under the frozen batch-invariant inference profile.
#SBATCH --job-name=social-q0-o
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-96:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: sbatch $0 REPO MODEL_DIR OUTPUT_DIR" >&2
  exit 2
fi
repo=$(readlink -f "$1")
model_dir=$(readlink -f "$2")
out=$(readlink -m "$3")

cd "$repo"
git diff --quiet
git diff --cached --quiet
[[ -f "$model_dir/config.json" && -f "$model_dir/model.safetensors.index.json" ]]
[[ ! -e "$out" ]]
mkdir -p "$out"
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose one assigned GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]

source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
export PYTHONPATH="$repo:$repo/mcore_adapter/src:$repo/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_DATA_DIR="$repo/examples/social_mixed/data_reasoning_v6"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH OPENAI_API_KEY
nvcc_path=$(readlink -f "$(command -v nvcc)")
export CUDA_HOME=$(dirname "$(dirname "$nvcc_path")")
site_dir=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

served_model=qwen3-4b-q0
port=$((23000 + SLURM_JOB_ID % 7000))
checkpoint_hash=$(python - "$model_dir" <<'PY'
import hashlib, sys
from pathlib import Path
root=Path(sys.argv[1])
h=hashlib.sha256()
for path in sorted(root.glob('model-*.safetensors')):
    h.update(path.name.encode()+b'\0')
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8<<20),b''):h.update(block)
print(h.hexdigest())
PY
)
git rev-parse HEAD > "$out/SOURCE_COMMIT"
printf '%s\n' \
  'profile=social-q0-o-batch-invariant-v1' \
  'VLLM_BATCH_INVARIANT=1' \
  'tensor_parallel_size=1' \
  'max_num_seqs=32' \
  'temperature=1' \
  'prefix_caching=true' \
  'chunked_prefill=false' \
  'cascade_attention=false' \
  'speculative_decoding=false' \
  'enforce_eager=true' > "$out/FROZEN_PROFILE.txt"

setsid python -u -m vllm.entrypoints.openai.api_server \
  --model "$model_dir" --served-model-name "$served_model" \
  --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 \
  --dtype bfloat16 --max-model-len 4096 --max-num-seqs 32 \
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
        with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:json.load(response)
        break
    except OSError:
        try:os.kill(pid,0)
        except OSError:raise RuntimeError('vLLM server exited during startup')
        if time.monotonic()-started>1200:raise TimeoutError('vLLM startup exceeded 1200 seconds')
        time.sleep(2)
PY

grep -F 'enable_prefix_caching=True' "$out/server.log"
grep -F 'enable_chunked_prefill=False' "$out/server.log"
python -u -m training.social_mixed.reasoning_probe \
  --views O --cases 32 --seed 42 --concurrency 32 \
  --base-url "http://127.0.0.1:$port/v1" --model "$served_model" \
  --checkpoint-hash "$checkpoint_hash" --output "$out/probe"
printf '0\n' > "$out/EXIT_CODE"
