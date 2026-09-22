"""Evaluate all 12 paired Shape Factory instances through CalBench-style routes."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
from urllib.request import Request,urlopen
from examples.final_evaluation.calbench_local import load_routes,separate_reasoning
from examples.final_evaluation.shapefactory import Factory,IDS,CYCLES,VERSION,instances,prompt,validate,HERE

def dump(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def append(path,data):
    with Path(path).open('a') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')

def parse(text):
    text,_,_=separate_reasoning(text)
    obj=json.loads(text)
    if not isinstance(obj,dict) or set(obj)-{'action','rationale'} or 'action' not in obj:raise ValueError('Expected action and optional rationale')
    if 'rationale' in obj and not isinstance(obj['rationale'],str):raise ValueError('rationale must be a string')
    error=validate(obj['action'])
    if error:raise ValueError(error)
    return obj['action']

def run_one(job):
    case,condition,routes,folder,route=job;folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    env=Factory(case,condition=='dashboard');calls=0;format_errors=0;truncations=0;retry_calls=0;state_conflicts=0
    dump(folder/'manifest.json',dict(version=VERSION,case=case,condition=condition,route=route,
         cycles=CYCLES,logical_seconds_per_cycle=10,temperature=0,max_tokens=routes.get('max_tokens',4096),
         max_retries=1,all_seats_same_checkpoint=True))
    try:
        for cycle in range(CYCLES):
            env.tick(cycle)
            # Snapshot all observations before any current-cycle action executes.
            observations={a:env.observation(a) for a in IDS};snapshot=deepcopy(env.state.task_state);actions={}
            for actor in IDS:
                messages=prompt(observations[actor]);actions[actor]=dict(type='do_nothing',payload={})
                for attempt in range(2):
                    calls+=1;retry_calls+=int(attempt>0)
                    seed=int(hashlib.sha256(f'{case["id"]}:{actor}:{cycle}:{attempt}'.encode()).hexdigest()[:8],16)
                    body=dict(model=route['model'],messages=messages,temperature=0.,max_tokens=routes.get('max_tokens',4096),seed=seed)
                    if 'chat_template_kwargs' in routes:body['chat_template_kwargs']=routes['chat_template_kwargs']
                    record=dict(cycle=cycle,actor=actor,attempt=attempt,request=body)
                    try:
                        key=os.environ.get(route.get('api_key_env',''),'EMPTY')
                        req=Request(route['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                        with urlopen(req,timeout=routes.get('timeout_seconds',600)) as response:raw=json.load(response)
                        record['response']=raw
                        choice=raw['choices'][0];cut=choice.get('finish_reason')=='length';truncations+=int(cut)
                        if cut:raise ValueError('Truncated response')
                        actions[actor]=parse(choice['message']['content']);record['status']='ok'
                        append(folder/f'transport-agent-{actor}.jsonl',record);break
                    except (ValueError,TypeError,KeyError,IndexError) as exc:
                        # Invalid output consumes the slot if the single retry also fails.
                        format_errors+=1;record.update(status='invalid_output',error=str(exc));append(folder/f'transport-agent-{actor}.jsonl',record)
                        if attempt==0:messages=messages+[dict(role='user',content='Your response was invalid or truncated. Return one complete JSON action only, using the specified schema. This is your only retry.')]
                    except Exception as exc:
                        record.update(status='infrastructure_failure',error=str(exc));append(folder/f'transport-agent-{actor}.jsonl',record);raise
            before=len(env.events)
            for actor in IDS[cycle%4:]+IDS[:cycle%4]:
                candidate=actions[actor];was_valid=None
                if candidate['type'] in ('propose_trade_offer','trade_response','cancel_trade_offer','fulfill_order'):
                    from types import SimpleNamespace
                    emitted=[]
                    handled=env.native.shapefactory_apply_action(SimpleNamespace(task_state=deepcopy(snapshot)),actor,candidate,lambda **e:emitted.append(e))
                    was_valid=handled and not any(e['event_type']=='action_rejected' for e in emitted)
                accepted=env.submit(actor,candidate)
                if was_valid and not accepted:
                    state_conflicts+=1
                    env.emit(event_type='submission_state_conflict',actor_id=actor,visibility='private',payload=dict(action=candidate))
            append(folder/'cycles.jsonl',dict(cycle=cycle,observations=observations,actions=actions,state=deepcopy(env.state.task_state)))
            # Full final events also retain production settlement at cycle starts.
            print(case['id'],condition,'cycle',cycle+1,flush=True)
        env.tick(CYCLES)
        result=dict(case_id=case['id'],condition=condition,engine_finished=True,healthy_transport=True,
                    calls=calls,retry_calls=retry_calls,submission_state_conflicts=state_conflicts,strict_format_failures=format_errors,truncations=truncations,metrics=env.metrics())
        dump(folder/'result.json',result);dump(folder/'events.json',env.events);dump(folder/'final_state.json',env.state.task_state)
        (folder/'COMPLETE').write_text('ok\n');return result
    except Exception as exc:
        dump(folder/'events.json',env.events);dump(folder/'FAILED.json',dict(error_type=type(exc).__name__,error=str(exc)))
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--routes',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--parallel-games',type=int,default=2)
    args=p.parse_args();routes=load_routes(args.routes)
    if args.parallel_games<1:p.error('parallel-games must be positive')
    if routes.get('temperature',0)!=0:raise ValueError('Frozen temperature is zero')
    args.output.mkdir(parents=True,exist_ok=False)
    from examples.final_evaluation.shapefactory_references import audit
    audit() # Freeze gate: both policies must execute under current native rules.
    frozen=json.loads((HERE/'shapefactory_v1/manifest.json').read_text())
    for name,digest in frozen['files'].items():
        if hashlib.sha256((HERE/'shapefactory_v1'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen Shape Factory artifact changed: '+name)
    suite=json.loads((HERE/'shapefactory_v1/cases.json').read_text())
    if suite!=instances():raise ValueError('Frozen instance definition changed')
    replicas=routes.get('equivalent_replicas') or [routes['endpoints']['focal']]
    jobs=[(case,condition,routes,str(args.output/f'{case["id"]}-{condition}'),replicas[i%len(replicas)]) for i,case in enumerate(suite) for condition in ('private','dashboard')]
    dump(args.output/'protocol.json',dict(version=VERSION,native=json.loads((HERE/'collabsim_native/source.json').read_text()),cases=suite,
         calls_per_game=72,base_calls=1728,conditions=['private','dashboard'],routes=routes,python=platform.python_version(),
         adaptation='fixed-opportunity, logical clock; not real-time/event-triggered evaluation',
         files={str(f.relative_to(HERE)):hashlib.sha256(f.read_bytes()).hexdigest() for f in HERE.glob('shapefactory*.py')}))
    try:
        with ProcessPoolExecutor(max_workers=args.parallel_games) as pool:results=list(pool.map(run_one,jobs))
        summaries={}
        for condition in ('private','dashboard'):
            rs=[r for r in results if r['condition']==condition]
            summaries[condition]=dict(mean_final_balance=sum(r['metrics']['mean_final_balance'] for r in rs)/12,
                  completed_fraction=sum(r['metrics']['completed_fraction'] for r in rs)/12,
                  all_orders_completed=sum(r['metrics']['all_orders_completed'] for r in rs),calls=sum(r['calls'] for r in rs),
                  strict_format_failures=sum(r['strict_format_failures'] for r in rs),truncations=sum(r['truncations'] for r in rs))
        pairs=[]
        for case in suite:
            r={x['condition']:x for x in results if x['case_id']==case['id']}
            pairs.append(dict(case_id=case['id'],balance_delta=r['dashboard']['metrics']['mean_final_balance']-r['private']['metrics']['mean_final_balance'],completion_delta=r['dashboard']['metrics']['completed_fraction']-r['private']['metrics']['completed_fraction']))
        dump(args.output/'results.json',results);dump(args.output/'summary.json',dict(conditions=summaries,paired_deltas=pairs,independent_instances=12,not_independent_games=24))
        (args.output/'COMPLETE').write_text('ok\n')
    except BaseException:
        (args.output/'FAILED').write_text('Infrastructure or execution failure; do not treat missing cases as successful-only averages.\n');raise
if __name__=='__main__':main()
