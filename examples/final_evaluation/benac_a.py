"""Package A: one focal model, two frozen Q0 players; native training interface."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from training.social_mixed.core import Episode, load_data
from examples.final_evaluation.benac_a_suite import DEFAULT, SEED, load


def complete(route, request):
    body=dict(model=route['model'],messages=request['messages'],tools=request['tools'],tool_choice='auto',
              parallel_tool_calls=False,max_tokens=1024,temperature=1.0,top_p=1.0,top_k=-1,
              repetition_penalty=1.0,seed=request['seed'])
    req=Request(route['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer EMPTY'})
    start=time.monotonic()
    with urlopen(req,timeout=600) as response:raw=json.load(response)
    choice=raw['choices'][0]
    if choice['finish_reason'] not in ('stop','tool_calls','length'):
        raise RuntimeError(f'Unexpected provider finish reason: {choice["finish_reason"]}')
    return dict(completion=dict(raw_message=choice['message'],finish_reason=choice['finish_reason']),
                usage=raw.get('usage',{}),request=body,response=raw,elapsed_seconds=time.monotonic()-start)


def run_game(reset,seat,routes,output,generate=complete):
    ep=Episode(reset,reset['id'],0,SEED)
    folder=output/f'{reset["id"]}-seat{seat}';folder.mkdir()
    error=None
    with (folder/'calls.jsonl').open('w') as f:
        try:
            while ep.status=='running':
                actor=ep.rules.actor(ep.node);role='focal' if actor==seat else 'q0'
                request=ep.request()
                try:response=generate(routes[role],request)
                except Exception as exc:
                    f.write(json.dumps(dict(status='infrastructure_failure',actor=actor,role=role,request=request,error=repr(exc)))+'\n');f.flush();raise
                response['role']=role
                ep.accept(response);f.write(json.dumps(ep.calls[-1])+'\n');f.flush()
        except Exception as exc:
            error=repr(exc);ep.status='infrastructure_failure'
    lower=sum(min(0,v) for v in ep.world[seat]);upper=sum(max(0,v) for v in ep.world[seat])
    result=dict(ep.summary(),focal_seat=seat,error=error,split=reset['evaluation_split'],
        mode='binary' if reset['raw']['game']['goals'][0]['binary'] else 'linear',
        structure_family=reset['structure_family'],calls=len(ep.calls),
        invalid_calls=sum(not c['valid'] for c in ep.calls),
        truncated_calls=sum(c['completion']['finish_reason']=='length' for c in ep.calls),
        focal_calls=sum(c['player']==seat for c in ep.calls),
        focal_invalid_calls=sum(c['player']==seat and not c['valid'] for c in ep.calls),
        focal_truncated_calls=sum(c['player']==seat and c['completion']['finish_reason']=='length' for c in ep.calls),
        completion_tokens=sum(c.get('usage',{}).get('completion_tokens',0) for c in ep.calls),
        focal_utility=None if ep.terminal is None else ep.terminal[seat],
        total_utility=None if ep.terminal is None else sum(ep.terminal),
        missing_utility_bounds=[lower,upper])
    (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def summarize(rows):
    out={}
    for split in sorted({r['split'] for r in rows}):
        for mode in ('all','binary','linear'):
            group=[r for r in rows if r['split']==split and (mode=='all' or r['mode']==mode)]
            if not group:continue
            done=[r for r in group if r['status']=='terminal'];calls=sum(r['calls'] for r in group)
            infrastructure=any(r['status']=='infrastructure_failure' for r in group)
            def avg(key):return sum(r[key] for r in done)/len(done) if done else None
            out[f'{split}/{mode}']=dict(games=len(group),status_counts=dict(Counter(r['status'] for r in group)),
                completion_rate=len(done)/len(group),terminal_focal_utility_mean=avg('focal_utility'),
                terminal_total_utility_mean=avg('total_utility'),
                full_cohort_focal_utility_bounds=None if infrastructure else [sum(r['focal_utility'] if r['status']=='terminal' else r['missing_utility_bounds'][i] for r in group)/len(group) for i in (0,1)],
                calls=calls,invalid_calls=sum(r['invalid_calls'] for r in group),
                invalid_call_rate=sum(r['invalid_calls'] for r in group)/calls if calls else None,
                truncated_calls=sum(r['truncated_calls'] for r in group),
                truncation_rate=sum(r['truncated_calls'] for r in group)/calls if calls else None,
                focal_calls=sum(r['focal_calls'] for r in group),
                focal_invalid_calls=sum(r['focal_invalid_calls'] for r in group),
                focal_truncated_calls=sum(r['focal_truncated_calls'] for r in group))
    return dict(strata=out,interpretation='Terminal means are conditional; read completion and missing-utility bounds together. Bounds use physical own-preference extrema, not imputed outcomes. Infrastructure failure invalidates cohort. Seats share scenarios; do not treat 48 seats as independent structures.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--routes',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--suite',type=Path,default=DEFAULT);p.add_argument('--stage',choices=['smoke','formal'],default='smoke');p.add_argument('--parallel-games',type=int,default=4)
    a=p.parse_args()
    if a.parallel_games<1:p.error('parallel-games must be positive')
    routes=json.loads(a.routes.read_text())
    for role in ('focal','q0'):
        if urlparse(routes[role]['base_url']).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('Local endpoints only')
    manifest,resets=load(a.suite)
    if a.stage=='smoke':
        from copy import deepcopy
        from training.social_mixed.structure_coverage import geometry_id
        reset=deepcopy(next(r for r in load_data()['selfplay_validation'] if r['players']==3))
        reset.update(evaluation_split='development',structure_family=geometry_id(reset['raw']['game']))
        resets=[reset]
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'protocol.json').write_text(json.dumps(dict(stage=a.stage,suite=manifest,routes=routes,replicas=1,seat_rotation=[0,1,2]),indent=2)+'\n')
    jobs=[(r,s) for r in resets for s in range(3)];rows=[]
    with ThreadPoolExecutor(max_workers=a.parallel_games) as pool,(a.output/'games.jsonl').open('w') as f:
        for offset in range(0,len(jobs),a.parallel_games):
            futures=[pool.submit(run_game,r,s,routes,a.output) for r,s in jobs[offset:offset+a.parallel_games]]
            batch=[]
            for future in as_completed(futures):
                row=future.result();rows.append(row);batch.append(row);f.write(json.dumps(row)+'\n');f.flush()
                print(f'{len(rows)}/{len(jobs)} {row["reset"]["id"]} seat={row["focal_seat"]} {row["status"]}',flush=True)
            (a.output/'summary.json').write_text(json.dumps(summarize(rows),indent=2)+'\n')
            if any(r['status']=='infrastructure_failure' for r in batch):
                (a.output/'RUN_FAILED.json').write_text(json.dumps(dict(recorded=len(rows),expected=len(jobs))))
                raise RuntimeError('Infrastructure failure; stopped before admitting more games')
    (a.output/'RUN_FINISHED.json').write_text(json.dumps(dict(recorded=len(rows),expected=len(jobs),all_terminal=all(r['status']=='terminal' for r in rows)))+'\n')

if __name__=='__main__':main()
