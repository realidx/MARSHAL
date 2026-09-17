"""Start two owned local Q0 servers for a development C2C plan, then clean up."""
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
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',type=Path,default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    parser.add_argument('--ports',type=int,nargs=2,default=[18095,18096])
    parser.add_argument('--max-model-len',type=int,default=32768)
    parser.add_argument('--max-turns',type=int,default=50)
    parser.add_argument('--parallel-games',type=int,default=4)
    args=parser.parse_args()
    if args.parallel_games<1:parser.error('--parallel-games must be positive')
    gpus=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    if len(gpus)!=2 or any(not g for g in gpus) or len(set(gpus))!=2:
        parser.error('CUDA_VISIBLE_DEVICES must name the two allocated GPUs')
    plan=args.plan.resolve();data=json.loads(plan.read_text())
    if data.get('formal_test') is not False or data.get('stage')!='development':
        raise ValueError('Development plans only')
    if not (args.model/'config.json').is_file():raise FileNotFoundError(args.model)
    if len(set(args.ports))!=2:raise ValueError('Distinct ports required')
    for port in args.ports:
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    config=json.loads(Path(__file__).with_name('c2c_local.json').read_text())
    config['endpoints']['focal']['base_url']=f'http://127.0.0.1:{args.ports[0]}/v1'
    for alias in ('q0','summary'):config['endpoints'][alias]['base_url']=f'http://127.0.0.1:{args.ports[1]}/v1'
    # Both servers load the same checkpoint in this development launcher.
    config['equivalent_replicas']=[dict(config['endpoints'][alias]) for alias in ('focal','q0')]
    routes=out/'routes.json';routes.write_text(json.dumps(config,indent=2)+'\n')
    processes=[];logs=[];commands=[]
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        for index,(gpu,port,name) in enumerate(zip(gpus,args.ports,('social-focal','social-q0'))):
            cmd=[sys.executable,'-u','-m','vllm.entrypoints.openai.api_server','--model',str(args.model.resolve()),
                 '--served-model-name',name,'--host','127.0.0.1','--port',str(port),'--tensor-parallel-size','1',
                 '--dtype','bfloat16','--max-model-len',str(args.max_model_len),'--max-num-seqs','4',
                 '--gpu-memory-utilization','0.65','--disable-frontend-multiprocessing',
                 '--max-seq-len-to-capture',str(args.max_model_len),
                 '--enable-prefix-caching','--disable-log-requests']
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,VLLM_USE_V1='0',VLLM_ATTENTION_BACKEND='XFORMERS',
                     OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',
                     TRITON_CACHE_DIR=str(out/f'triton-{index}'))
            log=(out/f'server-{index}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True));commands.append(cmd)
        (out/'servers.json').write_text(json.dumps(dict(commands=commands,gpus=gpus,pids=[p.pid for p in processes],development_only=True),indent=2)+'\n')
        started=time.monotonic();ready=set();last=-1
        while len(ready)<2:
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
            if len(ready)<2:time.sleep(1)
        subprocess.run([sys.executable,'-m','examples.final_evaluation.c2c_local','run-dev','--plan',str(plan),
                        '--routes',str(routes),'--output',str(out/'games'),'--max-turns',str(args.max_turns),'--parallel-games',str(args.parallel_games)],
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
