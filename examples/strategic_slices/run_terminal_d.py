"""Launch one allocation-local vLLM server and the terminal D evaluation.

Never submits a Slurm job, downloads weights, or installs packages.
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

from training.strategic_slices.common import digest, file_hash, write_json
from training.strategic_slices.terminal_d import (
    DEFAULT_CONFIG, ROOT, HTTPGenerator, load_config, load_dataset, run_evaluation)


def model_identity(model):
    """Hash the actual local weights, config and tokenizer, not a model alias."""
    required = ('config.json', 'tokenizer_config.json', 'tokenizer.json')
    for name in required:
        if not (model/name).is_file():
            raise FileNotFoundError(model/name)
    index = model/'model.safetensors.index.json'
    if index.exists():
        weights = sorted(set(json.loads(index.read_text())['weight_map'].values()))
    else:
        weights = ['model.safetensors']
    if not weights or any(not (model/name).is_file() for name in weights):
        raise FileNotFoundError('Missing local safetensors weights')
    names = set(required) | set(weights) | {p.name for p in model.glob('*.json')} | {p.name for p in model.glob('*.jinja')}
    hashes = {name:file_hash(model/name) for name in sorted(names)}
    return dict(mock=False, model=str(model), checkpoint_sha256=digest(hashes), files=hashes)


def server_command(cfg, model):
    return [sys.executable, '-m', 'vllm.entrypoints.cli.main', 'serve', str(model),
        '--served-model-name', cfg['served_model'], '--host', '127.0.0.1', '--port', str(cfg['port']),
        '--tensor-parallel-size', str(cfg['tensor_parallel_size']), '--dtype', cfg['dtype'],
        '--max-model-len', str(cfg['context']), '--max-num-seqs', str(cfg['workers']),
        '--gpu-memory-utilization', str(cfg['gpu_memory_utilization']),
        '--enable-auto-tool-choice', '--tool-call-parser', cfg['tool_call_parser']]


def stop_server(server):
    if server is None:
        return
    try:
        os.killpg(server.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        server.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(server.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        server.wait(timeout=5)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    cli.add_argument('--data', type=Path)
    cli.add_argument('--model', type=Path)
    cli.add_argument('--output', type=Path)
    cli.add_argument('--port', type=int)
    cli.add_argument('--resume', action='store_true')
    cli.add_argument('--check', action='store_true')
    args = cli.parse_args()
    cfg = load_config(args.config)
    if args.port is not None:
        cfg['port'] = args.port
    model = args.model or Path(cfg['model'])
    cfg['model'] = str(model)
    dataset = load_dataset(args.data or ROOT/cfg['data'])
    if args.check:
        print(json.dumps(dict(config=cfg, dataset_verified=True, parents=len(dataset.parents),
            candidates=len(dataset.candidates), trajectories=len(dataset.candidates)*cfg['replicas'],
            max_model_calls=sum(r['k']*8 for r in dataset.candidates),
            model_path_checked=False, gpu_started=False, submitted=False), indent=2))
        return
    if args.output is None:
        cli.error('--output is required')
    if not os.environ.get('SLURM_JOB_ID') or not os.environ.get('CUDA_VISIBLE_DEVICES'):
        raise ValueError('Use a Slurm GPU allocation; do not launch on a login node')
    if not (1024 <= cfg['port'] <= 65535):
        raise ValueError('Invalid localhost port')
    import torch
    from transformers import AutoTokenizer
    if torch.cuda.device_count() != 1:
        raise ValueError('Exactly one scheduler-visible GPU required; do not rewrite CUDA_VISIBLE_DEVICES')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', cfg['port']))
    identity = model_identity(model)
    tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
    command = server_command(cfg, model)
    runtime = dict(host=socket.gethostname(), job_id=os.environ['SLURM_JOB_ID'], python=sys.executable,
        cuda_visible_devices=os.environ['CUDA_VISIBLE_DEVICES'], gpu=torch.cuda.get_device_name(0),
        versions={name:importlib.metadata.version(name) for name in ('torch', 'vllm', 'transformers', 'numpy', 'scipy')},
        command=command, model_identity=identity, config=cfg,
        launcher_sha256=file_hash(Path(__file__)), parameters_updated=False, submitted_by_launcher=False)
    # Version/renderer changes invalidate resume, even if the model alias matches.
    identity['runtime_versions'] = runtime['versions']
    identity['launcher_sha256'] = runtime['launcher_sha256']
    out = args.output.resolve()
    if out.exists() and not args.resume:
        raise FileExistsError('Choose a new output directory or explicit --resume')
    out.mkdir(parents=True, exist_ok=True)
    attempt = out/f"attempt-{os.environ['SLURM_JOB_ID']}-{time.time_ns()}"
    attempt.mkdir()
    write_json(attempt/'runtime.json', runtime)
    (attempt/'run_terminal_d.py').write_bytes(Path(__file__).read_bytes())
    endpoint = f"http://127.0.0.1:{cfg['port']}/v1"
    server = None

    def interrupted(signum, frame):
        raise SystemExit(128+signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        with (attempt/'server.log').open('w') as log:
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic()+cfg['startup_timeout_seconds']
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('vLLM exited; inspect attempt server.log')
            try:
                with urlopen(endpoint+'/models', timeout=3) as response:
                    models = json.load(response)
            except (OSError, ValueError):
                time.sleep(2)
                continue
            if cfg['served_model'] not in [m['id'] for m in models['data']]:
                raise RuntimeError('Unexpected model on localhost endpoint')
            write_json(attempt/'models.json', models)
            break
        else:
            raise TimeoutError('vLLM readiness timed out')
        generator = HTTPGenerator(endpoint, cfg['served_model'], cfg, tokenizer, attempt/'transport.jsonl')
        summary = run_evaluation(dataset, cfg, out/'evaluation', generator, identity,
                                 resume=args.resume and (out/'evaluation').exists())
        write_json(attempt/'COMPLETE.json', dict(summary_sha256=file_hash(out/'evaluation/summary.json'),
                                                trajectories=summary['trajectories']))
    except BaseException as exc:
        write_json(attempt/'FAILED.json', dict(error=repr(exc)))
        raise
    finally:
        stop_server(server)


if __name__ == '__main__':
    main()
