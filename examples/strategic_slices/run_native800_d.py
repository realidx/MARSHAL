"""Remote native800 D launcher, standalone GPU or existing OpenAI-compatible vLLM.

No installation, model download, Slurm submission, training or local test mode.
"""
import argparse
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

from .native800.d_runner import (
    ROOT, DEFAULT_CONFIG, REG, VERSION, Dataset, CompressedHTTPGenerator,
    load_config, make_protocol, run_evaluation, atomic)
from .run_terminal_d import model_identity, server_command, stop_server
from training.strategic_slices.common import file_hash


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    cli.add_argument('--data',type=Path)
    cli.add_argument('--pool',type=Path)
    cli.add_argument('--model',type=Path,help='Required local weights/tokenizer directory; no downloads')
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--endpoint',help='Existing compatible /v1 URL; omit to launch local vLLM on allocated GPU')
    cli.add_argument('--served-model',help='Exact model ID served by --endpoint, or name for launched server')
    cli.add_argument('--workers',type=int)
    cli.add_argument('--port',type=int)
    cli.add_argument('--gpu-memory-utilization',type=float)
    cli.add_argument('--resume',action='store_true')
    args = cli.parse_args()
    cfg = load_config(args.config)
    for field in ('workers','port','gpu_memory_utilization','served_model'):
        value = getattr(args,field)
        if value is not None:cfg[field]=value
    if cfg['workers']<1 or not 0<cfg['gpu_memory_utilization']<=1 or not 1024<=cfg['port']<=65535:
        cli.error('Invalid workers, port or GPU memory fraction')
    model = args.model or (Path(cfg['model']) if cfg.get('model') else None)
    if model is None:cli.error('--model is required, including with --endpoint for exact tokenizer/weight identity')
    model = model.resolve()
    cfg['model']=str(model)
    data = (args.data or ROOT/cfg['data']).resolve()
    pool = (args.pool or ROOT/cfg['pool']).resolve()
    cfg['data'],cfg['pool']=str(data),str(pool)
    output = args.output.resolve()
    if output.exists() and not args.resume:
        raise FileExistsError('Choose a fresh output or use --resume')
    if args.resume and not (output/'evaluation/protocol.json').is_file():
        raise FileNotFoundError('No native800 evaluation protocol to resume')
    dataset = Dataset(data,pool,cfg)
    identity = model_identity(model)
    versions = {}
    for package in ('torch','vllm','transformers','numpy','scipy'):
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]='NOT_INSTALLED'
    identity['runtime_versions']=versions
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(model),local_files_only=True)
    endpoint = args.endpoint.rstrip('/') if args.endpoint else f'http://127.0.0.1:{cfg["port"]}/v1'
    protocol = make_protocol(dataset,cfg,identity,endpoint)
    if args.resume and json.loads((output/'evaluation/protocol.json').read_text())!=protocol:
        raise ValueError('Resume model/data/config/source/endpoint mismatch')
    command = None
    gpu = 'EXTERNAL_ENDPOINT_NOT_LOCALLY_INSPECTED'
    if not args.endpoint:
        import torch
        if torch.cuda.device_count()!=1:
            raise ValueError('Expose exactly one allocated GPU; otherwise provide --endpoint')
        gpu = torch.cuda.get_device_name(0)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',cfg['port']))
        command = server_command(cfg,model)
    output.mkdir(parents=True,exist_ok=True)
    attempt = output/f'attempt-{time.time_ns()}'
    attempt.mkdir()
    runtime = dict(version=VERSION,actual_argv=sys.argv,resolved_config=cfg,
        config_file=dict(path=str(args.config.resolve()),sha256=file_hash(args.config)),
        dataset_root=str(data),parent_pool_root=str(pool),model_identity=identity,
        hostname=socket.gethostname(),python=sys.executable,versions=versions,
        gpu=gpu,cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES','NOT_RECORDED'),
        slurm_job_id=os.environ.get('SLURM_JOB_ID','NOT_RECORDED'),endpoint=endpoint,server_command=command,
        registration_sha256=file_hash(REG),model_started_here=not bool(args.endpoint),
        validation='NOT_RUN_BEFORE_REMOTE_BY_USER_REQUEST',training='NOT_STARTED')
    atomic(attempt/'pipeline_snapshot.json',dict(protocol,runtime=runtime))
    server = None
    log = None
    def interrupted(signum,frame):
        raise SystemExit(128+signum)
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,interrupted)
    try:
        if command:
            log = (attempt/'server.log').open('w')
            server = subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True)
        deadline = time.monotonic()+cfg['startup_timeout_seconds']
        while True:
            if server is not None and server.poll() is not None:
                raise RuntimeError(f'vLLM exited with {server.returncode}; see server.log')
            try:
                with urlopen(endpoint+'/models',timeout=3) as response:models=json.load(response)
                break
            except (OSError,ValueError):
                if time.monotonic()>=deadline:raise TimeoutError('Endpoint readiness timed out')
                time.sleep(2)
        if cfg['served_model'] not in [m['id'] for m in models['data']]:
            raise ValueError('Wrong served model; use --served-model matching the endpoint')
        atomic(attempt/'models.json',models)
        generator = CompressedHTTPGenerator(endpoint,cfg['served_model'],cfg,tokenizer,attempt/'transport.jsonl.gz')
        summary = run_evaluation(dataset,cfg,output/'evaluation',generator,identity,endpoint,
            resume=args.resume,argv=sys.argv)
        atomic(attempt/'COMPLETE.json',dict(summary_sha256=file_hash(output/'evaluation/summary.json'),
            trajectories=summary['trajectories']))
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    except BaseException as exc:
        atomic(attempt/'FAILED.json',dict(error=repr(exc),recovery='Fix infrastructure, then explicit --resume with identical config/model/source'))
        raise
    finally:
        stop_server(server)
        if log is not None:log.close()


if __name__=='__main__':main()
