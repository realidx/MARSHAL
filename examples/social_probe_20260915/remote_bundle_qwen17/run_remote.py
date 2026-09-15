"""User-run two-GPU inference probe. No training or dependency installation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

ENTRY = Path(__file__).resolve().parent


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def verify(bundle):
    manifest = json.loads((bundle/'bundle_manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if Path(name).name != name or hashlib.sha256((bundle/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Bundle checksum mismatch: '+name)
    bp, bridges, resets = [rows(bundle/name) for name in
                          ('bp_requests.jsonl', 'bridges_requests.jsonl', 'selfplay_resets.environment.jsonl')]
    counts = manifest['conditions']
    l0 = rows(bundle/'l0_requests.jsonl') if 'l0' in counts else []
    if len(l0) != counts.get('l0', 0):
        raise ValueError('Wrong L0 selection count')
    if (len(bp), len(bridges), len(resets)) != tuple(counts[k] for k in ('bp', 'bridges', 'selfplay')):
        raise ValueError('Wrong selection counts')
    requests = bp+bridges+l0
    if any(r['split'] not in ('train', 'validation') for r in requests+resets):
        raise ValueError('Unexpected split')
    if len({r['task_id'] for r in requests}) != len(requests) or len({r['group_id'] for r in resets}) != len(resets):
        raise ValueError('Duplicate IDs')
    for r in requests:
        req = r['request']
        if req['max_tokens'] != 1024 or req['tool_choice'] != 'auto' or req['parallel_tool_calls']:
            raise ValueError('Unexpected B/P protocol')
        if any(k in r for k in ('teacher', 'gold', 'acceptable_actions')):
            raise ValueError('Scoring labels in remote requests')
    return manifest, requests, resets


def configure_model(tokenizer, model, manifest, bundle, output):
    """Validate before loading weights; use identical local/server templates."""
    original_hash = hashlib.sha256(str(tokenizer.chat_template).encode()).hexdigest()
    if original_hash != manifest['bp_template_sha256']:
        raise ValueError('Tokenizer chat template differs from the pinned probe model')
    profile = manifest.get('model_profile')
    if not profile:
        return [], dict(original_template_sha256=original_hash)
    for name, digest in profile['model_files_sha256'].items():
        if hashlib.sha256((model/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Model metadata/tokenizer differs from pinned Qwen3-1.7B: '+name)
    template = (bundle/'qwen17_nonthinking.jinja').read_text()
    if hashlib.sha256(template.encode()).hexdigest() != profile['effective_template_sha256']:
        raise ValueError('Nonthinking template checksum mismatch')
    tokenizer.chat_template = template
    config_dir = output/'effective_generation_config'
    config_dir.mkdir()
    shutil.copy2(bundle/'probe_generation_config.json', config_dir/'generation_config.json')
    return ['--chat-template', str((bundle/'qwen17_nonthinking.jinja').resolve()),
            '--generation-config', str(config_dir.resolve())], profile


def load_runtime(bundle, destination):
    spec = importlib.util.spec_from_file_location('probe_unpack', bundle/'unpack_runtime.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    root = module.unpack(bundle/'runtime_v4.tar.gz', bundle/'runtime_v4.sha256', destination)
    sys.path[:0] = [str(root/'runs/outcome_selfplay_screen'), str(root/'third_party/negotiation_benchmark/src'), str(root)]
    import rollout
    return rollout


def stop_server(server):
    # The frontend may have exited while its engine children still hold GPU memory.
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


def wait_ready(server, endpoint, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError('vLLM exited during startup: '+endpoint)
        try:
            with urlopen(endpoint+'/models', timeout=3) as response:
                data = json.load(response)
            if 'social-base' not in [m['id'] for m in data['data']]:
                raise RuntimeError('Wrong model service: '+endpoint)
            return data
        except (OSError, ValueError):
            time.sleep(2)
    raise RuntimeError('vLLM startup timed out: '+endpoint)


def token_count(tokenizer, messages, tools):
    encoded = tokenizer.apply_chat_template(messages, tools=tools, tokenize=True,
                                            add_generation_prompt=True, return_dict=True, truncation=False)
    ids = encoded['input_ids']
    if not isinstance(ids, list) or not ids or not all(isinstance(x, int) for x in ids):
        raise ValueError('Expected flat token IDs')
    return len(ids)


def performance_requests(requests):
    # Fixed input mix across configurations; no outcome-based selection.
    # The first 28 rows are old B/P; the remaining 18 are bridges.
    selected = ([r for r in requests[:28] if r['task']=='B'][:8]
                + [r for r in requests[:28] if r['task']=='P'][:4] + requests[28:32])
    assert len(selected) == 16 and len({r['task_id'] for r in selected}) == 16
    return [dict(r, request=dict(r['request'], seed=int(hashlib.sha256(
        r['task_id'].encode()).hexdigest()[:8], 16) % (2**31))) for r in selected]


def run_performance(args, bundle, requests, endpoints):
    selected = performance_requests(requests)
    path = args.output/'performance_requests.jsonl'
    path.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in selected))
    command = [sys.executable, '-u', str(bundle/'remote_bp_probe.py'),
               '--requests', str(path), '--out', str(args.output/'performance_samples'),
               '--model', 'social-base', '--group-size', '2', '--base-urls',
               *(endpoints*args.workers_per_gpu)]
    # The sampler runs in a child so a deadline also interrupts blocked HTTP threads.
    # Server cleanup in run() cancels remaining generation after the client is stopped.
    start = time.monotonic()
    timed_out = False
    print('Performance only: 32 requests, deadline 360s, no curriculum evaluation.', flush=True)
    try:
        code = subprocess.run(command, timeout=360).returncode
    except subprocess.TimeoutExpired:
        timed_out, code = True, 124
    elapsed = time.monotonic()-start
    samples_path = args.output/'performance_samples/samples.jsonl'
    samples = []
    if samples_path.exists():
        for line in samples_path.read_text().splitlines():
            try:
                samples.append(json.loads(line))
            except ValueError:
                pass  # A deadline may interrupt the last write; preserve original file.
    successful = [r for r in samples if r['status']=='completed']
    tokens = sum((r.get('usage') or {}).get('completion_tokens', 0) for r in successful)
    complete = code == 0 and len(successful) == 32
    result = dict(mode='performance_only', execution=args.execution, workers_per_gpu=args.workers_per_gpu,
                  planned=32, saved=len(samples), completed=len(successful), timed_out=timed_out,
                  client_returncode=code, elapsed_seconds=elapsed, completion_tokens=tokens,
                  saved_output_tokens_per_second=tokens/elapsed,
                  median_request_seconds=statistics.median(r['seconds'] for r in successful) if successful else None,
                  truncated=sum(r.get('finish_reason')=='length' for r in samples), complete=complete,
                  interpretation='Includes first batch and drain, excludes server startup. Incomplete throughput is a lower bound. Fixed repeated seeds for performance only; never mix with reward groups.',
                  request_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), training_started=False)
    save(args.output/'PERFORMANCE.json', result)
    print(json.dumps(result), flush=True)
    return 0 if complete else 2


@contextmanager
def stage_monitor(args, bundle, stage):
    if not args.capture_performance:
        yield
        return
    log = (args.output/f'{stage}-performance.log').open('w')
    process = subprocess.Popen([sys.executable, '-u', str(bundle/'capture_performance.py'),
                                '--run-dir', str(args.output), '--seconds', '60'],
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        yield
    finally:
        # A short stage may end before 60s; retain raw samples without making
        # the next stage wait for monitoring. Missing metrics are not game failures.
        if process.poll() is None:
            stop_server(process)
        log.close()


def run_selfplay(args, rollout, tokenizer, resets, endpoints, bundle):
    counter = iter(range(1000000)); lock = threading.Lock()
    token_lock = threading.Lock()
    class CheckedPolicy(rollout.HTTPPolicy):
        def __call__(self, messages, observation, seed):
            tools = rollout.readable.tools_for(observation)
            with token_lock:
                count = token_count(tokenizer, messages, tools)
            if count+1024 > args.context:
                raise ValueError(f'Context overflow: {count}+1024>{args.context}; input not truncated')
            response = super().__call__(messages, observation, seed)
            response['checked_prompt_tokens'] = count
            return response
    def factory():
        with lock:
            endpoint = endpoints[next(counter)%2]
        return CheckedPolicy(base_url=endpoint, model='social-base', max_tokens=1024, temperature=.7, timeout=180)
    summary, _ = rollout.run_batch(resets, factory, rollouts=4, concurrency=2*args.workers_per_gpu,
                                  seed=42, output_dir=args.output/'selfplay', format_penalty=-.1,
                                  metadata=dict(selection_sha256=hashlib.sha256((bundle/'selfplay_resets.environment.jsonl').read_bytes()).hexdigest(),
                                                split_by_group={r['group_id']:r['split'] for r in resets},
                                                base_urls=endpoints, temperature=.7, max_tokens=1024,
                                                remaining_sampling_parameters=(
                                                    'Pinned baseline defaults: top_p=0.8, top_k=20; effective_generation_config saved'
                                                    if (bundle/'qwen17_profile.json').exists() else
                                                    'vLLM model defaults; generation_config.json saved')))
    return summary


def run_selected_stages(args, sampler, rollout, tokenizer, resets, endpoints, bundle):
    results = {}
    start = time.monotonic()
    for stage in args.stages:
        print('Starting '+stage, flush=True)
        tick = time.monotonic()
        with stage_monitor(args, bundle, stage):
            if stage == 'selfplay':
                result = run_selfplay(args, rollout, tokenizer, resets, endpoints, bundle)
                failed = result['games'] != 4*len(resets) or bool(result['statuses'].get('client_error', 0))
            else:
                result = sampler.run(bundle/f'{stage}_requests.jsonl', args.output/stage,
                                     endpoints*args.workers_per_gpu, 'social-base', group_size=8,
                                     sample_seed_base=args.sampling_seed)
                failed = (result['requests_sent'] != 8*len(rows(bundle/f'{stage}_requests.jsonl'))
                          or bool(result['infrastructure_failures']))
        results[stage] = dict(result=result, seconds=time.monotonic()-tick)
        save(args.output/'stage_results.json', results)
        if failed:
            save(args.output/'INCOMPLETE.json', dict(failed_stage=stage, stages=args.stages,
                 completed_stages=list(results)[:-1], training_started=False))
            return 2
    selfplay = results.get('selfplay', {}).get('result')
    status = dict(stages=args.stages,
                  bp_formal_responses=sum(v['result']['requests_sent'] for k,v in results.items() if k!='selfplay'),
                  formal_responses_by_stage={k:v['result']['requests_sent'] for k,v in results.items() if k!='selfplay'},
                  preflight_responses=4,
                  selfplay_attempts=selfplay['games'] if selfplay else 0,
                  selfplay_statuses=selfplay['statuses'] if selfplay else {},
                  all_games_terminal=selfplay['statuses']=={'terminal':4*len(resets)} if selfplay else None,
                  stage_seconds={k:v['seconds'] for k,v in results.items()},
                  seconds=time.monotonic()-start, test_selected=0, training_started=False,
                  meaning='All selected sampling attempts collected; does not imply correct actions or usable reward variance.')
    save(args.output/'COMPLETE.json', status)
    print(json.dumps(status), flush=True)
    return 0


def run(args):
    manifest, requests, resets = verify(ENTRY)
    if args.check:
        with tempfile.TemporaryDirectory(prefix='social-probe-check-') as temp:
            rollout = load_runtime(ENTRY, temp)
            summary, _ = rollout.run_batch(resets, rollout.ScriptedPolicy, rollouts=1, concurrency=1)
            assert summary['statuses'] == {'terminal': len(resets)} and summary['all_replays_verified']
        print(f'CHECK PASSED: {len(requests)} B/P requests, {len(resets)} scripted full games, no model/server calls.')
        return 0
    if 'allowed_stages' in manifest and (args.performance_only or any(s not in manifest['allowed_stages'] for s in args.stages)):
        raise ValueError('This bundle only supports stages: '+', '.join(manifest['allowed_stages']))
    if 'l0' in getattr(args, 'stages', []) and 'l0' not in manifest['conditions']:
        raise ValueError('This bundle does not contain an L0 stage')
    gpu_ids = [x.strip() for x in os.environ.get('CUDA_VISIBLE_DEVICES', '').split(',')]
    if len(gpu_ids) != 2 or len(set(gpu_ids)) != 2 or any(not x.strip() for x in gpu_ids):
        raise ValueError('Set CUDA_VISIBLE_DEVICES to exactly the two GPUs allocated to you.')
    if not args.model.is_dir():
        raise FileNotFoundError(args.model)
    import importlib.metadata
    import torch
    from transformers import AutoTokenizer
    if torch.cuda.device_count() != 2:
        raise ValueError('Expected exactly two visible GPUs')
    for port in args.ports:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    args.output.mkdir(parents=True, exist_ok=False)
    print('PROBE_RUN_DIR='+str(args.output.resolve()), flush=True)
    bundle = args.output/'bundle'; bundle.mkdir()
    for name in ('bundle_manifest.json', *manifest['files']):
        shutil.copy2(ENTRY/name, bundle/name)
    rollout = load_runtime(bundle, args.output/'runtime')
    tokenizer = AutoTokenizer.from_pretrained(str(args.model), local_files_only=True)
    model_options, model_profile = configure_model(tokenizer, args.model, manifest, bundle, args.output)
    lengths = [token_count(tokenizer, r['request']['messages'], r['request']['tools']) for r in requests]
    if max(lengths)+1024 > args.context:
        raise ValueError('B/P input exceeds context; no truncation allowed')
    endpoints = [f'http://127.0.0.1:{port}/v1' for port in args.ports]
    model_config = {}
    for name in ('config.json', 'generation_config.json', 'tokenizer_config.json'):
        path = args.model/name
        if path.exists():
            model_config[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if name == 'generation_config.json':
                shutil.copy2(path, args.output/name)
    commands = []
    servers = []
    logs = []
    def interrupted(signum, frame):
        raise SystemExit(128+signum)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        startup = time.monotonic()
        print('Starting both vLLM services (one load per GPU for all stages).', flush=True)
        for index, (gpu, port) in enumerate(zip(gpu_ids, args.ports)):
            command = [sys.executable, '-u', '-m', 'vllm.entrypoints.openai.api_server',
                       '--model', str(args.model), '--served-model-name', 'social-base',
                       '--host', '127.0.0.1', '--port', str(port), '--tensor-parallel-size', '1',
                       '--dtype', 'bfloat16', '--max-model-len', str(args.context),
                       '--max-num-seqs', str(args.workers_per_gpu), '--gpu-memory-utilization', str(args.gpu_memory),
                       '--disable-frontend-multiprocessing',
                       '--enable-auto-tool-choice', '--tool-call-parser', 'hermes']
            command.extend(model_options)
            if args.execution == 'eager':
                command.append('--enforce-eager')
            commands.append(command)
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu,
                       TRITON_CACHE_DIR=str((args.output/f'triton-cache-{index}').resolve()))
            log = (args.output/f'server-{index}.log').open('w'); logs.append(log)
            servers.append(subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        save(args.output/'server_manifest.json', dict(model=str(args.model), python=sys.executable,
             model_config_sha256=model_config, model_profile=model_profile,
             host=socket.gethostname(), cuda_visible_devices=gpu_ids,
             devices=[dict(name=torch.cuda.get_device_name(i), bytes=torch.cuda.get_device_properties(i).total_memory) for i in range(2)],
             versions={n:importlib.metadata.version(n) for n in ('torch','vllm','transformers','numpy')},
             commands=commands, server_pids=[s.pid for s in servers], context=args.context,
             workers_per_gpu=args.workers_per_gpu, bp_max_prompt_tokens=max(lengths), response_budget=1024,
             execution=args.execution, performance_only=args.performance_only,
             selected_stages=args.stages, sampling_seed=args.sampling_seed,
             environment={k:os.environ.get(k) for k in ('VLLM_USE_V1','VLLM_ATTENTION_BACKEND','TRITON_PTXAS_PATH')},
             training_started=False, selfplay_temperature=.7, bp_temperature=.8))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(wait_ready, server, endpoint, args.startup_timeout)
                       for server, endpoint in zip(servers, endpoints)]
            for i, future in enumerate(futures):
                save(args.output/f'models-{i}.json', future.result())
        save(args.output/'startup.json', dict(both_services_ready_seconds=time.monotonic()-startup))
        print(f'Both services ready in {time.monotonic()-startup:.1f}s; starting requests.', flush=True)
        spec = importlib.util.spec_from_file_location('bp_sampler', bundle/'remote_bp_probe.py')
        sampler = importlib.util.module_from_spec(spec); spec.loader.exec_module(sampler)
        if args.performance_only:
            return run_performance(args, bundle, requests, endpoints)
        # Test both native B and P request envelopes on each service. Never mix with formal groups.
        for index, endpoint in enumerate(endpoints):
            result = sampler.run(bundle/'bp_requests.jsonl', args.output/f'preflight-{index}',
                                 [endpoint], 'social-base', preflight=True, group_size=1)
            if result['infrastructure_failures']:
                raise RuntimeError('Preflight transport failure; inspect samples')
        return run_selected_stages(args, sampler, rollout, tokenizer, resets, endpoints, bundle)
    finally:
        for server in servers:
            stop_server(server)
        for log in logs:
            log.close()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--check', action='store_true')
    cli.add_argument('--model', type=Path, default=Path('/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507'))
    cli.add_argument('--output', type=Path)
    cli.add_argument('--ports', nargs=2, type=int, default=[18091,18092])
    cli.add_argument('--context', type=int, default=16384)
    cli.add_argument('--workers-per-gpu', type=int, default=4)
    cli.add_argument('--gpu-memory', type=float, default=.80)
    cli.add_argument('--startup-timeout', type=int, default=600)
    cli.add_argument('--execution', choices=('eager', 'graphs'), default='eager',
                     help='graphs removes --enforce-eager; actual graph capture must be checked in logs')
    cli.add_argument('--performance-only', action='store_true',
                     help='32 fixed B/P/bridges requests, 360s sampling deadline; no formal evaluation')
    cli.add_argument('--stages', nargs='+', choices=('bp','bridges','l0','selfplay'),
                     default=['bp','bridges','selfplay'])
    cli.add_argument('--sampling-seed', type=int, default=20260915,
                     help='Formal B/P per-call seeds derived from this base, task ID and sample index')
    cli.add_argument('--capture-performance', action='store_true',
                     help='Read-only GPU/CPU/vLLM capture for up to 60s at each formal stage')
    args = cli.parse_args()
    if not args.check and args.output is None:
        cli.error('--output is required')
    if len(set(args.ports)) != 2 or not all(1024<=p<=65535 for p in args.ports):
        cli.error('Two distinct unprivileged ports required')
    if len(set(args.stages)) != len(args.stages) or args.sampling_seed < 0:
        cli.error('Stages must be distinct and sampling seed nonnegative')
    if not 1<=args.workers_per_gpu<=16 or not 0<args.gpu_memory<1 or args.context<=1024:
        cli.error('Invalid concurrency, GPU memory fraction or context')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
