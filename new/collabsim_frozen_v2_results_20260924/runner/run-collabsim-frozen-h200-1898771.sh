#!/usr/bin/env bash
#SBATCH --job-name=collabsim-frozen
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h200-141:1
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --output=/home/e/e1300530/tmp/collabsim-frozen-%j.out
#SBATCH --error=/home/e/e1300530/tmp/collabsim-frozen-%j.err
set -euo pipefail
[[ $# -eq 4 ]] || { echo 'usage: script v1|v2|v2single|v2missing LABEL MODEL_PATH CHECKPOINT_ID' >&2; exit 2; }
version=$1
label=$2
model=$3
checkpoint_id=$4
[[ "$version" == v1 || "$version" == v2 || "$version" == v2single || "$version" == v2missing ]]
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]]
[[ "$checkpoint_id" =~ ^[0-9a-f]{64}$ ]]
repo=/home/e/e1300530/tmp/MARSHAL-d-results-archive-20260924
runner=/home/e/e1300530/tmp/collabsim-native-lite-venv/bin/python
env_dir=/home/e/e1300530/tmp/marshal-vllm09
[[ -f "$model/config.json" && -f "$model/tokenizer.json" ]]
[[ -f "$model/model.safetensors" || -f "$model/model.safetensors.index.json" ]]
[[ -x "$runner" ]]
cd "$repo"
[[ "$(git rev-parse HEAD)" == 18987710970592f73c6423eb1e5243b7e2916df3 ]]
git diff --quiet
git diff --cached --quiet
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
module=examples.final_evaluation.collabsim_frozen
[[ "$version" == v2 || "$version" == v2single || "$version" == v2missing ]] && module=examples.final_evaluation.collabsim_frozen_v2
"$runner" -m "$module" --verify
"$runner" -c 'import yaml,litellm,httpx; from examples.final_evaluation.shapefactory_lite import verify_source; verify_source()'
python - <<'PY'
import os,torch,vllm
assert os.environ.get('VLLM_BATCH_INVARIANT')=='1'
assert torch.cuda.is_available() and torch.cuda.device_count()==1
assert vllm.__version__.split('+')[0]=='0.28.0'
print('GPU',torch.cuda.get_device_name(0),torch.cuda.get_device_properties(0).total_memory,flush=True)
PY
out="$repo/runs/collabsim_frozen/${label}-${version}-${SLURM_JOB_ID}"
mkdir -p "$out"
printf '%s\n' \
  "source_commit=18987710970592f73c6423eb1e5243b7e2916df3" \
  "model=$model" "checkpoint_id=$checkpoint_id" \
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
if [[ "$version" == v2missing ]]; then
  mkdir -p "$out/results/shapefactory"
  "$runner" - "$out/results/shapefactory" "$served" "http://127.0.0.1:${port}/v1" "$checkpoint_id" <<'PY'
import json,subprocess,sys
from pathlib import Path
import yaml
from examples.final_evaluation.shapefactory_lite_3p import ROOT,UPSTREAM,config,verify_source
output=Path(sys.argv[1]);served,url,checkpoint_id=sys.argv[2:]
prior=ROOT/'runs/collabsim_frozen/oldbp99-v2-877961/results/shapefactory'
expected='aab6fdb53542132f3818909f533678b5d01d31ce984e53674ebf90e14b737ab9'
assert checkpoint_id==expected
for name in ('native-lite-3p-forward-private','native-lite-3p-forward-dashboard','native-lite-3p-reverse-private'):
 assert (prior/(name+'.exit_code')).read_text().strip()=='0',name
verify_source()
_,cfg=config('dashboard',True,served,url)
name=cfg['experiment']['id']
cfg['logging']['output_dir']=str(output/name)
path=output/(name+'.yml');path.write_text(yaml.safe_dump(cfg,sort_keys=False))
code='from src.config.loader import load_experiment_config; from src.config.schema import validate_config_schema; import sys; validate_config_schema(load_experiment_config(sys.argv[1]))'
subprocess.run([sys.executable,'-c',code,str(path)],cwd=UPSTREAM,check=True)
(output/'REUSED_RUNS.json').write_text(json.dumps({'source':str(prior),'checkpoint_id':checkpoint_id,'reused':['native-lite-3p-forward-private','native-lite-3p-forward-dashboard','native-lite-3p-reverse-private'],'new':[name]},indent=2)+'\n')
with (output/(name+'.log')).open('w') as log:
 result=subprocess.run([sys.executable,'-m','src.cli',str(path),'--run-id',name,'--output-dir',str(output/name)],cwd=UPSTREAM,stdout=log,stderr=subprocess.STDOUT)
(output/(name+'.exit_code')).write_text(str(result.returncode)+'\n')
if result.returncode:raise SystemExit(result.returncode)
PY
  "$runner" -u -m examples.final_evaluation.hidden_profile_local \
    --model "$served" --base-url "http://127.0.0.1:${port}/v1" \
    --checkpoint-id "$checkpoint_id" --repeats 1 \
    --output "$out/results/hidden_profile" --run
  printf '%s\n' 'Three ShapeFactory runs reused from job 877961; one new ShapeFactory and one Hidden Profile run completed.' > "$out/results/COMPLETE"
elif [[ "$version" == v2single ]]; then
  mkdir -p "$out/results"
  printf '%s\n' 'Frozen v2 task configuration; four ShapeFactory runs and one Hidden Profile run. This is a reduced-repeat variant, not the original seven-run v2 suite.' > "$out/results/PROTOCOL_VARIANT.txt"
  "$runner" -u -m examples.final_evaluation.shapefactory_lite_3p \
    --model "$served" --base-url "http://127.0.0.1:${port}/v1" \
    --output "$out/results/shapefactory" --run
  "$runner" -u -m examples.final_evaluation.hidden_profile_local \
    --model "$served" --base-url "http://127.0.0.1:${port}/v1" \
    --checkpoint-id "$checkpoint_id" --repeats 1 \
    --output "$out/results/hidden_profile" --run
  printf '%s\n' 'Reduced-repeat v2 task runs completed; not a task-success certificate.' > "$out/results/COMPLETE"
else
  "$runner" -u -m "$module" --model "$served" \
    --base-url "http://127.0.0.1:${port}/v1" \
    --checkpoint-id "$checkpoint_id" --output "$out/results" --run
fi
printf '0\n' > "$out/EXIT_CODE"
