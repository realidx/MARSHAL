#!/usr/bin/env bash
set -euo pipefail
cd /raid/chenjiahao/mas
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export LD_LIBRARY_PATH="/raid/chenjiahao/conda_envs/mas/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
PYTHON=/raid/chenjiahao/conda_envs/mas/bin/python
# Add only missing ROLL dependencies; preserve the working inference stack.
"$PYTHON" - <<'CHECK'
import importlib.metadata as m, subprocess, sys
protected=['torch','vllm','ray','numpy','transformers','deepspeed','nvidia-nccl-cu11','nvidia-nccl-cu12']
def snapshot():
    result={}
    for name in protected:
        try: result[name]=m.version(name)
        except m.PackageNotFoundError: result[name]=None
    return result
before=snapshot()
requirements=['hydra-core==1.3.2','omegaconf==2.3.0','antlr4-python3-runtime==4.9.3',
              'dacite==1.9.2','codetiming==1.4.0','tensordict==0.7.2','orjson==3.12.0','more-itertools==11.1.0']
missing=[]
for req in requirements:
    name,version=req.split('==')
    try:
        actual=m.version(name)
        if actual!=version: raise SystemExit(f'{name} is {actual}; expected {version}. No automatic replacement.')
    except m.PackageNotFoundError: missing.append(req)
if missing: subprocess.run([sys.executable,'-m','pip','install','--no-deps',*missing],check=True)
assert before==snapshot(), 'Protected inference package versions changed'
print('Existing inference packages preserved:',before)
CHECK
"$PYTHON" -m training.b_sft.prepare_b_grpo_nccl
export LD_PRELOAD="$PWD/new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2${LD_PRELOAD:+:$LD_PRELOAD}"
"$PYTHON" -m training.b_sft.check_b_grpo_env
