"""Frozen training-side Q0 probe. Preparation is offline; generation is explicit."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
import json
from pathlib import Path
from urllib.request import Request, urlopen
from training.social_mixed.reasoning_bank import load, sha, stable
from training.social_mixed.reasoning_training import case_schedule
from training.social_mixed.core import seed_for
from training.social_mixed.paired_requests import request


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:groups[(r['canonical_id'],r['view'])].append(r)
    stats=defaultdict(Counter)
    for (_,view),rs in groups.items():
        valid=[r for r in rs if r['score']['status']=='ok' and r['completion']['finish_reason']!='length']
        values=[r['score']['reward'] for r in valid if r['score'].get('semantic_eligible',True)]
        stats[view]['semantic_masked']+=sum(r['score'].get('semantic_outcome')=='masked' for r in valid)
        stats[view]['semantic_scored']+=len(values)
        s=stats[view];s['groups']+=1;s['responses']+=len(rs);s['valid']+=len(valid)
        s['correct']+=sum(values)
        s['semantic_mixed_groups']+=int(bool(values) and max(values)>min(values))
        s['no_correct_groups']+=int(bool(values) and not any(values))
        s['no_scored_groups']+=int(not values)
        s['all_legal_correct_groups']+=int(bool(values) and all(values))
    return {k:dict(v) for k,v in stats.items()}


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--output',required=True)
    cli.add_argument('--base-url');cli.add_argument('--model');cli.add_argument('--checkpoint-hash')
    cli.add_argument('--prepare-only',action='store_true');cli.add_argument('--cases',type=int,default=32)
    cli.add_argument('--seed',type=int,default=42)
    cli.add_argument('--concurrency',type=int,default=32)
    cli.add_argument('--views',nargs='+',choices=('O','B','Pplus'),default=['O','B','Pplus'])
    args=cli.parse_args()
    if not 1<=args.cases<=32:raise ValueError('Probe is bounded to 1–32 training cases')
    if not 1<=args.concurrency<=32:raise ValueError('Probe concurrency must be in 1–32')
    if not args.prepare_only and not all((args.base_url,args.model,args.checkpoint_hash)):
        raise ValueError('Generation requires explicit endpoint, model and checkpoint identity')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise FileExistsError('Use a fresh probe directory')
    tasks=load('train');schedule=case_schedule(tasks,args.seed)[:args.cases]
    by={(t['canonical_id'],t['paired_view']):t for t in tasks};jobs=[]
    for cid in schedule:
        for view in dict.fromkeys(args.views):
            t=by[cid,view]
            if view=='Pplus' and not t.get('p_train_eligible',True):continue
            for replica in range(8):
                req=request(t,'action_tools',t.get('name_variant',0))
                req.update(seed=seed_for(args.seed,'reasoning-q0-probe',cid,view,replica),temperature=1.,top_p=1.,max_tokens=1024)
                jobs.append(dict(canonical_id=cid,view=view,replica=replica,request=req,
                                 belief_action_relevant=t['belief_action_relevant'],source_kernel=t['source_kernel']))
    (out/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in jobs))
    protocol=dict(cases=len(schedule),responses=len(jobs),split='train',checkpoint_hash=args.checkpoint_hash,
        model=args.model,view_responses=dict(Counter(j['view'] for j in jobs)),P_eligibility_filter=True,request_sha256=sha((out/'requests.jsonl').read_bytes()),
        selection='Frozen parent/structure coverage schedule; no output-based filtering',concurrency=args.concurrency,status='prepared')
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    if args.prepare_only:print(json.dumps(protocol,indent=2));return
    from training.social_mixed.reasoning_scoring import score as reward
    from training.social_mixed.reasoning_scoring import decision_metrics
    def execute(index,job):
        req=dict(job['request'],model=args.model)
        http=Request(args.base_url.rstrip('/')+'/chat/completions',data=json.dumps(req).encode(),headers={'Content-Type':'application/json'})
        with urlopen(http,timeout=180) as response:raw=json.load(response)
        choice=raw['choices'][0]
        completion=dict(raw_message=choice['message'],finish_reason=choice['finish_reason'])
        task=by[job['canonical_id'],job['view']]
        score=reward(task,completion);score.update(decision_metrics(task,completion))
        return index,dict(job,completion=completion,score=score,usage=raw.get('usage'))
    rows=[None]*len(jobs);completed=0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures=[pool.submit(execute,index,job) for index,job in enumerate(jobs)]
        for future in as_completed(futures):
            index,row=future.result();rows[index]=row;completed+=1
            if completed%24==0:print(f'completed {completed}/{len(jobs)}',flush=True)
    with (out/'calls.jsonl').open('w') as f:
        for row in rows:f.write(json.dumps(row)+'\n')
    (out/'summary.json').write_text(json.dumps(summarize(rows),indent=2)+'\n')
    (out/'COMPLETE.json').write_text(json.dumps(dict(rows=len(rows),checkpoint_hash=args.checkpoint_hash))+'\n')


if __name__=='__main__':main()
