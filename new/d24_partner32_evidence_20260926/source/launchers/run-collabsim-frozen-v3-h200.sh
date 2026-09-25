#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 3 ]] || { echo 'usage: script LABEL MODEL_PATH CHECKPOINT_SHA256' >&2; exit 2; }
label=$1
model=$2
checkpoint_id=$3
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]]
[[ "$checkpoint_id" =~ ^[0-9a-f]{64}$ ]]
repo=/home/e/e1300530/tmp/MARSHAL-d-results-archive-20260924
runner=/home/e/e1300530/tmp/collabsim-native-lite-venv/bin/python
env_dir=/home/e/e1300530/tmp/marshal-vllm09
[[ -f "$model/config.json" && -f "$model/tokenizer.json" && -f "$model/model.safetensors" ]]
[[ -x "$runner" ]]
cd "$repo"
[[ "$(git rev-parse HEAD)" == "${COLLABSIM_SOURCE_COMMIT:?Pin source commit at submission}" ]]
[[ -z "$(git status --porcelain)" ]] || { echo 'Source checkout is dirty' >&2; exit 42; }
source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate "$env_dir"
export PYTHONPATH="$repo:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1 LITELLM_API_KEY=EMPTY OPENAI_API_KEY=EMPTY
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
for key in ${!COLLABSIM_MODEL_@}; do unset "$key"; done
nvcc_path="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
site_dir="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose one GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]
"$runner" -m examples.final_evaluation.collabsim_frozen_v3 --verify
python - <<'PY'
import os,torch,vllm
assert os.environ.get('VLLM_BATCH_INVARIANT')=='1'
assert torch.cuda.is_available() and torch.cuda.device_count()==1
assert vllm.__version__.split('+')[0]=='0.28.0'
print('GPU',torch.cuda.get_device_name(0),torch.cuda.get_device_properties(0).total_memory,flush=True)
PY
out="$repo/runs/collabsim_frozen_v3/${label}-${SLURM_JOB_ID}"
mkdir -p "$out"
printf '%s\n' \
  "source_commit=$COLLABSIM_SOURCE_COMMIT" "model=$model" "checkpoint_id=$checkpoint_id" \
  'VLLM_BATCH_INVARIANT=1' 'tensor_parallel_size=1' 'dtype=bfloat16' \
  'max_model_len=98304' 'max_num_seqs=32' 'gpu_memory_utilization=0.65' \
  'prefix_caching=true' 'chunked_prefill=false' 'cascade_attention=false' \
  'enforce_eager=true' > "$out/SERVING_PROFILE.txt"
served="collabsim-${label}"
port=$((24000 + SLURM_JOB_ID % 6000))
setsid python -u -m vllm.entrypoints.openai.api_server \
  --model "$model" --served-model-name "$served" \
  --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 \
  --dtype bfloat16 --max-model-len 98304 --max-num-seqs 32 \
  --gpu-memory-utilization 0.65 --enable-prefix-caching \
  --no-enable-chunked-prefill --disable-cascade-attn --enforce-eager \
  > "$out/server.log" 2>&1 &
server_pid=$!
cleanup() {
  if kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM -- "-$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT TERM INT
python - "$port" "$server_pid" "$served" <<'PY'
import json,os,sys,time
from urllib.request import urlopen
port,pid,served=int(sys.argv[1]),int(sys.argv[2]),sys.argv[3]
started=time.monotonic()
while True:
 try:
  with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:
   body=json.load(response)
  assert served in [x['id'] for x in body['data']]
  break
 except OSError:
  try: os.kill(pid,0)
  except OSError: raise RuntimeError('vLLM server exited during startup')
  if time.monotonic()-started>900: raise TimeoutError('vLLM startup exceeded 900 seconds')
  time.sleep(2)
print('SERVER_READY',served,flush=True)
PY
"$runner" -u -m examples.final_evaluation.collabsim_frozen_v3 \
  --model "$served" --base-url "http://127.0.0.1:${port}/v1" \
  --checkpoint-id "$checkpoint_id" --output "$out/results" --run
printf '0\n' > "$out/EXIT_CODE"
