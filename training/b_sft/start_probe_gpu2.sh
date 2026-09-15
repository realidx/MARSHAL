#!/usr/bin/env bash
# User-run launcher: physical GPU 2, new port 8007. Other services untouched.
set -euo pipefail
probe_bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python=/raid/chenjiahao/conda_envs/mas/bin/python
probe_logs="${probe_bundle_dir}/../logs"
mkdir -p "$probe_logs"
"$probe_python" - <<'PY'
import socket
with socket.socket() as s:
    try:
        s.bind(('127.0.0.1',8007))
    except OSError as exc:
        raise SystemExit('Port 8007 is occupied; inspect the existing service before starting another one.') from exc
PY
nvidia-smi -i 2 --query-gpu=index,name,memory.used,memory.total --format=csv
nohup env CUDA_VISIBLE_DEVICES=2 \
    VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS \
    TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas \
    TRITON_CACHE_DIR=/raid/chenjiahao/mas/.cache/triton_vllm085_gpu_2 \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    "$probe_python" -u -m vllm.entrypoints.openai.api_server \
      --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
      --served-model-name social-base --host 127.0.0.1 --port 8007 \
      --tensor-parallel-size 1 --dtype bfloat16 \
      --max-model-len 16384 --max-num-seqs 1 --gpu-memory-utilization 0.35 \
      --enforce-eager --disable-frontend-multiprocessing \
      --enable-auto-tool-choice --tool-call-parser hermes \
      > "$probe_logs/vllm_gpu2_port8007.log" 2>&1 < /dev/null &
probe_pid=$!
echo "$probe_pid" > "$probe_logs/vllm_gpu2_port8007.pid"
echo "Started physical GPU 2 / port 8007, PID $probe_pid. Log: $probe_logs/vllm_gpu2_port8007.log"
"$probe_python" - "$probe_pid" <<'PY'
import json, os, sys, time
from urllib.request import urlopen
pid=int(sys.argv[1])
for attempt in range(180):
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        raise SystemExit('vLLM exited during startup. Inspect its log.')
    try:
        with urlopen('http://127.0.0.1:8007/v1/models',timeout=3) as r:
            models=json.load(r)
        if any(m['id']=='social-base' for m in models['data']):
            print('GPU 2 service is ready on port 8007.')
            break
    except Exception:
        pass
    if attempt % 12 == 0:print('Waiting for vLLM model loading...',flush=True)
    time.sleep(5)
else:
    raise SystemExit('Startup wait timed out. Service was not stopped; inspect its log.')
PY
