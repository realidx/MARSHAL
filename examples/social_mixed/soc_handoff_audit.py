"""Read-only SoC handoff capture. No models, installs, Ray head or HTTP server.

Run with the activated target environment from the actual remote checkout:
  python /path/to/soc_handoff_audit.py --repo "$PWD" --output /tmp/soc-handoff
Use --gpu only inside an allocated two-GPU Slurm job.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

PACKAGES=('torch','vllm','transformers','ray','megatron-core','transformer-engine',
          'transformer-engine-torch','flash-attn','accelerate','tensordict','numpy','pydantic')
ROOTS=('roll','mcore_adapter/src','training/social_mixed','training/b_sft','examples/social_mixed')

def command(args,cwd,timeout=60):
 try:
  p=subprocess.run(args,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
  return dict(argv=args,exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr)
 except (OSError,subprocess.TimeoutExpired) as e:return dict(argv=args,error=str(e))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--gpu',action='store_true');a=p.parse_args()
 repo=a.repo.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 if not (repo/'examples/social_mixed/sbatch_train.sh').is_file():raise ValueError('Not the social training checkout')
 versions={}
 for name in PACKAGES:
  try:versions[name]=importlib.metadata.version(name)
  except importlib.metadata.PackageNotFoundError:versions[name]=None
 report=dict(repo=str(repo),python=sys.executable,python_version=sys.version,versions=versions,
  environment={k:os.environ.get(k) for k in ('CONDA_PREFIX','CUDA_HOME','CUDA_VISIBLE_DEVICES','ROLL_ASSIGNED_CUDA_DEVICES','RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES','VLLM_USE_V1','VLLM_TOOL_CALL_PARSER','LD_LIBRARY_PATH','PYTHONPATH','NCCL_SOCKET_IFNAME','GLOO_SOCKET_IFNAME')})
 report['git']=command(['git','status','--short'],repo)
 report['nvcc']=command(['nvcc','--version'],repo)
 # Preserve the exact remote adapter/launcher, including untracked Python files.
 files={}
 with tarfile.open(out/'runtime-source.tar.gz','w:gz') as tar:
  for root in ROOTS:
   for f in sorted((repo/root).rglob('*')):
    if f.is_file() and not f.is_symlink() and '__pycache__' not in f.parts and f.suffix in ('.py','.sh','.yaml','.yml'):
     rel=str(f.relative_to(repo));files[rel]=hashlib.sha256(f.read_bytes()).hexdigest();tar.add(f,arcname=rel,recursive=False)
 report['source_sha256']=files
 # Import independently so one missing dependency cannot hide the others.
 modules=('vllm.tool_parsers.hermes_tool_parser','roll.third_party.vllm',
          'roll.distributed.strategy.megatron_strategy','roll.distributed.strategy.vllm_strategy',
          'training.social_mixed.pipeline')
 report['imports']={}
 for module in modules:
  code='import importlib; m=importlib.import_module('+repr(module)+'); print(m.__file__); print(getattr(m,"LLM",None))'
  report['imports'][module]=command([sys.executable,'-c',code],repo,60)
 if a.gpu:
  report['nvidia_smi']=command(['nvidia-smi','-L'],repo)
  report['topology']=command(['nvidia-smi','topo','-m'],repo)
  # Separate process exits before training: no residual model or CUDA contexts.
  script=out/'nccl_probe.py'
  script.write_text('''import datetime,json,os,torch
import torch.distributed as dist
rank=int(os.environ['LOCAL_RANK'])
count=torch.cuda.device_count()
print(json.dumps(dict(rank=rank,visible=os.environ.get('CUDA_VISIBLE_DEVICES'),device_count=count)),flush=True)
assert count==2, 'Each rank must enumerate two assigned CUDA devices'
torch.cuda.set_device(rank)
p=torch.cuda.get_device_properties(rank)
print(json.dumps(dict(rank=rank,name=p.name,memory=p.total_memory,uuid=str(getattr(p,'uuid',None)))),flush=True)
dist.init_process_group('nccl',timeout=datetime.timedelta(seconds=30))
x=torch.tensor([rank+1.],device='cuda')
dist.all_reduce(x)
assert x.item()==3., x
print('NCCL_ALL_REDUCE_PASSED rank='+str(rank),flush=True)
dist.destroy_process_group()
''')
  report['nccl']=command([sys.executable,'-m','torch.distributed.run','--standalone','--nnodes=1','--nproc-per-node=2',str(script)],repo,90)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(dict(output=str(out),source_files=len(files),imports={k:v.get('exit_code',v.get('error')) for k,v in report['imports'].items()},nccl=report.get('nccl',{}).get('exit_code')),indent=2))
if __name__=='__main__':main()
