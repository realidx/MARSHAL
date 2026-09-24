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
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',choices=['chenjiahao','soc'],default='chenjiahao')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',type=Path,default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    parser.add_argument('--ports',type=int,nargs='+',default=[18105,18106])
    parser.add_argument('--max-tokens',type=int,choices=[768,4096],default=None)
    parser.add_argument('--disable-thinking',action='store_true',help='Use the tokenizer non-thinking template; preserve native JSON thinking')
    parser.add_argument('--max-model-len',type=int,default=32768)
    parser.add_argument('--runner-python',type=Path,default=Path('/raid/chenjiahao/mas/.venv-calbench/bin/python'))
    parser.add_argument('--parallel-games',type=int,default=2)
    parser.add_argument('--max-num-seqs',type=int,default=4)
    parser.add_argument('--disable-chunked-prefill',action='store_true')
    parser.add_argument('--disable-cascade-attn',action='store_true')
    parser.add_argument('--suite',choices=['smoke','structures','formal','stream','shapefactory','shapefactory_native_lite'],default='smoke')
    args=parser.parse_args()
    if args.max_tokens is None:
        args.max_tokens = 4096 if args.suite in ('stream','shapefactory','shapefactory_native_lite') else 768
    if args.parallel_games<1 or args.max_num_seqs<1:parser.error('--parallel-games and --max-num-seqs must be positive')
    gpus=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    allowed=(1,2) if args.runtime=='soc' else (2,)
    if len(gpus) not in allowed or any(not g for g in gpus) or len(set(gpus))!=len(gpus):
        parser.error('CUDA_VISIBLE_DEVICES must name the allocated GPUs (SoC: one or two)')
    if len(args.ports)!=len(gpus) or len(set(args.ports))!=len(args.ports):
        parser.error('Provide one distinct --ports value per allocated GPU')
    if not (args.model/'config.json').is_file():raise FileNotFoundError(args.model)
    if args.disable_thinking:
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(str(args.model),local_files_only=True)
        messages=[dict(role='user',content='Reply with OK.')]
        on=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=True)
        off=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
        if on==off or '<think>\n\n</think>' not in off:
            raise ValueError('Tokenizer does not implement the expected Qwen3 non-thinking switch; stop before evaluation')
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
    if args.disable_thinking:
        config['chat_template_kwargs']={'enable_thinking':False}
        (out/'thinking_template_check.json').write_text(json.dumps(dict(enabled_suffix=on[-200:],disabled_suffix=off[-200:]),indent=2)+'\n')
    routes=out/'routes.json';routes.write_text(json.dumps(config,indent=2)+'\n')
    if args.suite in ('formal','stream','shapefactory','shapefactory_native_lite'):
        if args.max_model_len!=32768 and not (args.suite=='shapefactory_native_lite' and args.max_model_len==98304):
            raise ValueError('Context budget is frozen at 32768 except 98304 for ShapeFactory native Lite')
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
                 '--dtype','bfloat16','--max-model-len',str(args.max_model_len),'--max-num-seqs',str(args.max_num_seqs),
                 '--gpu-memory-utilization','0.65','--enable-prefix-caching']
            if args.disable_chunked_prefill:cmd+=['--no-enable-chunked-prefill']
            if args.disable_cascade_attn:cmd+=['--disable-cascade-attn']
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
        (out/'servers.json').write_text(json.dumps(dict(commands=commands,gpus=gpus,pids=[p.pid for p in processes],development_only=args.suite not in ('formal','stream','shapefactory','shapefactory_native_lite')),indent=2)+'\n')
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
        if args.disable_thinking:
            for index,endpoint in enumerate(config['equivalent_replicas']):
                body=dict(model=endpoint['model'],messages=[dict(role='user',content='Reply with exactly OK.')],
                          temperature=0.0,max_tokens=128,chat_template_kwargs={'enable_thinking':False})
                req=Request(endpoint['base_url']+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=120) as response:probe=json.load(response)
                (out/f'thinking_probe-{index}.json').write_text(json.dumps(dict(request=body,response=probe),indent=2)+'\n')
                answer=probe['choices'][0]['message'].get('content') or ''
                if '<think>' in answer or '</think>' in answer or probe['choices'][0]['finish_reason']=='length':
                    raise RuntimeError('Non-thinking probe emitted think tags or truncated; inspect thinking_probe before proceeding')
            print('Non-thinking template and server probes passed',flush=True)
        if args.suite=='shapefactory_native_lite':
            runner_module='examples.final_evaluation.shapefactory_lite'
            runner_args=['--model',config['equivalent_replicas'][0]['model'],
                         '--base-url',config['equivalent_replicas'][0]['base_url'],
                         '--output',str(out/'games'),'--run']
        else:
            runner_module='examples.final_evaluation.shapefactory_local' if args.suite=='shapefactory' else 'examples.final_evaluation.calbench_local'
            runner_args=['--routes',str(routes),'--output',str(out/'games'),
                         '--parallel-games',str(args.parallel_games)]
            if args.suite!='shapefactory':runner_args+=['--games','2','--suite',args.suite]
        subprocess.run([str(args.runner_python),'-u','-m',runner_module,*runner_args],
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
