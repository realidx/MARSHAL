#!/usr/bin/env bash
#SBATCH --job-name=ttt-slice-pilot
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-96:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: sbatch $0 REPO_DIR MODEL_DIR NEW_OUTPUT_DIR" >&2
  exit 2
fi

repo=$(readlink -f "$1")
model_dir=$(readlink -f "$2")
out=$(readlink -m "$3")
pilot_dir=$(cd "$(dirname "$0")" && pwd)

[[ -f "$repo/roll/agentic/env/tictactoe/minimax.py" ]]
[[ -f "$repo/roll/agentic/tictactoe_protocol.py" ]]
[[ -f "$model_dir/config.json" ]]
[[ -f "$pilot_dir/pilot_data/panel_requests.jsonl" ]]
[[ -f "$pilot_dir/pilot_data/panel_oracle.jsonl" ]]
[[ -f "$pilot_dir/pilot_data/source_hashes.json" ]]
[[ ! -e "$out" ]]
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose the assigned GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]

mkdir -p "$out"
echo "PILOT_RUN_DIR=$out"
export MARSHAL_REPO_ROOT="$repo"
export PYTHONPATH="$repo:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH OPENAI_API_KEY

source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
nvcc_path=$(readlink -f "$(command -v nvcc)")
export CUDA_HOME=$(dirname "$(dirname "$nvcc_path")")
site_dir=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

python - "$repo" "$pilot_dir/pilot_data/source_hashes.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
expected = json.loads(Path(sys.argv[2]).read_text())
for relative, digest in expected.items():
    actual = hashlib.sha256((root/relative).read_bytes()).hexdigest()
    if actual != digest:
        raise RuntimeError(f'Source hash mismatch: {relative}')
print('oracle and prompt source hashes verified')
PY

served_model=ttt-slice-pilot
port=$((23000 + ${SLURM_JOB_ID:-0} % 7000))
replicas=${PILOT_REPLICAS:-16}
limit=${PILOT_LIMIT:-0}
concurrency=${PILOT_CONCURRENCY:-16}
min_valid=${PILOT_MIN_VALID_SAMPLES:-8}

checkpoint_hash=$(python - "$model_dir" <<'PY'
import hashlib, sys
from pathlib import Path
root = Path(sys.argv[1])
paths = sorted(root.glob('model-*.safetensors'))
if not paths:
    paths = sorted(root.glob('*.safetensors'))
if not paths:
    raise RuntimeError('No model safetensors were found')
digest = hashlib.sha256()
for path in paths:
    digest.update(path.name.encode() + b'\0')
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 << 20), b''):
            digest.update(block)
print(digest.hexdigest())
PY
)

python - "$repo" "$pilot_dir" "$model_dir" "$checkpoint_hash" "$out" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
repo = Path(sys.argv[1])
pilot = Path(sys.argv[2])
model = Path(sys.argv[3])
model_hash = sys.argv[4]
out = Path(sys.argv[5])
paths = [repo/'roll/agentic/env/tictactoe/minimax.py',
         repo/'roll/agentic/tictactoe_protocol.py',
         pilot/'analyze.py', pilot/'probe.py', pilot/'sbatch_probe.sh',
         pilot/'pilot_data/panel_requests.jsonl', pilot/'pilot_data/panel_oracle.jsonl']
source = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
manifest = dict(repo=str(repo), pilot=str(pilot), model_dir=str(model),
                checkpoint_hash=model_hash, sources=source,
                slurm_job_id=os.environ.get('SLURM_JOB_ID'),
                gpu_visibility=os.environ.get('CUDA_VISIBLE_DEVICES'),
                batch_invariant=os.environ.get('VLLM_BATCH_INVARIANT'))
(out/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
PY

setsid python -u -m vllm.entrypoints.openai.api_server \
  --model "$model_dir" --served-model-name "$served_model" \
  --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 \
  --dtype bfloat16 --max-model-len 2048 --max-num-seqs 16 \
  --gpu-memory-utilization 0.65 --enable-prefix-caching \
  --no-enable-chunked-prefill --disable-cascade-attn --enforce-eager \
  --generation-config vllm \
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
port, pid = int(sys.argv[1]), int(sys.argv[2])
started = time.monotonic()
while True:
    try:
        with urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2) as response:
            json.load(response)
        break
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError as exc:
            raise RuntimeError('vLLM exited during startup') from exc
        if time.monotonic() - started > 1200:
            raise TimeoutError('vLLM startup exceeded 1200 seconds')
        time.sleep(2)
PY

python -u "$pilot_dir/probe.py" \
  --panel "$pilot_dir/pilot_data/panel_requests.jsonl" \
  --output "$out/probe" --base-url "http://127.0.0.1:$port/v1" \
  --model "$served_model" --checkpoint-hash "$checkpoint_hash" \
  --replicas "$replicas" --limit "$limit" --concurrency "$concurrency" \
  --temperature 0.7 --top-p 0.8 --top-k 20 --max-tokens 600

python "$pilot_dir/analyze.py" score \
  --oracle-dir "$pilot_dir/pilot_data" \
  --samples "$out/probe/samples.jsonl" \
  --output "$out/score" --model-id "$checkpoint_hash" \
  --temperature 0.7 --min-valid-samples "$min_valid"

python - "$out" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
probe = json.loads((out/'probe/summary.json').read_text())
score = json.loads((out/'score/summary.json').read_text())
if not probe['complete']:
    raise RuntimeError('Probe was incomplete')
result = dict(checkpoint_hash=probe['checkpoint_hash'], jobs=probe['jobs'],
              ranked_decisions=score['ranked_decisions'],
              panel_decisions=score['panel_decisions'],
              invalid_samples=score['invalid_samples'])
(out/'COMPLETE.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
PY
