"""Two-GPU SoC launcher: focal checkpoint on GPU 0, frozen Q0 on GPU 1."""
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
from examples.final_evaluation.benac_a_suite import ROOT, load


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--q0',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--ports',type=int,nargs=2,required=True)
    p.add_argument('--stage',choices=['smoke','formal'],default='smoke');p.add_argument('--parallel-games',type=int,default=4)
    a=p.parse_args();load()
    cards=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    if len(cards)!=2 or len(set(cards))!=2 or not all(cards):p.error('Exactly two allocated CUDA devices required')
    if importlib.metadata.version('vllm').split('+')[0]!='0.28.0':raise RuntimeError('Expected existing SoC vLLM 0.28.0 environment')
    for path in (a.model,a.q0):
        if not (path/'config.json').is_file():raise FileNotFoundError(path)
    if len(set(a.ports))!=2:p.error('Distinct ports required')
    for port in a.ports:
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    routes={role:dict(base_url=f'http://127.0.0.1:{port}/v1',model=f'benac-{role}') for role,port in zip(('focal','q0'),a.ports)}
    (out/'routes.json').write_text(json.dumps(routes,indent=2)+'\n')
    identity={}
    for role,path in [('focal',a.model),('q0',a.q0)]:
        files={}
        for f in sorted(path.rglob('*')):
            if f.is_file() and (f.suffix in ('.json','.safetensors','.jinja') or f.name=='merges.txt'):
                h=hashlib.sha256()
                with f.open('rb') as stream:
                    for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
                files[str(f.relative_to(path))]=h.hexdigest()
        identity[role]=dict(path=str(path.resolve()),files=files)
    identity['versions']={name:importlib.metadata.version(name) for name in ('vllm','torch','transformers')}
    identity['evaluation_scripts']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(__file__).parent.glob('*benac_a*.py')}
    (out/'execution_identity.json').write_text(json.dumps(identity,indent=2)+'\n')
    procs=[];logs=[];commands=[]
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        for i,(role,model,port,card) in enumerate(zip(('focal','q0'),(a.model,a.q0),a.ports,cards)):
            cmd=[sys.executable,'-u','-m','vllm.entrypoints.openai.api_server','--model',str(model.resolve()),
                 '--served-model-name',f'benac-{role}','--host','127.0.0.1','--port',str(port),
                 '--tensor-parallel-size','1','--dtype','bfloat16','--max-model-len','32768','--max-num-seqs','8',
                 '--gpu-memory-utilization','0.7','--enable-prefix-caching','--enforce-eager',
                 '--enable-auto-tool-choice','--tool-call-parser','hermes']
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=card,TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='4')
            for key in ('VLLM_USE_V1','VLLM_ATTENTION_BACKEND','TRITON_PTXAS_PATH'):env.pop(key,None)
            log=(out/f'server-{role}.log').open('w');logs.append(log)
            procs.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True));commands.append(cmd)
        (out/'servers.json').write_text(json.dumps(dict(commands=commands,gpus=cards,pids=[p.pid for p in procs]),indent=2)+'\n')
        start=time.monotonic();ready=set();last=-1
        while len(ready)<2:
            for i,(proc,port) in enumerate(zip(procs,a.ports)):
                if proc.poll() is not None:raise RuntimeError(f'Server {i} exited; inspect logs')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:json.load(response)
                    ready.add(i)
                except OSError:pass
            elapsed=time.monotonic()-start
            if elapsed>1200:raise TimeoutError('Startup exceeded 1200s')
            if int(elapsed//30)!=last:last=int(elapsed//30);print(f'Startup {elapsed:.0f}s ready={sorted(ready)}',flush=True)
            if len(ready)<2:time.sleep(1)
        subprocess.run([sys.executable,'-u','-m','examples.final_evaluation.benac_a','--routes',str(out/'routes.json'),
                        '--output',str(out/'games'),'--stage',a.stage,'--parallel-games',str(a.parallel_games)],cwd=ROOT,check=True)
        (out/'EXIT_CODE').write_text('0\n')
    except BaseException as exc:
        (out/'EXIT_CODE').write_text('1\n');(out/'LAUNCH_FAILED.json').write_text(json.dumps(dict(error=repr(exc))))
        raise
    finally:
        for proc in procs:
            if proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for proc in procs:
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
        for log in logs:log.close()

if __name__=='__main__':main()
