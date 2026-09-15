"""Start two owned vLLM servers, evaluate against fixed base, then clean up."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--candidate',type=Path,required=True)
    cli.add_argument('--base',type=Path,default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--ports',type=int,nargs=2,default=[18091,18092])
    args=cli.parse_args()
    gpus=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    if len(gpus)!=2 or any(not g for g in gpus) or len(set(gpus))!=2:raise ValueError('Set exactly two allocated GPUs')
    for model in (args.candidate,args.base):
        if not (model/'config.json').is_file():raise FileNotFoundError(model)
    for port in args.ports:
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    if len(set(args.ports))!=2:raise ValueError('Ports must differ')
    args.output.mkdir(parents=True,exist_ok=False)
    processes=[];logs=[];commands=[]
    def interrupted(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        for i,(gpu,model,name,port) in enumerate(zip(gpus,(args.candidate,args.base),('social-learner','social-base'),args.ports)):
            cmd=[sys.executable,'-u','-m','vllm.entrypoints.openai.api_server','--model',str(model.resolve()),
                 '--served-model-name',name,'--host','127.0.0.1','--port',str(port),'--tensor-parallel-size','1',
                 '--dtype','bfloat16','--max-model-len','4096','--max-num-seqs','16','--gpu-memory-utilization','0.65',
                 '--disable-frontend-multiprocessing','--enable-auto-tool-choice','--tool-call-parser','hermes']
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,VLLM_USE_V1='0',VLLM_ATTENTION_BACKEND='XFORMERS',
                     TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',
                     TRITON_CACHE_DIR=str((args.output/f'triton-{i}').resolve()))
            log=(args.output/f'server-{i}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
            commands.append(cmd)
        (args.output/'servers.json').write_text(json.dumps(dict(commands=commands,gpus=gpus,pids=[p.pid for p in processes]),indent=2)+'\n')
        start=time.monotonic();ready=set();reported=-1
        while len(ready)<2:
            for i,(p,port) in enumerate(zip(processes,args.ports)):
                if p.poll() is not None:raise RuntimeError(f'Server {i} exited: inspect server-{i}.log')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:
                        json.load(response);ready.add(i)
                except OSError:pass
            elapsed=time.monotonic()-start
            if elapsed>1200:raise TimeoutError('vLLM startup exceeded 1200 seconds')
            if int(elapsed//30)!=reported:
                reported=int(elapsed//30);print(f'Startup {elapsed:.0f}s ready={sorted(ready)}',flush=True)
            if len(ready)<2:time.sleep(1)
        subprocess.run([sys.executable,'-u','-m','training.social_mixed.evaluate',
            '--learner-url',f'http://127.0.0.1:{args.ports[0]}/v1',
            '--opponent-url',f'http://127.0.0.1:{args.ports[1]}/v1',
            '--output',str(args.output/'evaluation')],check=True)
    finally:
        for p in processes:
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for p in processes:
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        for log in logs:log.close()


if __name__=='__main__':main()
