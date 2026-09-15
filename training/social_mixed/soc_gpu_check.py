"""Short, model-free allocated-rank CUDA/NCCL test in a disposable subprocess."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from training.social_mixed.hardware import PROFILES
def gpu_count():
 return PROFILES[os.environ.get('SOCIAL_GPU_PROFILE','h100-96')]['gpus']

def run(root):
 root=Path(root)
 with (root/'gpu_topology.log').open('w') as log:
  for args in (['nvidia-smi','-L'],['nvidia-smi','topo','-m']):
   subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=15)
 command=[sys.executable,'-m','torch.distributed.run','--standalone','--nnodes=1',f'--nproc-per-node={gpu_count()}','--module','training.social_mixed.soc_gpu_check']
 with (root/'nccl_preflight.log').open('w') as log:
  subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
 print('ALLOCATED_RANK_NCCL_PREFLIGHT_PASSED',flush=True)

def main():
 import torch
 import torch.distributed as dist
 rank=int(os.environ['LOCAL_RANK']);count=torch.cuda.device_count()
 print(json.dumps(dict(rank=rank,visible=os.environ.get('CUDA_VISIBLE_DEVICES'),device_count=count)),flush=True)
 if count!=gpu_count():raise RuntimeError('Each rank must enumerate all assigned GPUs; inspect allocation/MIG topology')
 torch.cuda.set_device(rank);p=torch.cuda.get_device_properties(rank)
 profile=os.environ.get('SOCIAL_GPU_PROFILE','h100-96')
 minimum={'h100-47':42,'h100-96':85,'h200-141':125}[profile]
 if p.total_memory<minimum*1024**3:raise RuntimeError(f'{profile} profile requires at least {minimum} GiB per visible device')
 print(json.dumps(dict(rank=rank,name=p.name,memory=p.total_memory,uuid=str(getattr(p,'uuid',None)))),flush=True)
 dist.init_process_group('nccl',timeout=datetime.timedelta(seconds=30))
 try:
  x=torch.tensor([rank+1.],device='cuda');dist.all_reduce(x)
  if x.item()!=count*(count+1)/2:raise RuntimeError('Incorrect NCCL reduction')
  print(f'NCCL_ALL_REDUCE_PASSED rank={rank}',flush=True)
 finally:dist.destroy_process_group()
if __name__=='__main__':main()
