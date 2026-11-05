"""Bounded two-GPU CUDA/NCCL diagnostic: no Ray, model loading, or package changes."""
import argparse
import ctypes
from datetime import timedelta
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback


def loaded_libraries():
    maps=Path('/proc/self/maps')
    if not maps.exists():return []
    return sorted({line.split()[-1] for line in maps.read_text().splitlines()
                   if '/' in line and any(name in line for name in ('libcuda','libnccl','libnvidia'))})


def write(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def worker(rank,gpu,endpoint,root):
    os.environ.update(CUDA_VISIBLE_DEVICES=gpu,RANK=str(rank),LOCAL_RANK='0',WORLD_SIZE='2')
    record=dict(rank=rank,gpu=gpu,pid=os.getpid(),stage='import_torch',status='running')
    path=Path(root)/f'rank-{rank}.json'
    def stage(name):
        record.update(stage=name,loaded_libraries=loaded_libraries());write(path,record)
    try:
        stage('import_torch')
        import torch
        import torch.distributed as dist
        record.update(torch=torch.__version__,torch_cuda=torch.version.cuda,nccl=torch.cuda.nccl.version())
        stage('single_gpu_cuda')
        torch.cuda.set_device(0)
        value=torch.ones(32,device='cuda').sum()
        torch.cuda.synchronize()
        assert value.item()==32
        record['single_gpu_cuda_passed']=True
        record['gpu_name']=torch.cuda.get_device_name(0)
        # Ask each actually loaded runtime for its version, without loading new libraries.
        record['cuda_runtime_versions']={}
        for library in loaded_libraries():
            if 'libcudart' in library and Path(library).is_file():
                version=ctypes.c_int()
                code=ctypes.CDLL(library).cudaRuntimeGetVersion(ctypes.byref(version))
                record['cuda_runtime_versions'][library]=dict(return_code=code,version=version.value)
        stage('nccl_init')
        dist.init_process_group('nccl',init_method=endpoint,rank=rank,world_size=2,timeout=timedelta(seconds=45))
        for dtype in (torch.float32,torch.bfloat16):
            stage('all_reduce_'+str(dtype))
            tensor=torch.full((65536,),rank+1,dtype=dtype,device='cuda')
            dist.all_reduce(tensor)
            torch.cuda.synchronize()
            if not torch.all(tensor==3).item():raise RuntimeError('NCCL reduction returned incorrect values')
        dist.destroy_process_group()
        record['status']='passed';stage('complete')
    except BaseException as exc:
        record.update(status='failed',error=repr(exc),traceback=traceback.format_exc())
        stage(record['stage'])
        raise


def command(args):
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=10)
        return dict(command=args,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
    except (OSError,subprocess.TimeoutExpired) as exc:return dict(command=args,error=repr(exc))


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',required=True,type=Path)
    cli.add_argument('--gpus',default=os.environ.get('BP_GPUS',os.environ.get('CUDA_VISIBLE_DEVICES','6,7')))
    args=cli.parse_args();gpus=args.gpus.split(',')
    if len(gpus)!=2 or any(not gpu.strip() for gpu in gpus) or gpus[0]==gpus[1]:
        cli.error('Provide exactly two distinct assigned GPU IDs')
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    # Match the communication options in grpo.yaml; never disable P2P as a workaround.
    os.environ.update(NCCL_CUMEM_ENABLE='0',NCCL_NVLS_ENABLE='0',NCCL_SOCKET_IFNAME='lo',
                      GLOO_SOCKET_IFNAME='lo',NCCL_DEBUG='INFO',NCCL_DEBUG_SUBSYS='INIT,ENV,NET,GRAPH,ALLOC',
                      NCCL_DEBUG_FILE=str(root/'nccl.%h.%p.log'),OMP_NUM_THREADS='4')
    packages=('torch','vllm','deepspeed','ray','nvidia-nccl-cu11','nvidia-nccl-cu12',
              'nvidia-cuda-runtime-cu11','nvidia-cuda-runtime-cu12')
    versions={}
    for name in packages:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    env={k:v for k,v in os.environ.items() if k.startswith(('NCCL_','CUDA_','GLOO_')) or k in ('LD_LIBRARY_PATH','LD_PRELOAD','PATH')}
    write(root/'environment.json',dict(python=sys.executable,gpus=gpus,versions=versions,environment=env,
        nvidia_smi=command(['nvidia-smi','--query-gpu=index,name,driver_version,memory.used,memory.total','--format=csv']),
        disks=command(['df','-h','/tmp','/raid/chenjiahao','/dev/shm'])))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    context=multiprocessing.get_context('spawn')
    processes=[context.Process(target=worker,args=(rank,gpu,f'tcp://127.0.0.1:{port}',str(root))) for rank,gpu in enumerate(gpus)]
    try:
        for process in processes:process.start()
        deadline=time.monotonic()+100
        while any(p.is_alive() for p in processes) and time.monotonic()<deadline:
            if any(p.exitcode not in (None,0) for p in processes):break
            time.sleep(.2)
    finally:
        for process in processes:
            if process.is_alive():process.terminate()
        for process in processes:
            if process.pid is not None:
                process.join(timeout=5)
                if process.is_alive():process.kill();process.join(timeout=5)
    rows=[json.loads(p.read_text()) for p in sorted(root.glob('rank-*.json'))]
    dependencies={library:command(['ldd',library]) for row in rows for library in row['loaded_libraries']
                  if 'libnccl' in library and Path(library).is_file()}
    passed=len(rows)==2 and all(r['status']=='passed' for r in rows) and all(p.exitcode==0 for p in processes)
    result=dict(status='passed' if passed else 'failed',exitcodes=[p.exitcode for p in processes],
                stages=[dict(rank=r['rank'],stage=r['stage'],status=r['status']) for r in rows],nccl_dependencies=dependencies)
    write(root/'result.json',result)
    print(json.dumps(dict(status=result['status'],stages=result['stages'],output=str(root)),indent=2),flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
