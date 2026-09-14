#!/usr/bin/env bash
# New NUS inference-only entrypoint; existing launchers/runtimes are unchanged.
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$entry_dir/../.." && pwd)"
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Run inside an allocated single-GPU job. No optimizer or training process.
Defaults: OUTCOME_PYTHON=/home/e/e1300530/tmp/marshal-vllm09/bin/python
          OUTCOME_MODEL=/home/e/e1300530/models/Qwen3-4B-Instruct-2507
          OUTCOME_GPU_MEMORY=0.40, OUTCOME_PORT=18080
          OUTCOME_MAX_TOKENS=2048, OUTCOME_TIMEOUT=180
          OUTCOME_ROLLOUTS=1, OUTCOME_CONCURRENCY=1, OUTCOME_FORMAT_PENALTY=-0.1
Use sbatch examples/outcome_selfplay_nus/sbatch_smoke.sh from the repo root.
HELP
  exit 0
fi
python_bin="${OUTCOME_PYTHON:-/home/e/e1300530/tmp/marshal-vllm09/bin/python}"
model_dir="${OUTCOME_MODEL:-/home/e/e1300530/models/Qwen3-4B-Instruct-2507}"
[[ -x "$python_bin" ]] || { echo "Python missing: $python_bin; set OUTCOME_PYTHON" >&2; exit 2; }
[[ -d "$model_dir" ]] || { echo "Model missing: $model_dir; set OUTCOME_MODEL" >&2; exit 2; }
# Respect scheduler GPU selection, never override CUDA_VISIBLE_DEVICES.
if [[ -z "${SLURM_JOB_ID:-}" && -z "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  echo 'Run in a single-GPU allocation, or explicitly select one GPU with CUDA_VISIBLE_DEVICES.' >&2
  exit 2
fi
mkdir -p "$repo_dir/runs/outcome_selfplay_nus"
run_dir="$(mktemp -d "$repo_dir/runs/outcome_selfplay_nus/${SLURM_JOB_ID:-manual}.XXXXXX")"
echo "OUTCOME_RUN_DIR=$run_dir"
export OUTCOME_PYTHON="$python_bin"
export OUTCOME_RUN_DIR="$run_dir"
export OUTCOME_PORT="${OUTCOME_PORT:-18080}"
export OUTCOME_GPU_MEMORY="${OUTCOME_GPU_MEMORY:-0.40}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1
"$python_bin" "$entry_dir/unpack_runtime.py" "$entry_dir/runtime_v3.tar.gz" "$entry_dir/runtime_v3.sha256" "$run_dir"
"$python_bin" - "$model_dir" <<'PY'
import importlib.metadata,json,os,socket,sys
from pathlib import Path
import torch
if torch.cuda.device_count()!=1:raise SystemExit('Exactly one scheduler-visible GPU required')
port=int(os.environ['OUTCOME_PORT']);memory=float(os.environ['OUTCOME_GPU_MEMORY'])
if not 1024<=port<=65535 or not 0<memory<=1:raise SystemExit('Invalid port or GPU memory fraction')
with socket.socket() as sock:sock.bind(('127.0.0.1',port))
record=dict(host=socket.gethostname(),job_id=os.environ.get('SLURM_JOB_ID'),cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),gpu=torch.cuda.get_device_name(0),python=sys.executable,model=sys.argv[1],port=port,gpu_memory_utilization=memory,training_started=False,versions={n:importlib.metadata.version(n) for n in ('torch','vllm','numpy')})
Path(os.environ['OUTCOME_RUN_DIR'],'server_manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
PY
server_pid=''
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$python_bin" -m vllm.entrypoints.cli.main serve "$model_dir" \
  --served-model-name outcome-base --host 127.0.0.1 --port "$OUTCOME_PORT" \
  --tensor-parallel-size 1 --dtype bfloat16 \
  --max-model-len 8192 --max-num-seqs 4 \
  --gpu-memory-utilization "$OUTCOME_GPU_MEMORY" \
  --enable-auto-tool-choice --tool-call-parser hermes \
  >"$run_dir/server.log" 2>&1 &
server_pid=$!
"$python_bin" - "$server_pid" <<'PY'
import json,os,sys,time,urllib.request
from pathlib import Path
pid=int(sys.argv[1]);deadline=time.monotonic()+600
url=f"http://127.0.0.1:{os.environ['OUTCOME_PORT']}/v1/models"
while time.monotonic()<deadline:
    try:os.kill(pid,0)
    except ProcessLookupError:raise SystemExit('Inference process exited; inspect server.log')
    try:
        with urllib.request.urlopen(url,timeout=3) as response:data=json.load(response)
        if 'outcome-base' not in [m['id'] for m in data['data']]:raise SystemExit('Unexpected model already on requested port')
        Path(os.environ['OUTCOME_RUN_DIR'],'models.json').write_text(json.dumps(data,indent=2)+'\n')
        break
    except (OSError,ValueError):time.sleep(2)
else:raise SystemExit('Inference readiness timed out; inspect server.log')
PY
# The v3 rollout handles private views, retry penalties and native replay.
bash "$run_dir/outcome_rollout_runtime/run_rollout.sh" \
  --backend http --suite smoke \
  --base-url "http://127.0.0.1:$OUTCOME_PORT/v1" --model outcome-base \
  --rollouts "${OUTCOME_ROLLOUTS:-1}" --concurrency "${OUTCOME_CONCURRENCY:-1}" \
  --max-tokens "${OUTCOME_MAX_TOKENS:-2048}" --timeout "${OUTCOME_TIMEOUT:-180}" \
  --format-penalty "${OUTCOME_FORMAT_PENALTY:--0.1}" \
  --output-dir "$run_dir/rollout" \
  2>&1 | tee "$run_dir/client.log"
echo "Results: $run_dir/rollout/summary.json"
