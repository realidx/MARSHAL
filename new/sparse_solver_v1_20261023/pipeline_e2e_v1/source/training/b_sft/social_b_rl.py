"""B-only RL preparation and native reward-diversity probe; no optimizer."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
from threading import Lock

from training.b_sft.social_b_evaluation import request, score_attempt, PROMPT_VERSION, require_current_tasks
from training.b_sft.run_social_b_eval import checkpoint
from methods.vllm_client import OpenAICompatibleNegotiationClient

CONTRACT = dict(version='social-b-exact-reward-v1',
    valid='Mean of per-query exact matches of both preference set and favored; range [0,1].',
    format_failure=-1, truncated=-1, infrastructure_failure=None,
    failure_priority='Infrastructure masked; truncation -1 without additional format penalty.',
    reasoning='No separate prose, length, or repetition reward.',
    retries='Every attempt receives its own reward. First attempts alone define same-prompt reward groups; retry prompts differ.',
    advantage='These are rewards and group diagnostics, not optimizer advantages.',
    training_unit='New optimizer exports use one queried preference per response, with full actual history; legacy multi-query rewards remain readable for audits.')


def reward(task, completion):
    if task.get('training_unit')=='single_query' and len(task['input']['queries'])!=1:
        raise ValueError('Single-query training must not average multiple queries')
    s=score_attempt(task,completion)
    if s['status']=='infrastructure_failure':value=None
    elif s['status']!='ok':value=-1.0
    else:value=sum(j['set_exact'] and j['favored_exact'] for j in s['judgments'])/len(s['judgments'])
    return dict(version=CONTRACT['version'],status=s['status'],reward=value,
                trainable=value is not None,query_count=s['query_count'])


def read(path):return list(map(json.loads,Path(path).read_text().splitlines()))
def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def jsonl(path,values):Path(path).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in values))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(data_dir, output_dir, per_category=3):
    from training.b_sft.social_b_training_data import single_queries
    data=Path(data_dir);tasks=read(data/'tasks.jsonl');pairs=read(data/'pairs.jsonl')
    tasks=[q for t in tasks for q in single_queries(t)]
    require_current_tasks(tasks)
    index={t['id']:t for t in tasks}
    if len(index)!=len(tasks):raise ValueError('Duplicate task ids')
    families=defaultdict(set)
    categories=defaultdict(set)
    for t in tasks:
        families[t['split']].add(t['family'])
        # Validate teacher against the same exact reward without adding a
        # teacher completion to any model-facing data.
        fake=dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_BELIEFS',arguments=json.dumps(t['gold'])))]))
        if reward(t,fake)['reward']!=1:raise ValueError('Invalid gold')
    for a in families:
        for b in families:
            if a!=b and families[a]&families[b]:raise ValueError('Family leakage')
    for t in tasks:
        for p in pairs:
            if p['after']==t.get('parent_checkpoint',t['id']) and (not p.get('query') or p['query'] in t['input']['queries']):
                categories[t['id']].add(p['category'])
        categories[t['id']].update(p['category'] for p in t.get('category_queries',[]))
    # Select by category and family, without consulting model responses.
    selected=[];seen=set()
    for cat in ('formation','maintain','update','uninformative'):
        candidates=sorted([t for t in tasks if t['split']=='train' and cat in categories[t['id']]],key=lambda t:t['id'])
        chosen=[];used_families=set()
        for diverse in (True,False):
            for t in candidates:
                if len(chosen)>=per_category:break
                if t['id'] in seen or diverse and t['family'] in used_families:continue
                chosen.append(t);seen.add(t['id']);used_families.add(t['family'])
        selected.extend(dict(id=t['id'],family=t['family'],category=cat) for t in chosen)
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=False)
    for split in ('train','validation','test'):
        ts=[t for t in tasks if t['split']==split]
        jsonl(out/(split+'_requests.jsonl'),[dict(id=t['id'],request=request(t)) for t in ts])
        jsonl(out/(split+'_targets.jsonl'),[dict(id=t['id'],family=t['family'],categories=sorted(categories[t['id']]),gold=t['gold']) for t in ts])
    dump(out/'probe_selection.json',selected)
    dump(out/'reward_contract.json',CONTRACT)
    manifest=dict(prompt_version=PROMPT_VERSION,data_dir=str(data.resolve()),
        source_hashes=source_hashes(),task_hash=digest(data/'tasks.jsonl'),
        split_counts=dict(Counter(t['split'] for t in tasks)),
        family_counts={k:len(v) for k,v in families.items()},probe_points=len(selected),
        selection='Train only, up to three diverse families per category; no response-based selection.',
        known_limitations=['Coverage must be checked on the newly generated weighted-label pack.',
                          'Prepared requests are not directly consumable by the existing text-only RLVR encoder.',
                          'No optimizer, rollout token IDs, or behavior log probabilities are included.'])
    dump(out/'manifest.json',manifest)
    return manifest


def source_hashes():
    from training.b_sft import social_b_evaluation, social_presentation, social_lm_eval, run_social_b_eval, social_b_training_data
    import methods.vllm_client as client
    return {Path(m.__file__).name:digest(m.__file__) for m in (social_b_evaluation,social_presentation,social_lm_eval,run_social_b_eval,social_b_training_data,client)} | {'social_b_rl.py':digest(__file__)}


def analyze(calls, tasks, selection, samples):
    groups=defaultdict(list)
    for r in calls:
        if r['attempt']==0:groups[r['checkpoint']].append(r)
    reports=[]
    for chosen in selection:
        tid=chosen['id'];rs=groups[tid]
        values=[reward(tasks[tid],r)['reward'] for r in rs]
        usable=[v for v in values if v is not None]
        valid=[reward(tasks[tid],r)['reward'] for r in rs if r['score']['status']=='ok']
        mean=sum(usable)/len(usable) if usable else None
        answers=[]
        for r in rs:
            if r['score']['status']=='ok':
                answers.append(json.dumps(sorted([(j['player'],j['goal'],sorted(j['prediction']['possible_preferences']),j['prediction']['favored']) for j in r['score']['judgments']]),sort_keys=True))
        reports.append(dict(**chosen,scheduled_samples=samples,recorded_samples=len(rs),
            complete=len(rs)==samples and len(usable)==samples,
            statuses=dict(Counter(r['score']['status'] for r in rs)),rewards=values,
            mean_reward=mean,variance=sum((v-mean)**2 for v in usable)/len(usable) if usable else None,
            unique_valid_answers=len(set(answers)),
            positive_samples=sum(v>0 for v in usable),
            all_valid_task_zero=bool(valid) and all(v==0 for v in valid),
            reward_varies=len(set(usable))>1,valid_task_reward_varies=len(set(valid))>1))
    return dict(contract=CONTRACT,groups=reports,
        totals=dict(groups=len(reports),complete_groups=sum(r['complete'] for r in reports),
                    groups_with_positive_reward=sum(r['positive_samples']>0 for r in reports),
                    groups_with_reward_variation=sum(r['reward_varies'] for r in reports),
                    groups_with_valid_task_variation=sum(r['valid_task_reward_varies'] for r in reports),
                    all_attempt_statuses=dict(Counter(r['score']['status'] for r in calls))),
        interpretation='Reward differences caused only by format failures are not evidence of B task learning signal. No advantages computed; incomplete groups are flagged, not filled with zero.')


def probe(args):
    from training.b_sft.social_b_training_data import single_queries
    prep=Path(args.prepared_dir);manifest=json.loads((prep/'manifest.json').read_text())
    data=Path(args.data_dir);tasks={q['id']:q for t in read(data/'tasks.jsonl') for q in single_queries(t)}
    if manifest['task_hash']!=digest(data/'tasks.jsonl') or manifest['source_hashes']!=source_hashes():
        raise ValueError('Prepared data/code changed; prepare a new version before sampling')
    selection=json.loads((prep/'probe_selection.json').read_text())
    if any(tasks[t['id']]['split']!='train' for t in selection):raise ValueError('Probe must use train only')
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=False)
    dump(out/'run_config.json',dict(arguments=vars(args),contract=CONTRACT,source_hashes=source_hashes(),
        selection=selection,sampling=dict(temperature=args.temperature,top_p=1.0,top_k=-1,seed=args.seed),
        note='Explicit full-support sampling; earlier evaluations left top_p/top_k/seed implicit. Frozen model only.'))
    queue=Queue()
    for chosen in selection:
        for sample in range(args.samples):queue.put((chosen['id'],sample))
    calls=[];lock=Lock()
    def worker(endpoint):
        client=OpenAICompatibleNegotiationClient(endpoint,args.model,
            api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),timeout=args.timeout,
            temperature=args.temperature,top_p=1.0,top_k=-1,max_tokens=1024)
        while True:
            try:tid,sample=queue.get_nowait()
            except Empty:return
            seed=int.from_bytes(hashlib.sha256(f'{args.seed}:{tid}:{sample}'.encode()).digest()[:4],'big')%(2**31)
            client.seed=seed
            def emit(r):
                row=dict(r,checkpoint=tid,sample=sample,endpoint=endpoint,seed=seed,rl_reward=reward(tasks[tid],r))
                with lock:
                    calls.append(row)
                    with (out/'calls.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            attempts=checkpoint(tasks[tid],client,mode='independent',prior=[],emit=emit)
            print(tid,sample,attempts[-1]['score']['status'],flush=True)
    with ThreadPoolExecutor(max_workers=len(args.base_urls)) as pool:
        futures=[pool.submit(worker,url) for url in args.base_urls]
        for future in futures:future.result()
    calls.sort(key=lambda r:(r['checkpoint'],r['sample'],r['attempt']))
    result=analyze(calls,tasks,selection,args.samples);dump(out/'summary.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--data-dir',required=True);prep.add_argument('--output-dir',required=True)
    run=sub.add_parser('probe');run.add_argument('--data-dir',required=True);run.add_argument('--prepared-dir',required=True);run.add_argument('--output-dir',required=True)
    run.add_argument('--base-urls',nargs='+',required=True);run.add_argument('--model',default='social-base');run.add_argument('--samples',type=int,default=8)
    run.add_argument('--temperature',type=float,default=.7);run.add_argument('--seed',type=int,default=20260912);run.add_argument('--timeout',type=float,default=180)
    args=p.parse_args()
    if args.command=='prepare':result=prepare(args.data_dir,args.output_dir)
    else:
        if args.samples<2 or args.temperature<=0 or args.timeout<=0 or len(set(args.base_urls))!=len(args.base_urls):p.error('Invalid sampling arguments')
        result=probe(args)
    print(json.dumps(result,indent=2))
    if args.command=='probe' and result['totals']['all_attempt_statuses'].get('infrastructure_failure'):raise SystemExit(2)

if __name__=='__main__':main()
