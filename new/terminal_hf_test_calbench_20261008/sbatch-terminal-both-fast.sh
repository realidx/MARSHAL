#!/usr/bin/env bash
#SBATCH --job-name=slices-base-D
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "${REPO_DIR:-${SLURM_SUBMIT_DIR:?Submit from the repository root}}"
source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
slice_nvcc=$(readlink -f "$(command -v nvcc)")
export CUDA_HOME=$(dirname "$(dirname "$slice_nvcc")")
slice_site=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$slice_site/nvidia/cuda_runtime/lib:$slice_site/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export VLLM_BATCH_INVARIANT=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
TASK_PORT=$((20000 + SLURM_JOB_ID % 20000))
TASK_URL="http://127.0.0.1:$TASK_PORT/v1"
TASK_OUT="/home/e/e1300530/tmp/terminal-test-${EVAL_LABEL}-${SLURM_JOB_ID}"
mkdir -p "${TASK_OUT}.server"
python -u -m vllm.entrypoints.openai.api_server --model "$EVAL_MODEL" --served-model-name terminal-eval --host 127.0.0.1 --port "$TASK_PORT" --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 32768 --max-num-seqs 64 --gpu-memory-utilization 0.80 --enable-prefix-caching --enforce-eager --no-enable-chunked-prefill --disable-cascade-attn > "${TASK_OUT}.server/server.log" 2>&1 &
TASK_SERVER=$!
trap 'kill "${TASK_TEST_PID:-}" "${TASK_CAL_PID:-}" "$TASK_SERVER" 2>/dev/null || true; wait "$TASK_SERVER" 2>/dev/null || true' EXIT
python - "$TASK_URL" "$TASK_SERVER" <<'READY'
import sys,time,os,json
from urllib.request import urlopen
url,pid=sys.argv[1],int(sys.argv[2])
for _ in range(180):
 os.kill(pid,0)
 try:
  with urlopen(url+'/models',timeout=5) as r:json.load(r)
  break
 except Exception:time.sleep(5)
else:raise RuntimeError('Server startup timeout')
READY
TASK_CALBENCH="/home/e/e1300530/tmp/terminal-calbench-${EVAL_LABEL}-${SLURM_JOB_ID}"
mkdir -p "$TASK_CALBENCH"
python - "$TASK_CALBENCH" "$TASK_URL" "$EVAL_MODEL" <<'ROUTES'
import json,sys,hashlib,importlib.metadata
from pathlib import Path
out,url,model=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]);endpoint=dict(model='terminal-eval',base_url=url)
routes=dict(local_only=True,temperature=0.,max_tokens=4096,timeout_seconds=600,endpoints={'focal':endpoint,'q0':endpoint},equivalent_replicas=[endpoint],execution_protocol='reasoning-separated-v2-tokens-4096')
(out/'routes.json').write_text(json.dumps(routes,indent=2)+'\n')
(out/'execution_identity.json').write_text(json.dumps(dict(model=str(model),export_verified=json.loads((model/'EXPORT_VERIFIED.json').read_text()),shared_server=True,context=32768,max_num_seqs=64,batch_invariant=True,chunked_prefill=False,cascade_attention=False,terminal_output=1024,calbench_output=4096),indent=2)+'\n')
ROUTES
TASK_RUNNER=/home/e/e1300530/tmp/MARSHAL-calbench-20260918/.venv-calbench/bin/python
"$TASK_RUNNER" -c 'from examples.final_evaluation.calbench_local import verify_source; verify_source(); from examples.final_evaluation.calbench_stream import load_frozen; load_frozen()'
python -u -m examples.strategic_slices.evaluate_terminal_hf --model "$EVAL_MODEL" --url "$TASK_URL" --output "$TASK_OUT" --workers 64 --repeats 8 > "${TASK_OUT}.log" 2>&1 &
TASK_TEST_PID=$!
"$TASK_RUNNER" -u -m examples.final_evaluation.calbench_local --routes "$TASK_CALBENCH/routes.json" --output "$TASK_CALBENCH/games" --parallel-games 24 --games 2 --suite stream > "$TASK_CALBENCH/runner.log" 2>&1 &
TASK_CAL_PID=$!
set +e
wait "$TASK_TEST_PID"; TASK_TEST_STATUS=$?
wait "$TASK_CAL_PID"; TASK_CAL_STATUS=$?
set -e
printf '%s\n' "$TASK_TEST_STATUS" > "${TASK_OUT}.EXIT_CODE"
printf '%s\n' "$TASK_CAL_STATUS" > "$TASK_CALBENCH/EXIT_CODE"
[[ "$TASK_TEST_STATUS" == 0 && "$TASK_CAL_STATUS" == 0 ]]
