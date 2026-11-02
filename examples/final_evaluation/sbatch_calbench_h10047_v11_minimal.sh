#!/usr/bin/env bash
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100-47:1
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/e/e1300530/tmp/calbench-v11_minimal-h10047-%x-%j.out
#SBATCH --error=/home/e/e1300530/tmp/calbench-v11_minimal-h10047-%x-%j.err

set -euo pipefail
repo="${SLURM_SUBMIT_DIR:?Submit from the MARSHAL repository root}"
cd "$repo"
: "${CALBENCH_MODEL:?Missing model path}"
: "${CALBENCH_SCAFFOLD:?Missing scaffold condition}"
: "${CALBENCH_LABEL:?Missing run label}"
: "${CALBENCH_PROMPT_VERSION:?Missing prompt version}"
[[ "$CALBENCH_PROMPT_VERSION" == general-belief-ms-v11-minimal ]]
[[ "$CALBENCH_SCAFFOLD" == belief-ms ]]
[[ "$CALBENCH_SUITE" == stream && "$CALBENCH_MAX_TOKENS" == 4096 ]]
[[ "$CALBENCH_MAX_MODEL_LEN" == 32768 && "$CALBENCH_MAX_NUM_SEQS" == 32 ]]
[[ "$CALBENCH_PARALLEL_GAMES" == 8 && "$VLLM_BATCH_INVARIANT" == 1 ]]
[[ "$CALBENCH_DISABLE_CHUNKED_PREFILL" == 1 && "$CALBENCH_DISABLE_CASCADE_ATTN" == 1 ]]

source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
export PYTHONPATH="$repo:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export VLLM_BATCH_INVARIANT=1
unset VLLM_USE_V1 VLLM_ATTENTION_BACKEND TRITON_PTXAS_PATH
nvcc_path="$(readlink -f "$(command -v nvcc)")"
export CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
site_dir="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$site_dir/nvidia/cuda_runtime/lib:$site_dir/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUDNN_FRONTEND_CUDART_LIB_NAME=libcudart.so.13

runner=/home/e/e1300530/tmp/MARSHAL-calbench-20260918/.venv-calbench/bin/python
[[ -x "$runner" ]]
[[ -f "$CALBENCH_MODEL/config.json" ]]
: "${CUDA_VISIBLE_DEVICES:?Slurm must expose the allocated GPU}"
[[ "$CUDA_VISIBLE_DEVICES" != *,* ]]

"$runner" -c 'from examples.final_evaluation.calbench_local import verify_source; verify_source()'
"$runner" -m examples.final_evaluation.calbench_stream --verify examples/final_evaluation/calbench_stream_v1
if [[ "$CALBENCH_SCAFFOLD" == belief-ms ]]; then
  "$runner" -c 'from examples.final_evaluation.calbench_scaffold import verify_registration; r=verify_registration(); assert r["version"] == "general-belief-ms-v11-minimal"'
fi
python - <<'PY'
import os, torch
assert os.environ.get('VLLM_BATCH_INVARIANT') == '1'
assert torch.cuda.is_available() and torch.cuda.device_count() == 1
print('CalBench24 H100-47 shared execution profile')
print('VLLM_BATCH_INVARIANT=', os.environ['VLLM_BATCH_INVARIANT'])
print('Visible GPU:', torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory)
PY

port=$((20000 + SLURM_JOB_ID % 10000))
out="$repo/runs/calbench_soc/${CALBENCH_LABEL}-stream-${SLURM_JOB_ID}"
meta_dir="$repo/runs/calbench_soc/submissions"
mkdir -p "$meta_dir"
meta="$meta_dir/${SLURM_JOB_ID}.json"
python - "$meta" "$out" "$port" "$runner" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
meta_path, out, port, runner = sys.argv[1:]
repo = Path.cwd()
max_tokens = int(os.environ['CALBENCH_MAX_TOKENS'])
script_paths = [
    'examples/final_evaluation/submit_calbench_h10047_v11_minimal.sh',
    'examples/final_evaluation/sbatch_calbench_h10047_v11_minimal.sh',
    'examples/final_evaluation/finalize_calbench_pipeline_snapshot_v11_minimal.py',
    'examples/strategic_slices/versions/general_ms_calbench_v11_minimal_20261102/SNAPSHOT.json',
]
script_hashes = {}
for name in script_paths:
    p = repo / name
    script_hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else '未记录'
launch_argv = [
    'python', '-u', '-m', 'examples.final_evaluation.launch_calbench_local',
    '--runtime', 'soc', '--suite', os.environ['CALBENCH_SUITE'],
    '--model', os.environ['CALBENCH_MODEL'], '--max-tokens', os.environ['CALBENCH_MAX_TOKENS'],
    '--max-model-len', os.environ['CALBENCH_MAX_MODEL_LEN'], '--max-num-seqs', os.environ['CALBENCH_MAX_NUM_SEQS'],
    '--runner-python', runner, '--ports', port, '--parallel-games', os.environ['CALBENCH_PARALLEL_GAMES'],
    '--disable-chunked-prefill', '--disable-cascade-attn', '--scaffold', os.environ['CALBENCH_SCAFFOLD'],
    '--output', out,
]
request = {
    'run_label': os.environ['CALBENCH_LABEL'],
    'prompt_version': os.environ['CALBENCH_PROMPT_VERSION'],
    'condition': {'model': os.environ['CALBENCH_MODEL'], 'scaffold': os.environ['CALBENCH_SCAFFOLD']},
    'launch_argv': launch_argv,
    'resolved_routes_if_launcher_fails': {
        'local_only': True, 'temperature': 0.0, 'max_tokens': max_tokens, 'timeout_seconds': 600,
        'execution_protocol': f'reasoning-separated-v2-tokens-{max_tokens}',
        'endpoints': {
            'focal': {'model': 'social-replica-0', 'base_url': f'http://127.0.0.1:{port}/v1'},
            'q0': {'model': 'social-replica-0', 'base_url': f'http://127.0.0.1:{port}/v1'},
        },
        'equivalent_replicas': [{'model': 'social-replica-0', 'base_url': f'http://127.0.0.1:{port}/v1'}],
        'scaffold': os.environ['CALBENCH_SCAFFOLD'],
    },
    'runtime_profile': {
        'partition': 'gpu', 'gres': 'gpu:h100-47:1', 'time_limit': '03:00:00',
        'cpus_per_task': 8, 'memory': '64G', 'parallel_games': 8, 'max_num_seqs': 32,
        'max_model_len': 32768, 'dtype': 'bfloat16', 'gpu_memory_utilization': 0.65,
        'enforce_eager': True, 'enable_prefix_caching': True,
        'chunked_prefill': False, 'cascade_attention': False,
        'VLLM_BATCH_INVARIANT': '1', 'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '1',
        'temperature': 0.0, 'max_tokens': max_tokens,
    },
    'submission': {
        'job_id': os.environ.get('SLURM_JOB_ID', '未记录'),
        'job_name': os.environ.get('SLURM_JOB_NAME', '未记录'),
        'partition': os.environ.get('SLURM_JOB_PARTITION', 'gpu'),
        'nodelist': os.environ.get('SLURM_JOB_NODELIST', '未记录'),
        'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES', '未记录'),
        'cpus_per_task': os.environ.get('SLURM_CPUS_PER_TASK', '未记录'),
        'time_limit_minutes': 180,
    },
    'source': {'git_head': os.popen('git rev-parse HEAD').read().strip(), 'execution_scripts_sha256': script_hashes},
}
Path(meta_path).write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
PY

finish() {
  status=$?
  trap - EXIT
  mkdir -p "$out"
  cp "$meta" "$out/job_submission.json" 2>/dev/null || true
  printf '%s\n' "$status" > "$out/BATCH_EXIT_CODE"
  python -m examples.final_evaluation.finalize_calbench_pipeline_snapshot_v11_minimal \
    --run-root "$out" --request "$out/job_submission.json" || \
    echo 'Pipeline snapshot finalization failed; inspect the Slurm output.' >&2
  exit "$status"
}
trap finish EXIT

python -u -m examples.final_evaluation.launch_calbench_local \
  --runtime soc --suite "$CALBENCH_SUITE" --model "$CALBENCH_MODEL" \
  --max-tokens "$CALBENCH_MAX_TOKENS" --max-model-len "$CALBENCH_MAX_MODEL_LEN" \
  --max-num-seqs "$CALBENCH_MAX_NUM_SEQS" --runner-python "$runner" \
  --ports "$port" --parallel-games "$CALBENCH_PARALLEL_GAMES" \
  --disable-chunked-prefill --disable-cascade-attn --scaffold "$CALBENCH_SCAFFOLD" \
  --output "$out"
