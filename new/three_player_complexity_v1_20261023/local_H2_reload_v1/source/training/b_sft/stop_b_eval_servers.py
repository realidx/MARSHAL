"""Stop only the four recorded social-base evaluation servers on selected GPUs."""
import os
from pathlib import Path
import signal
import time

selected=set(os.environ.get('SOCIAL_GRPO_GPUS','4,5,6,7').split(','))
pids=[]
for port in range(8000,8004):
    record=Path(f'outputs/logs/social_vllm_{port}.pid')
    if not record.exists():continue
    pid=int(record.read_text().strip());proc=Path('/proc')/str(pid)
    if not proc.exists():continue
    args=proc.joinpath('cmdline').read_bytes().decode().split('\0')
    env=proc.joinpath('environ').read_bytes().split(b'\0')
    gpu=next((x.decode().split('=',1)[1] for x in env if x.startswith(b'CUDA_VISIBLE_DEVICES=')),None)
    def option(name,value):return name in args and args[args.index(name)+1]==value
    if proc.stat().st_uid!=os.getuid() or 'vllm.entrypoints.openai.api_server' not in args or not option('--served-model-name','social-base') or not option('--port',str(port)) or gpu not in selected:
        raise SystemExit(f'Recorded PID {pid} does not match the expected evaluation server; no shutdown performed.')
    pids.append((pid,port,gpu))
for pid,port,gpu in pids:
    os.kill(pid,signal.SIGTERM);print(f'Stopping social-base port {port}, GPU {gpu}, PID {pid}',flush=True)
for _ in range(60):
    if not any(Path(f'/proc/{pid}').exists() for pid,_,_ in pids):break
    time.sleep(1)
print('Shutdown requested. Training launcher separately checks GPU memory before starting.')
