"""Standalone HTTP sampling of model-visible requests; standard library only.

No evaluator, hidden target labels, private game worlds, solver or training
imports. Authorized worked examples may be part of visible teaching requests.
The calling environment must already host the requested model on approved GPUs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
from threading import Lock
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def run(requests_path, out, endpoints, model, *, preflight=False, group_size=8):
    raw=Path(requests_path).read_bytes()
    tasks=[json.loads(line) for line in raw.splitlines() if line.strip()]
    if preflight:
        representatives={}
        for task in tasks:
            representatives.setdefault((task['task'],task.get('output_arm','separate_tool')),task)
        tasks=list(representatives.values())
        group_size=1
    if not tasks or type(group_size) is not int or group_size < 1 or not endpoints:
        raise ValueError('Nonempty requests, endpoints and positive group size required')
    if len({t['task_id'] for t in tasks})!=len(tasks):raise ValueError('Duplicate task ids')
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    config=dict(model=model,group_size=group_size,temperature=.8,preflight=preflight,
        task_ids=[t['task_id'] for t in tasks],planned_requests=len(tasks)*group_size,
        workers=len(endpoints),requests_sha256=hashlib.sha256(raw).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        endpoints=endpoints,parameters_updated=False,retries=0)
    (out/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps(dict(stage='preflight' if preflight else 'formal',
        workers=len(endpoints),planned_requests=config['planned_requests'],
        preflight_gate='transport_and_response_envelope_only')),flush=True)
    queue=Queue()
    for task in tasks:queue.put(task)
    lock=Lock()
    samples=[]
    with (out/'samples.jsonl').open('w') as f:
        def worker(worker_id,endpoint):
            while True:
                try:task=queue.get_nowait()
                except Empty:return
                payload=dict(task['request'],model=model,temperature=.8)
                endpoint=endpoint.rstrip('/')
                url=endpoint+'/chat/completions' if endpoint.endswith('/v1') else endpoint+'/v1/chat/completions'
                for index in range(group_size):
                    row=dict(task_id=task['task_id'],sample_index=index,worker_id=worker_id)
                    start=time.monotonic()
                    try:
                        req=Request(url,data=json.dumps(payload).encode(),headers={
                            'Content-Type':'application/json',
                            'Authorization':'Bearer '+os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY')})
                        with urlopen(req,timeout=180) as response:body=json.load(response)
                        choice=body['choices'][0]
                        if not isinstance(choice['message'],dict) or not isinstance(choice['finish_reason'],str):
                            raise ValueError('Invalid completion response envelope')
                        row.update(status='completed',raw_message=choice['message'],
                            finish_reason=choice['finish_reason'],usage=body.get('usage',{}))
                    except Exception as exc:
                        row.update(status='infrastructure_failure',error_type=type(exc).__name__)
                        if isinstance(exc,HTTPError):row['http_status']=exc.code
                    row['seconds']=time.monotonic()-start
                    with lock:
                        samples.append(row)
                        f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
                with lock:
                    print(json.dumps(dict(task_id=task['task_id'],worker_id=worker_id,
                                          endpoint=endpoint,samples_written=len(samples),
                                          planned_requests=config['planned_requests'])),flush=True)
        with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
            futures=[pool.submit(worker,i,endpoint) for i,endpoint in enumerate(endpoints)]
            for future in futures:future.result()
    expected={t['task_id']:({tool['function']['name'] for tool in t['request']['tools']}
              if t['request'].get('tools') else None) for t in tasks}
    native=text_submissions=0
    for row in samples:
        calls=row.get('raw_message',{}).get('tool_calls') or []
        if expected[row['task_id']] is None:
            if row.get('finish_reason')=='length' or calls:continue
            try:
                obj=json.loads(row['raw_message']['content'])
                if (isinstance(obj,dict) and set(obj)=={'reasoning','answer'} and
                        isinstance(obj['reasoning'],str) and obj['reasoning'].strip() and isinstance(obj['answer'],dict)):
                    text_submissions+=1
            except (KeyError,TypeError,ValueError):pass
            continue
        if (row.get('finish_reason')!='length' and len(calls)==1 and
                calls[0].get('function',{}).get('name') in expected[row['task_id']]):
            try:
                if isinstance(json.loads(calls[0]['function']['arguments']),dict):native+=1
            except (KeyError,TypeError,ValueError):pass
    completed=sum(s['status']=='completed' for s in samples)
    result=dict(requests_sent=len(samples),completed=completed,
        infrastructure_failures=len(samples)-completed,
        completed_without_protocol_submission=completed-native-text_submissions,
        truncated_submissions=sum(s.get('finish_reason')=='length' for s in samples),
        worker_samples={str(i):sum(s['worker_id']==i for s in samples) for i in range(len(endpoints))},
        native_submissions=native,text_submissions=text_submissions,
        protocol_submissions=native+text_submissions,preflight=preflight,parameters_updated=False,
        preflight_gate='transport_and_response_envelope_only',
        semantic_scoring='Performed locally against separate teacher labels; none were uploaded.')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    # Protocol compliance and semantic correctness are measured outcomes, not
    # readiness requirements. Preserve failures verbatim without repair/retry.
    if preflight and completed!=config['planned_requests']:
        raise RuntimeError('Preflight transport or response-envelope failure; inspect samples.jsonl')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--requests',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--base-urls',required=True,nargs='+')
    p.add_argument('--model',required=True)
    p.add_argument('--group-size',type=int,default=8)
    p.add_argument('--preflight',action='store_true')
    a=p.parse_args()
    run(a.requests,a.out,a.base_urls,a.model,preflight=a.preflight,group_size=a.group_size)
