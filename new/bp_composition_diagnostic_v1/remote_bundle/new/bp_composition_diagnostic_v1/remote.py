"""Own two vLLM replicas using the previously verified chenjiahao rollout stack."""
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

from prepare import HERE, ROOT, sha
from evaluate import load


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', type=Path, default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ports', type=int, nargs=2, default=[18093, 18094])
    a = p.parse_args()
    os.chdir(ROOT); os.environ['PYTHONPATH'] = str(ROOT)
    load()
    gpus = os.environ.get('CUDA_VISIBLE_DEVICES', '').split(',')
    if len(gpus) != 2 or any(not g.strip() for g in gpus) or len(set(gpus)) != 2:
        raise ValueError('Set exactly two assigned GPUs, e.g. CUDA_VISIBLE_DEVICES=6,7')
    if not (a.model / 'config.json').is_file(): raise FileNotFoundError(a.model)
    if len(set(a.ports)) != 2: raise ValueError('Ports must differ')
    for port in a.ports:
        with socket.socket() as sock: sock.bind(('127.0.0.1', port))
    a.output.mkdir(parents=True, exist_ok=False)
    processes = []; logs = []; monitor = None; commands = []
    def interrupted(signum, frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    try:
        # Same tokenizer/tool template as the served checkpoint; no weight loading.
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(a.model), local_files_only=True)
        _, _, frozen_requests = load()
        counts = {}
        for tid, row in frozen_requests.items():
            req = row['request']
            ids = tokenizer.apply_chat_template(req['messages'], tools=req['tools'],
                                                tokenize=True, add_generation_prompt=True)
            counts[tid] = len(ids)
            if len(ids) + req['max_tokens'] > 4096:
                raise ValueError(f'Context budget exceeded for {tid}: {len(ids)} + {req["max_tokens"]}')
        (a.output / 'prompt_tokens.json').write_text(json.dumps(counts, indent=2) + '\n')
        for i, (gpu, port) in enumerate(zip(gpus, a.ports)):
            cmd = [sys.executable, '-u', '-m', 'vllm.entrypoints.openai.api_server',
                '--model', str(a.model.resolve()), '--served-model-name', 'bp-composition',
                '--host', '127.0.0.1', '--port', str(port), '--tensor-parallel-size', '1',
                '--dtype', 'bfloat16', '--max-model-len', '4096', '--max-num-seqs', '16',
                '--gpu-memory-utilization', '0.65', '--disable-frontend-multiprocessing',
                '--enable-auto-tool-choice', '--tool-call-parser', 'hermes']
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu, VLLM_USE_V1='0',
                VLLM_ATTENTION_BACKEND='XFORMERS', TOKENIZERS_PARALLELISM='false',
                OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1',
                TRITON_CACHE_DIR=str((a.output / f'triton-{i}').resolve()))
            log = (a.output / f'server-{i}.log').open('w'); logs.append(log)
            processes.append(subprocess.Popen(cmd, env=env, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)); commands.append(cmd)
        (a.output / 'servers.json').write_text(json.dumps(dict(commands=commands, gpus=gpus,
            pids=[proc.pid for proc in processes], python=sys.executable,
            diagnostic_manifest_sha256=sha(HERE / 'manifest.json'),
            note='Both servers load the same checkpoint; no separate opponent or self-play in this diagnostic.'), indent=2) + '\n')
        gpu_log = (a.output / 'gpu.csv').open('w'); logs.append(gpu_log)
        monitor = subprocess.Popen(['nvidia-smi', '--id=' + ','.join(gpus),
            '--query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total,power.draw',
            '--format=csv', '-l', '5'], stdout=gpu_log, stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic(); ready = set(); reported = -1
        while len(ready) < 2:
            for i, (proc, port) in enumerate(zip(processes, a.ports)):
                if proc.poll() is not None: raise RuntimeError(f'Server {i} exited; inspect server-{i}.log')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2) as response:
                        data = json.load(response)
                        if any(row['id'] == 'bp-composition' for row in data['data']): ready.add(i)
                except OSError: pass
            elapsed = time.monotonic() - started
            if elapsed > 1200: raise TimeoutError('vLLM startup exceeded 1200 seconds')
            if int(elapsed // 30) != reported:
                reported = int(elapsed // 30); print(f'Startup {elapsed:.0f}s ready={sorted(ready)}', flush=True)
            if len(ready) < 2: time.sleep(1)
        (a.output / 'startup.json').write_text(json.dumps(dict(seconds=time.monotonic() - started)) + '\n')
        subprocess.run([sys.executable, '-u', str(HERE / 'run.py'), '--base-url',
            *[f'http://127.0.0.1:{port}/v1' for port in a.ports], '--model', 'bp-composition',
            '--output', str(a.output / 'evaluation'), '--temperature', '1.0', '--top-p', '1.0',
            '--top-k', '-1', '--concurrency-per-endpoint', '16', '--repeats', '8'], check=True)
    except BaseException as exc:
        (a.output / 'LAUNCH_FAILED.json').write_text(json.dumps(dict(error_type=type(exc).__name__, message=str(exc))) + '\n')
        raise
    finally:
        owned = processes + ([monitor] if monitor else [])
        for proc in owned:
            if proc.poll() is None:
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        for proc in owned:
            try: proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait()
        for log in logs: log.close()


if __name__ == '__main__':
    main()
