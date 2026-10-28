"""Frozen B evaluation using the existing native chat HTTP client."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
from threading import Lock
import time

from training.b_sft.social_b_evaluation import request, score_attempt, score_transition, summarize, SPEC
from methods.vllm_client import OpenAICompatibleNegotiationClient

VERSION = 'social-b-eval-runner-v2'


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def checkpoint(task, client, *, mode, prior, emit):
    remaining = 1024
    attempts = []
    feedback = None
    for attempt in range(2):
        payload = request(task, mode=mode, prior_turns=prior,
                          remaining_tokens=remaining, retry_feedback=feedback)
        record = dict(attempt=attempt, requested_max_tokens=remaining, request=payload)
        start = time.monotonic()
        try:
            c = client.complete_with_tools(**payload)
            record.update(raw_message=dict(c.raw_message), raw_text=c.content,
                          usage=dict(c.usage), finish_reason=c.finish_reason)
            used = c.usage.get('completion_tokens')
            if type(used) is not int or not 0 <= used <= remaining:
                record.update(status='infrastructure_failure', error='Missing or invalid completion_tokens; budget cannot be verified')
                remaining = 0
            else:
                remaining -= used
        except Exception as exc:
            # A timeout can have generated tokens remotely. Do not guess usage
            # or resend the request with a fresh budget.
            record.update(status='infrastructure_failure', error=str(exc))
            remaining = 0
        record.update(seconds=time.monotonic()-start, remaining_tokens=remaining)
        record['score'] = score_attempt(task, record)
        emit(record)
        attempts.append(record)
        if record['score']['status'] in ('ok', 'infrastructure_failure') or remaining == 0:
            break
        feedback = ('Your previous response failed the submission format: ' +
                    record['score'].get('detail', record['score']['status']) +
                    '. Briefly explain, then submit exactly one native SUBMIT_BELIEFS tool call answering every query. ' +
                    'Writing a function call in ordinary text does not submit it.')
    return attempts


def grouped(records, tasks, which):
    scores = [r[which] for r in records]
    out = summarize(scores)
    for field in ('family', 'split', 'phase'):
        groups = defaultdict(list)
        for r in records:
            task = tasks[r['checkpoint']]
            value = task.get(field) if field != 'phase' else task['input'].get('assessment', {}).get('phase', 'unknown')
            groups[str(value)].append(r[which])
        out['by_'+field] = {k:summarize(v) for k,v in groups.items()}
    return out


def run(args):
    data = Path(args.data_dir)
    tasks = {t['id']:t for t in rows(data/'tasks.jsonl') if args.split == 'all' or t['split'] == args.split}
    sequences = [s for s in rows(data/'sequences.jsonl') if args.split == 'all' or s['split'] == args.split]
    pairs = [p for p in rows(data/'pairs.jsonl') if p['before'] in tasks and p['after'] in tasks]
    jobs = []
    if args.mode in ('both', 'independent'):
        jobs += [('independent', tid, [tid]) for tid in sorted(tasks)]
    if args.mode in ('both', 'sequential'):
        jobs += [('sequential', s['id'], s['checkpoints']) for s in sequences]
    if getattr(args,'jobs_file',None):
        wanted={tuple(j[:2]):j[2] for j in json.loads(Path(args.jobs_file).read_text())}
        jobs=[j for j in jobs if tuple(j[:2]) in wanted]
        if len(jobs)!=len(wanted) or any(j[2]!=wanted[tuple(j[:2])] for j in jobs):
            raise ValueError('Selected jobs do not match complete dataset jobs')
    if args.limit:
        # Limit whole jobs separately per mode, never cut a continuous history.
        jobs = [j for mode in ('independent','sequential') for j in [x for x in jobs if x[0] == mode][:args.limit]]
    if not jobs:
        raise ValueError('No evaluation jobs selected')
    for mode, _, ids in jobs:
        prior=[]
        for tid in ids:
            request(tasks[tid], mode=mode, prior_turns=prior)
            prior.append(dict(task=tasks[tid], message=dict(role='assistant',content='Validation only.')))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    dump = lambda path, obj: path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
    from training.b_sft import social_b_evaluation, social_lm_eval, favored_belief, social_presentation
    import methods.vllm_client as native_client
    files = [Path(__file__), Path(social_b_evaluation.__file__), Path(social_lm_eval.__file__),
             Path(favored_belief.__file__), Path(native_client.__file__), Path(social_presentation.__file__)]
    config = dict(version=VERSION, prompt_version=social_b_evaluation.PROMPT_VERSION, arguments=vars(args), spec=SPEC,
                  source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  data_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in data.glob('*.json*')},
                  jobs=len(jobs), scheduled_checkpoints=sum(len(j[2]) for j in jobs),
                  infrastructure_retry='No retry when generated-token usage is unknown.',
                  parameters_updated=False)
    dump(out/'run_config.json', config)
    dump(out/'jobs.json', jobs)
    lock = Lock()
    completed=[]; calls=[]; blocked=[]
    def append(name, obj):
        with lock:
            with (out/name).open('a') as f:
                f.write(json.dumps(obj, ensure_ascii=False)+'\n')
            if name == 'calls.jsonl': calls.append(obj)
            elif name == 'checkpoints.jsonl': completed.append(obj)
            elif name == 'blocked.jsonl': blocked.append(obj)
    queue=Queue()
    for job in jobs: queue.put(job)
    def worker(endpoint):
        client = OpenAICompatibleNegotiationClient(endpoint, args.model,
            api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),
            temperature=args.temperature, timeout=args.timeout, max_tokens=1024)
        while True:
            try: mode, jid, ids = queue.get_nowait()
            except Empty: return
            prior=[]
            for index, tid in enumerate(ids):
                tag=dict(mode=mode, job=jid, checkpoint=tid, endpoint=endpoint)
                attempts=checkpoint(tasks[tid],client,mode=mode,prior=prior,
                    emit=lambda r:append('calls.jsonl',dict(tag,**r)))
                last=attempts[-1]
                append('checkpoints.jsonl',dict(tag,first=attempts[0]['score'],final=last['score'],
                    attempts=len(attempts),generated_tokens=sum(r.get('usage',{}).get('completion_tokens',0) or 0 for r in attempts),
                    budget_verified=all(r['score']['status']!='infrastructure_failure' for r in attempts)))
                print(f"{mode} {jid} {index+1}/{len(ids)} {last['score']['status']}",flush=True)
                if mode == 'sequential':
                    if last['score']['status']=='infrastructure_failure':
                        for missing in ids[index+1:]:
                            append('blocked.jsonl',dict(mode=mode,job=jid,checkpoint=missing,reason='Earlier infrastructure failure'))
                        break
                    prior.append(dict(task=tasks[tid],message=last['raw_message']))
    with ThreadPoolExecutor(max_workers=len(args.base_urls)) as pool:
        futures=[pool.submit(worker,url) for url in args.base_urls]
        for future in futures: future.result()
    result=dict(version=VERSION,scheduled_checkpoints=config['scheduled_checkpoints'],
                completed_checkpoints=len(completed),blocked_checkpoints=len(blocked),modes={})
    for mode in ('independent','sequential'):
        selected=[r for r in completed if r['mode']==mode]
        if not selected: continue
        mode_calls=[r for r in calls if r['mode']==mode]
        stats=dict(first=grouped(selected,tasks,'first'),final=grouped(selected,tasks,'final'),
                   all_attempt_statuses=dict(Counter(r['score']['status'] for r in mode_calls)))
        by_job=defaultdict(dict)
        for r in selected: by_job[r['job']][r['checkpoint']]=r
        if mode=='independent': by_job={'independent':{r['checkpoint']:r for r in selected}}
        transitions=[]
        categories=defaultdict(list)
        for jid, checkpoints in by_job.items():
            for p in pairs:
                if p['before'] not in checkpoints or p['after'] not in checkpoints: continue
                a,b=checkpoints[p['before']],checkpoints[p['after']]
                row=dict(mode=mode,job=jid,**p)
                for which in ('first','final'):
                    row[which]=score_transition(tasks[p['before']],tasks[p['after']],a[which],b[which],p['query'])
                append('transitions.jsonl',row);transitions.append(row)
                categories[p['category']].append(b)
        stats['by_transition_category']={k:{w:grouped(v,tasks,w) for w in ('first','final')} for k,v in categories.items()}
        stats['transition_counts']={w:dict(Counter({
            key:sum(bool(t[w].get(key)) for t in transitions)
            for key in ('comparable','expected_change','unnecessary_update','missed_update','previous_error','error_recovered','error_persisted')}),
            total=len(transitions),unavailable=sum(not t[w]['comparable'] for t in transitions)) for w in ('first','final')}
        stats['category_unit']='Pair endpoint; shared checkpoints may occur in multiple pairs. See transitions.jsonl for queried preference.'
        result['modes'][mode]=stats
    dump(out/'summary.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',required=True)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--base-urls',nargs='+',required=True)
    p.add_argument('--jobs-file',help='JSON list of complete dataset jobs for a fixed diagnostic subset')
    p.add_argument('--model',default='social-base')
    p.add_argument('--mode',choices=['independent','sequential','both'],default='both')
    p.add_argument('--split',choices=['train','validation','test','all'],default='all')
    p.add_argument('--temperature',type=float,default=0.7)
    p.add_argument('--timeout',type=float,default=180)
    p.add_argument('--limit',type=int,default=0,help='Whole jobs per mode; 0 selects all')
    args=p.parse_args()
    if args.limit<0 or args.temperature<0 or args.timeout<=0 or len(set(args.base_urls))!=len(args.base_urls):
        p.error('Invalid limit, temperature, timeout, or duplicate endpoints')
    result=run(args)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['blocked_checkpoints'] or any(m['all_attempt_statuses'].get('infrastructure_failure') for m in result['modes'].values()):
        raise SystemExit(2)


if __name__=='__main__': main()
