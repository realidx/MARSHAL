"""Optional explicit OpenAI-compatible endpoint runner. Never starts a server."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
import os
import random
import threading
import time
from urllib.request import Request, urlopen

from build import HERE, sha
from evaluate import load, summarize


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base-url', required=True, nargs='+', help='Explicit inference server URL(s) including /v1')
    p.add_argument('--model', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--temperature', type=float, default=1.)
    p.add_argument('--top-p', type=float, default=1.)
    p.add_argument('--top-k', type=int, default=-1)
    p.add_argument('--concurrency-per-endpoint', type=int, default=16)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--timeout', type=float, default=180)
    a = p.parse_args()
    if a.repeats < 1 or a.temperature < 0 or not 0 < a.top_p <= 1 or a.concurrency_per_endpoint < 1:
        p.error('Invalid sampling settings')
    _, tasks, requests = load()
    a.output.mkdir(parents=True, exist_ok=False)
    config = dict(model=a.model, base_url=a.base_url, repeats=a.repeats, seed=a.seed,
        temperature=a.temperature, top_p=a.top_p, top_k=a.top_k, repetition_penalty=1., max_tokens=1024,
        concurrency_per_endpoint=a.concurrency_per_endpoint,
        manifest_sha256=sha(HERE / 'manifest.json'), retry=0, independent_contexts=True)
    (a.output / 'run_config.json').write_text(json.dumps(config, indent=2) + '\n')
    jobs = [(tid, rep) for tid in tasks for rep in range(a.repeats)]
    random.Random(a.seed).shuffle(jobs)
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('OPENAI_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENAI_API_KEY']
    records = []; locks = [threading.BoundedSemaphore(a.concurrency_per_endpoint) for _ in a.base_url]
    def call(job):
        tid, replica = job
        endpoint = replica % len(a.base_url)
        with locks[endpoint]:
            started = time.monotonic()
            call_seed = int(hashlib.sha256(f'{a.seed}:{tid}:{replica}'.encode()).hexdigest()[:8], 16)
            body = dict(requests[tid]['request'], model=a.model, temperature=a.temperature,
                        top_p=a.top_p, top_k=a.top_k, repetition_penalty=1., seed=call_seed)
            try:
                req = Request(a.base_url[endpoint].rstrip('/') + '/chat/completions',
                              data=json.dumps(body).encode(), headers=headers, method='POST')
                with urlopen(req, timeout=a.timeout) as response: payload = json.load(response)
                if len(payload['choices']) != 1: raise ValueError('Expected one completion')
                choice = payload['choices'][0]
                completion = dict(raw_message=choice['message'], finish_reason=choice['finish_reason'])
                usage = payload.get('usage')
            except Exception as exc:
                completion = dict(status='infrastructure_failure', error_type=type(exc).__name__,
                                  http_status=getattr(exc, 'code', None))
                usage = None
            return dict(task_id=tid, replica=replica, seed=call_seed, completion=completion, usage=usage,
                        endpoint_index=endpoint, elapsed_seconds=time.monotonic() - started)
    with ThreadPoolExecutor(max_workers=len(a.base_url) * a.concurrency_per_endpoint) as pool, \
            (a.output / 'responses.jsonl').open('w') as stream:
        futures = [pool.submit(call, job) for job in jobs]
        for number, future in enumerate(as_completed(futures), 1):
            record = future.result()
            records.append(record); stream.write(json.dumps(record) + '\n'); stream.flush()
            print(f'{number}/{len(jobs)} {record["task_id"]} replica={record["replica"]}', flush=True)
    summary, scored = summarize(records, tasks, a.repeats)
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (a.output / 'scored.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in scored))
    complete = summary['overall']['complete']
    (a.output / ('COMPLETE.json' if complete else 'INCOMPLETE.json')).write_text(json.dumps(config, indent=2) + '\n')
    if not complete: raise SystemExit('Incomplete inference run; inspect infrastructure failures')


if __name__ == '__main__':
    main()
