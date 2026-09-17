"""Start two owned replicas for a CalBench evaluation, then clean up."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',choices=['chenjiahao','soc'],default='chenjiahao')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',type=Path,default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    parser.add_argument('--ports',type=int,nargs='+',default=[18105,18106])
    parser.add_argument('--max-tokens',type=int,choices=[768,4096],default=768)
    parser.add_argument('--max-model-len',type=int,default=32768)
    parser.add_argument('--runner-python',type=Path,default=Path('/raid/chenjiahao/mas/.venv-calbench/bin/python'))
    parser.add_argument('--parallel-games',type=int,default=2)
    parser.add_argument('--suite',choices=['smoke','structures','formal'],default='smoke')
    args=parser.parse_args()
    if args.parallel_games<1:parser.error('--parallel-games must be positive')
    gpus=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    allowed=(1,2) if args.runtime=='soc' else (2,)
    if len(gpus) not in allowed or any(not g for g in gpus) or len(set(gpus))!=len(gpus):
        parser.error('CUDA_VISIBLE_DEVICES must name the allocated GPUs (SoC: one or two)')
    if len(args.ports)!=len(gpus) or len(set(args.ports))!=len(args.ports):
        parser.error('Provide one distinct --ports value per allocated GPU')
    if not (args.model/'config.json').is_file():raise FileNotFoundError(args.model)
    for port in args.ports:
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    config=dict(local_only=True,temperature=0.0,max_tokens=args.max_tokens,timeout_seconds=600 if args.max_tokens>768 else 120,endpoints={
        'focal':dict(model='social-focal'), 'q0':dict(model='social-q0')})
    config['endpoints']['focal']['base_url']=f'http://127.0.0.1:{args.ports[0]}/v1'
    for alias in ('q0',):config['endpoints'][alias]['base_url']=f'http://127.0.0.1:{args.ports[-1]}/v1'
    config['equivalent_replicas']=[dict(model=f'social-replica-{i}',base_url=f'http://127.0.0.1:{port}/v1') for i,port in enumerate(args.ports)]
    config['endpoints']['focal']=dict(config['equivalent_replicas'][0])
    config['endpoints']['q0']=dict(config['equivalent_replicas'][-1])
    config['execution_protocol']=f'reasoning-separated-v2-tokens-{args.max_tokens}'
    routes=out/'routes.json';routes.write_text(json.dumps(config,indent=2)+'\n')
    if args.suite=='formal':
        if args.max_model_len!=32768: raise ValueError('Formal context budget is frozen at 32768')
        files={}
        for path in sorted(args.model.rglob('*')):
            if path.is_file() and (path.suffix in ('.json','.safetensors','.jinja') or path.name=='merges.txt'):
                digest=hashlib.sha256()
                with path.open('rb') as f:
                    for block in iter(lambda:f.read(8*1024*1024),b''): digest.update(block)
                files[str(path.relative_to(args.model))]=dict(sha256=digest.hexdigest(),bytes=path.stat().st_size)
        versions={}
        for package in ('vllm','torch','transformers','tokenizers'):
            try: versions[package]=importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: versions[package]=None
        scripts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
        (out/'execution_identity.json').write_text(json.dumps(dict(model=str(args.model.resolve()),files=files,versions=versions,scripts=scripts),indent=2)+'\n')
    ptxas=None
    if args.runtime=='chenjiahao':
        ptxas=Path(os.environ.get('TRITON_PTXAS_PATH', str(Path(os.environ.get('CUDA_HOME','/home/chenjiahao/cuda-11.8'))/'bin/ptxas')))
        if not ptxas.is_file() or not os.access(ptxas,os.X_OK):
            raise FileNotFoundError(f'Set TRITON_PTXAS_PATH to an executable compatible ptxas: {ptxas}')
    runtime_env=dict(runtime=args.runtime,CUDA_HOME=os.environ.get('CUDA_HOME'),
                     CONDA_PREFIX=os.environ.get('CONDA_PREFIX'),CUDA_VISIBLE_DEVICES=gpus)
    if ptxas:
        runtime_env.update(TRITON_PTXAS_PATH=str(ptxas.resolve()),
            ptxas_version=subprocess.check_output([str(ptxas),'--version'],text=True))
    else:
        runtime_env.update(TRITON_PTXAS_PATH='vLLM/Triton default',enforce_eager=True)
        if importlib.metadata.version('vllm').split('+')[0]!='0.28.0':
            raise RuntimeError('SoC adapter targets vLLM 0.28.0; inspect a different version before running')
    (out/'runtime_environment.json').write_text(json.dumps(runtime_env,indent=2)+'\n')
    processes=[];logs=[];commands=[]
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        for index,(gpu,port,name) in enumerate(zip(gpus,args.ports,[f'social-replica-{i}' for i in range(len(gpus))])):
            cmd=[sys.executable,'-u','-m','vllm.entrypoints.openai.api_server','--model',str(args.model.resolve()),
                 '--served-model-name',name,'--host','127.0.0.1','--port',str(port),'--tensor-parallel-size','1',
                 '--dtype','bfloat16','--max-model-len',str(args.max_model_len),'--max-num-seqs','4',
                 '--gpu-memory-utilization','0.65','--enable-prefix-caching']
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,
                     OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',
                     TRITON_CACHE_DIR=str(out/f'triton-{index}'))
            if args.runtime=='soc':
                cmd+=['--enforce-eager']
                for key in ('VLLM_USE_V1','VLLM_ATTENTION_BACKEND','TRITON_PTXAS_PATH'):
                    env.pop(key,None)
            else:
                cmd+=['--disable-frontend-multiprocessing','--max-seq-len-to-capture',str(args.max_model_len),'--disable-log-requests']
                env.update(VLLM_USE_V1='0',VLLM_ATTENTION_BACKEND='XFORMERS',TRITON_PTXAS_PATH=str(ptxas.resolve()))
            log=(out/f'server-{index}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True));commands.append(cmd)
        (out/'servers.json').write_text(json.dumps(dict(commands=commands,gpus=gpus,pids=[p.pid for p in processes],development_only=args.suite!='formal'),indent=2)+'\n')
        started=time.monotonic();ready=set();last=-1
        while len(ready)<len(gpus):
            for index,(proc,port) in enumerate(zip(processes,args.ports)):
                if proc.poll() is not None:raise RuntimeError(f'Server {index} exited; inspect its log')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:json.load(response)
                    ready.add(index)
                except OSError:pass
            elapsed=time.monotonic()-started
            if elapsed>1200:raise TimeoutError('Server startup exceeded 1200 seconds')
            if int(elapsed//30)!=last:
                last=int(elapsed//30);print(f'Startup {elapsed:.0f}s ready={sorted(ready)}',flush=True)
            if len(ready)<len(gpus):time.sleep(1)
        subprocess.run([str(args.runner_python),'-u','-m','examples.final_evaluation.calbench_local',
                        '--routes',str(routes),'--output',str(out/'games'),'--games','2',
                        '--parallel-games',str(args.parallel_games),'--suite',args.suite],
                       cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT)),check=True)
        (out/'EXIT_CODE').write_text('0\n')
    except BaseException as exc:
        (out/'EXIT_CODE').write_text('1\n');(out/'LAUNCH_FAILED.json').write_text(json.dumps(dict(error_type=type(exc).__name__,error=str(exc)))+'\n');raise
    finally:
        for proc in processes:
            if proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for proc in processes:
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
        for log in logs:log.close()

if __name__=='__main__':main()
