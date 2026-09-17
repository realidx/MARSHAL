#!/usr/bin/env bash
set -euo pipefail
BP_DIAG_HERE="$(cd "$(dirname "$0")" && pwd)"
BP_DIAG_ROOT="$(cd "$BP_DIAG_HERE/../.." && pwd)"
BP_DIAG_JOB="${1:?Pass an absolute NEW output directory}"
[[ "$BP_DIAG_JOB" = /* ]] || { echo 'Output must be absolute' >&2; exit 2; }
mkdir "$BP_DIAG_JOB"
trap 'BP_DIAG_STATUS=$?; printf "%s\n" "$BP_DIAG_STATUS" > "$BP_DIAG_JOB/EXIT_CODE"' EXIT
BP_DIAG_PY="${BP_DIAG_PY:-/raid/chenjiahao/conda_envs/mas/bin/python}"
BP_DIAG_MODEL="${BP_DIAG_MODEL:-/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-6,7}"
export CUDA_HOME="${CUDA_HOME:-/home/chenjiahao/cuda-11.8}"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/home/chenjiahao/cuda-11.8/bin/ptxas}"
export PATH="$(dirname "$BP_DIAG_PY"):$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$(dirname "$BP_DIAG_PY")/../lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export PYTHONPATH="$BP_DIAG_ROOT"
cd "$BP_DIAG_ROOT"
if [[ -f "$BP_DIAG_ROOT/bundle_manifest.json" ]]; then
  "$BP_DIAG_PY" - <<'PY'
import hashlib, json
from pathlib import Path
for name, expected in json.loads(Path('bundle_manifest.json').read_text())['files'].items():
    if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
        raise SystemExit('Bundle file mismatch: ' + name)
print('Independent bundle hashes verified.')
PY
fi
"$BP_DIAG_PY" "$BP_DIAG_HERE/evaluate.py" --check
"$BP_DIAG_PY" -m unittest discover -s "$BP_DIAG_HERE" -p 'test_*.py' -v
"$BP_DIAG_PY" -u "$BP_DIAG_HERE/remote.py" --model "$BP_DIAG_MODEL" \
  --output "$BP_DIAG_JOB/run" --ports "${BP_DIAG_PORT0:-18093}" "${BP_DIAG_PORT1:-18094}" \
  2>&1 | tee "$BP_DIAG_JOB/console.log"
