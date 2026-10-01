#!/usr/bin/env bash
#SBATCH --job-name=benac-slice-pilot
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
pilot_dir="$repo/new/benac_slice_pilot"
panel_dir=$(readlink -f "${PILOT_PANEL_DIR:-$pilot_dir/pilot_data}")
[[ -f "$model_dir/config.json" ]]
[[ -f "$panel_dir/summary.json" ]]
[[ -f "$panel_dir/selected.jsonl" ]]
[[ -f "$panel_dir/candidates.jsonl" ]]
[[ ! -e "$out" ]]
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose the assigned GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]

cd "$repo"
export PYTHONPATH="$repo:$repo/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH OPENAI_API_KEY

source "${SOC_CONDA_SH:-/home/e/e1300530/miniconda3/etc/profile.d/conda.sh}"
conda activate "${SOC_CONDA_ENV:-/home/e/e1300530/tmp/marshal-vllm09}"

nvcc_path=$(readlink -f "$(command -v nvcc)")
export CUDA_HOME=$(dirname "$(dirname "$nvcc_path")")
site_dir=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

source_path=$(python - "$repo" "$panel_dir/summary.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
summary = json.loads(Path(sys.argv[2]).read_text())
source = Path(summary['source'])
if not source.is_absolute():
    source = root / source
if hashlib.sha256(source.read_bytes()).hexdigest() != summary['source_sha256']:
    raise RuntimeError('Pilot source bank hash changed; rebuild the C/S panel')
print(source)
PY
)

mkdir -p "$out"
git rev-parse HEAD > "$out/SOURCE_COMMIT"
python - "$model_dir" "$out" "$panel_dir" "$source_path" <<'PY'
import hashlib, json, sys
from pathlib import Path
model, out, panel, source = map(Path, sys.argv[1:5])
paths = sorted(model.glob('model-*.safetensors')) or sorted(model.glob('*.safetensors'))
if not paths:
    raise RuntimeError('No model safetensors found')
digest = hashlib.sha256()
for path in paths:
    digest.update(path.name.encode() + b'\0')
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 << 20), b''):
            digest.update(block)
(out / 'MODEL_SHA256').write_text(digest.hexdigest() + '\n')
manifest = {
    'model_dir': str(model),
    'model_sha256': digest.hexdigest(),
    'pilot_files': {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((Path('new/benac_slice_pilot')).glob('*.py'))
    },
    'panel_files': {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [panel/'summary.json', panel/'selected.jsonl',
                     panel/'candidates.jsonl', source]
    },
}
(out / 'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY

served_model=benac-slice-pilot
port=$((23000 + ${SLURM_JOB_ID:-0} % 7000))
setsid python -u -m vllm.entrypoints.openai.api_server \
  --model "$model_dir" --served-model-name "$served_model" \
  --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 \
  --dtype bfloat16 --max-model-len 4096 --max-num-seqs 16 \
  --gpu-memory-utilization 0.65 --enable-prefix-caching \
  --no-enable-chunked-prefill --disable-cascade-attn --enforce-eager \
  --generation-config vllm --enable-auto-tool-choice --tool-call-parser hermes \
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
        except OSError:
            raise RuntimeError('vLLM server exited during startup')
        if time.monotonic() - started > 1200:
            raise TimeoutError('vLLM startup exceeded 1200 seconds')
        time.sleep(2)
PY

python -u -m new.benac_slice_pilot.model_probe \
  --source "$source_path" \
  --selected "$panel_dir/selected.jsonl" \
  --candidates "$panel_dir/candidates.jsonl" \
  --base-url "http://127.0.0.1:$port/v1" \
  --model "$served_model" \
  --checkpoint-hash "$(cat "$out/MODEL_SHA256")" \
  --output "$out/probe" \
  --replicas "${PILOT_REPLICAS:-16}" \
  --max-tokens "${PILOT_MAX_TOKENS:-1024}" \
  --concurrency "${PILOT_CONCURRENCY:-8}" \
  --seed "${PILOT_SEED:-42}"
