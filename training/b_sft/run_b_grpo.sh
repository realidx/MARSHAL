#!/usr/bin/env bash
set -euo pipefail
export SOCIAL_GRPO_START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cd /raid/chenjiahao/mas
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export LD_LIBRARY_PATH="/raid/chenjiahao/conda_envs/mas/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
PYTHON=/raid/chenjiahao/conda_envs/mas/bin/python
export NCCL_LIBRARY="$PWD/new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2"
if [[ ! -f "$NCCL_LIBRARY" ]]; then
  echo 'Run bash training/b_sft/setup_b_grpo_env.sh to prepare the matching NCCL library.' >&2
  exit 1
fi
export LD_PRELOAD="$NCCL_LIBRARY${LD_PRELOAD:+:$LD_PRELOAD}"
export NCCL_CUMEM_ENABLE=0 NCCL_NVLS_ENABLE=0
export CUDA_VISIBLE_DEVICES="${SOCIAL_GRPO_GPUS:-0,1,4,5,6,7}"
export ROLL_ASSIGNED_CUDA_DEVICES="$CUDA_VISIBLE_DEVICES"
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
export TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MAX_JOBS=2
export PATH="/raid/chenjiahao/conda_envs/mas/bin:$PATH"
export RAY_ADDRESS="127.0.0.1:${SOCIAL_GRPO_RAY_PORT:-26380}"
export MULTI_TENANT=1 RAY_USAGE_STATS_ENABLED=0
export ROLL_LOCAL_COMM_ADDR=127.0.0.1 GLOO_SOCKET_IFNAME=lo NCCL_SOCKET_IFNAME=lo
export MASTER_ADDR=127.0.0.1 MASTER_PORT="${SOCIAL_GRPO_RAY_PORT:-26380}" RAY_NUM_GPUS_PER_NODE=6
# Ray reserves 10002..19999 for workers; the head port must be separate.
"$PYTHON" - <<'PORT_CHECK'
import os, socket, subprocess
port = int(os.environ['MASTER_PORT'])
if not 1024 <= port <= 65535 or 10002 <= port <= 19999:
    raise SystemExit('Choose SOCIAL_GRPO_RAY_PORT outside 10002..19999, within 1024..65535')
with socket.socket() as sock:
    try:
        sock.bind(('', port))
    except OSError:
        # A failed driver can leave its Ray head alive. Reuse only the
        # explicitly configured address after verifying it is a Ray cluster.
        subprocess.run(['ray','status','--address',os.environ['RAY_ADDRESS']],
                       check=True,timeout=15,capture_output=True)
        print('Reusing Ray cluster at', os.environ['RAY_ADDRESS'])
PORT_CHECK
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
# No server shutdown, environment installation, or deletion is implicit.
if [[ -n "${ROLL_OUTPUT_DIR:-}" || -n "${ROLL_LOG_DIR:-}" ]]; then
  echo 'Unset ROLL_OUTPUT_DIR and ROLL_LOG_DIR; this entrypoint records one fixed run directory.' >&2
  exit 1
fi
if [[ -e outputs/social_b_grpo_b_r3 ]]; then
  echo 'outputs/social_b_grpo_b_r3 already exists; preserve it and choose a new run configuration.' >&2
  exit 1
fi
"$PYTHON" -m training.b_sft.check_b_grpo_env
"$PYTHON" - <<'CHECK'
import subprocess,os
selected={int(v) for v in os.environ["CUDA_VISIBLE_DEVICES"].split(",")}
if len(selected)!=6:raise SystemExit("Select exactly six GPU indices")
rows=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used','--format=csv,noheader,nounits'],text=True)
busy=[line.strip() for line in rows.splitlines() if int(line.split(',')[0]) in selected and int(line.split(',')[1])>1000]
if busy:
    raise SystemExit('Selected GPUs must be released before training; current index,MiB: '+ '; '.join(busy))
CHECK
# The verified NCCL library is hash-checked below; no repeated GPU smoke at launch.
if [[ ! -f new/local_data/social_runs/b_grpo_data_v2/manifest.json ]]; then
  "$PYTHON" -m training.b_sft.social_b_grpo \
    --data-dir new/local_data/social_runs/b_behavior_curriculum_v2 \
    --output-dir new/local_data/social_runs/b_grpo_data_v2 \
    --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507
fi
"$PYTHON" - <<'DATA_CHECK'
from training.b_sft.social_b_grpo import validate_export
validate_export('new/local_data/social_runs/b_grpo_data_v2')
print('Single-query curriculum export and split hashes verified.')
DATA_CHECK
"$PYTHON" - <<'RECORD'
import json,hashlib,importlib.metadata,sys,os
from pathlib import Path
from training.b_sft.social_b_rl import CONTRACT
out=Path('outputs/social_b_grpo_b_r3');out.mkdir(parents=True,exist_ok=False)
paths=[Path('examples/social_b/grpo.yaml'),Path('roll/pipeline/rlvr/rlvr_pipeline.py'),Path('roll/pipeline/base_worker.py'),Path('roll/distributed/strategy/vllm_strategy.py'),Path('roll/utils/functionals.py'),Path('roll/utils/offload_states.py'),Path('training/b_sft/run_b_grpo.sh')]
paths+=list(Path('roll/third_party/vllm').rglob('*.py'))
paths.append(Path('roll/distributed/scheduler/log_monitor.py'))
paths.append(Path('roll/distributed/scheduler/generate_scheduler.py'))
paths.extend(Path(p) for p in ('roll/distributed/strategy/deepspeed_strategy.py','roll/distributed/strategy/hf_strategy.py','roll/configs/worker_config.py','roll/distributed/executor/worker.py','roll/distributed/executor/cluster.py','roll/pipeline/base_pipeline.py','roll/pipeline/rlvr/rlvr_config.py','roll/utils/checkpoint_manager.py','roll/utils/upload_utils.py','roll/utils/checkpoint_integrity.py','examples/config/deepspeed_zero2.yaml'))
paths+=list(Path('training/b_sft').glob('social_b*.py'))
obj=dict(launcher_started_at=os.environ['SOCIAL_GRPO_START_UTC'],assigned_gpus=os.environ['CUDA_VISIBLE_DEVICES'],reward_contract=CONTRACT,source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
         python=sys.executable,ld_preload=os.environ['LD_PRELOAD'],
         nccl_sha256=hashlib.sha256(Path(os.environ['NCCL_LIBRARY']).read_bytes()).hexdigest(),
         versions={p:importlib.metadata.version(p) for p in ('torch','transformers','deepspeed','ray','vllm')},
         data_files_sha256={name:hashlib.sha256(Path('new/local_data/social_runs/b_grpo_data_v2', name).read_bytes()).hexdigest() for name in ('train.jsonl','validation.jsonl','test.jsonl')},
         data_manifest=json.loads(Path('new/local_data/social_runs/b_grpo_data_v2/manifest.json').read_text()))
(out/'run_manifest.json').write_text(json.dumps(obj,indent=2)+'\n')
RECORD
"$PYTHON" -u examples/start_rlvr_pipeline.py --config_path social_b --config_name grpo 2>&1 | tee outputs/social_b_grpo_b_r3/driver.log
