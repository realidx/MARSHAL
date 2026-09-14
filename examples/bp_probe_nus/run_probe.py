"""Single-GPU SoC probe launcher. Frozen visible bundle, no teacher dependencies."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ENTRY = Path(__file__).resolve().parent


def verify_bundle(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if set(manifest['files']) != {'requests.jsonl', 'remote_bp_probe.py'}:
        raise ValueError('Unexpected bundle files')
    for name, expected in manifest['files'].items():
        if hashlib.sha256((bundle / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Bundle checksum mismatch: ' + name)
    rows = [json.loads(line) for line in (bundle / 'requests.jsonl').read_text().splitlines()]
    assert len(rows) == 32 and len({r['task_id'] for r in rows}) == 32
    assert Counter(r['task'] for r in rows) == {'B': 16, 'P': 16}
    assert manifest['group_size'] == 2 and manifest['formal_requests'] == 64
    for row in rows:
        req = row['request']
        assert row['output_arm'] == 'action_tools' and req['tools']
        assert req['tool_choice'] == 'auto' and req['parallel_tool_calls'] is False
        assert req['max_tokens'] == 1024 and 'response_format' not in req
        names = {t['function']['name'] for t in req['tools']}
        if row['task'] == 'B':
            assert names == {'SUBMIT_BELIEFS'}
        else:
            assert names <= {'OFFER', 'INVESTIGATE', 'PASS', 'ACCEPT', 'REJECT'}
        for key in ('teacher', 'gold', 'acceptable_actions'):
            assert key not in row
    return manifest, rows


class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, value):
        for stream in self.streams: stream.write(value)
        return len(value)
    def flush(self):
        for stream in self.streams: stream.flush()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def stop_server(server):
    if server is None: return
    # Only the process group created by this launcher; never pkill or reset GPUs.
    try: os.killpg(server.pid, signal.SIGTERM)
    except ProcessLookupError: return
    try: server.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try: os.killpg(server.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        server.wait(timeout=5)


def run(check=False):
    source_bundle = ENTRY / 'bundle'
    manifest, rows = verify_bundle(source_bundle)
    if check:
        print(json.dumps(dict(bundle_verified=True, conditions=len(rows), formal_requests=64,
                              preflight_requests=2, tools_only=True, gpu_started=False)))
        return
    if not (os.environ.get('SLURM_JOB_ID') or os.environ.get('CUDA_VISIBLE_DEVICES')):
        raise ValueError('Run inside a single-GPU allocation; scheduler GPU visibility is preserved')
    model = Path(os.environ.get('BP_MODEL', '/home/e/e1300530/models/Qwen3-4B-Instruct-2507'))
    if not model.is_dir(): raise FileNotFoundError(f'Model missing: {model}; set BP_MODEL')
    import importlib.metadata
    import torch
    from transformers import AutoTokenizer
    if torch.cuda.device_count() != 1:
        raise ValueError('Exactly one scheduler-visible GPU required')
    port = int(os.environ.get('BP_PORT', '18081'))
    workers = int(os.environ.get('BP_WORKERS', '2'))
    memory = float(os.environ.get('BP_GPU_MEMORY', '0.40'))
    context = int(os.environ.get('BP_CONTEXT', '16384'))
    if not (1024 <= port <= 65535 and 1 <= workers <= 4 and 0 < memory <= 1 and context > 1024):
        raise ValueError('Invalid BP_PORT, BP_WORKERS, BP_GPU_MEMORY or BP_CONTEXT')
    with socket.socket() as sock: sock.bind(('127.0.0.1', port))
    # Check full tool-augmented context before allocating the vLLM cache.
    tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
    lengths = [len(tokenizer.apply_chat_template(r['request']['messages'],
        tools=r['request']['tools'], tokenize=True, add_generation_prompt=True)) for r in rows]
    if max(lengths) + 1024 > context:
        raise ValueError(f'Need at least {max(lengths)+1024} context tokens; increase BP_CONTEXT. No input is truncated.')
    root = Path(os.environ.get('BP_RUN_ROOT', str(ENTRY.parents[1] / 'runs/bp_probe_nus')))
    root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=os.environ.get('SLURM_JOB_ID', 'manual') + '.', dir=root))
    print(f'BP_RUN_DIR={run_dir}', flush=True)
    # Freeze the exact launch source too; Git can change while a queued job runs.
    bundle = run_dir / 'bundle'
    bundle.mkdir()
    for name in ('manifest.json', *manifest['files']):
        (bundle / name).write_bytes((source_bundle / name).read_bytes())
    verify_bundle(bundle)
    (run_dir / 'run_probe.py').write_bytes(Path(__file__).read_bytes())
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ENTRY,
                            capture_output=True, text=True).stdout.strip()
    command = [sys.executable, '-m', 'vllm.entrypoints.cli.main', 'serve', str(model),
        '--served-model-name', 'social-base', '--host', '127.0.0.1', '--port', str(port),
        '--tensor-parallel-size', '1', '--dtype', 'bfloat16', '--max-model-len', str(context),
        '--max-num-seqs', str(workers), '--gpu-memory-utilization', str(memory),
        '--enable-auto-tool-choice', '--tool-call-parser', 'hermes']
    save(run_dir / 'server_manifest.json', dict(host=socket.gethostname(),
        job_id=os.environ.get('SLURM_JOB_ID'), commit=commit, python=sys.executable, model=str(model),
        cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'), gpu=torch.cuda.get_device_name(0),
        versions={n: importlib.metadata.version(n) for n in ('torch', 'vllm', 'transformers')},
        command=command, prompt_tokens=lengths, max_prompt_tokens=max(lengths),
        http_workers=workers, parameters_updated=False))
    server = None
    def interrupted(signum, frame): raise SystemExit(128 + signum)
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, interrupted)
    try:
        with (run_dir / 'server.log').open('w') as log:
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        endpoint = f'http://127.0.0.1:{port}/v1'
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('vLLM exited during startup; inspect server.log')
            try:
                with urlopen(endpoint + '/models', timeout=3) as response: models = json.load(response)
            except (OSError, ValueError):
                time.sleep(2)
                continue
            if 'social-base' not in [m['id'] for m in models['data']]:
                raise RuntimeError('Unexpected model at the requested port')
            save(run_dir / 'models.json', models)
            break
        else: raise RuntimeError('vLLM readiness timed out; inspect server.log')
        spec = importlib.util.spec_from_file_location('frozen_bp_sampler', bundle / 'remote_bp_probe.py')
        sampler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sampler)
        for stage, preflight in [('preflight', True), ('probe', False)]:
            print(f'Starting {stage}: {2 if preflight else 64} requests', flush=True)
            with (run_dir / f'{stage}.log').open('w') as log, redirect_stdout(Tee(sys.stdout, log)):
                result = sampler.run(bundle / 'requests.jsonl', run_dir / stage,
                    [endpoint] * workers, 'social-base', preflight=preflight, group_size=2)
            if result['infrastructure_failures']:
                raise RuntimeError(f'{stage} contains infrastructure failures; inspect preserved samples')
        save(run_dir / 'COMPLETE.json', dict(formal_requests=64, preflight_requests=2,
            parameters_updated=False, semantic_scoring='Local, against separately retained teacher labels'))
        print(f'Complete. Download {run_dir} for local scoring and reasoning analysis.', flush=True)
    finally:
        stop_server(server)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate visible bundle without GPU/model/network')
    args = parser.parse_args()
    run(args.check)
