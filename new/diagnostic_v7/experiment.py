"""Run the frozen v7 B/O/P interface diagnostic against an OpenAI-compatible service."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import Request,urlopen
from new.diagnostic_v5.experiment import parse_b,belief_scores,_judgment_text
from training.b_sft.social_named_probe import score,present

HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load():
    manifest=json.loads((HERE/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        if sha(HERE/name)!=digest:raise ValueError('Frozen file changed: '+name)
    for name,digest in manifest.get('dependencies',{}).items():
        if sha(HERE.parents[1]/name)!=digest:raise ValueError('Frozen dependency changed: '+name)
    return manifest,json.loads((HERE/'cases.json').read_text())

def p_request(c,judgment):
    req=deepcopy(c['requests']['P_clean']);text=req['messages'][1]['content']
    before,after=text.split('\nRESPONSE INSTRUCTIONS',1)
    req['messages'][1]['content']=before+'\nSUPPLIED PARTNER JUDGMENT\n'+(
        'Use this inference output directly. No probability or behavioral history is supplied.\n')+_judgment_text(c,judgment)+'\nRESPONSE INSTRUCTIONS'+after
    return req

def action_score(c,completion):
    if completion.get('status')=='infrastructure_failure':return dict(status='infrastructure_failure',utility=None,regret=None,correct=False)
    if completion.get('finish_reason')=='length':return dict(status='truncated',utility=None,regret=None,correct=False)
    task=c['task'];s=score(task,completion,'action_tools',0)
    if s['status']!='ok':return dict(status=s['status'],utility=None,regret=None,correct=False)
    f=completion['raw_message']['tool_calls'][0]['function'];a=json.loads(f['arguments'])
    a={'response' if f['name'] in ('ACCEPT','REJECT') else 'action':f['name'],**a}
    idx=present(task,0)['legal_actions'].index(a)
    actor=task['input']['observer'];values=[row[actor] for row in task['teacher']['action_values']]
    return dict(status='ok',action_index=idx,utility=values[idx],regret=max(values)-values[idx],
        correct=idx in c['certificate']['acceptable_action_indices'],exact_optimal=abs(max(values)-values[idx])<1e-9)

def run_case(c,call):
    pred,status=parse_b(c,call('B',c['requests']['B']))
    if pred is not None:
        pred['possible_preferences']=[v for v in ('want','neutral','avoid') if v in pred['possible_preferences']]
    o=action_score(c,call('O',c['requests']['O']))
    gold=action_score(c,call('P_gold',p_request(c,c['gold_judgment'])))
    model=(action_score(c,call('P_model',p_request(c,pred))) if pred is not None else
           dict(status='blocked_by_'+status,utility=None,regret=None,correct=False))
    paired=gold['utility'] is not None and model['utility'] is not None
    return dict(case_id=c['id'],source_parent=c['source_parent'],stratum=c['stratum'],
        intervention_role=c['intervention_qualification']['role'],structure_family=c['structure_family'],
        belief_changed=(pred!=c['gold_judgment']) if pred is not None else None,
        B=dict(status=status,correct=bool(belief_scores(pred,c['gold_judgment'])['exact']),prediction=pred,gold=c['gold_judgment']),
        O=o,P_gold=gold,P_model=model,
        repair_gain=gold['utility']-model['utility'] if paired else None,
        action_changed=gold['action_index']!=model['action_index'] if paired else None)

def summarize(rows,expected):
    result=dict(completed_case_repeats=len(rows),expected_case_repeats=expected,panels={})
    for group in ['all']+sorted({r['stratum'] for r in rows})+['repair_sensitive','action_control']:
        selected=rows if group=='all' else [r for r in rows if r['stratum']==group or r['intervention_role']==group]
        panel={}
        for condition in ('B','O','P_gold','P_model'):
            cells=[r[condition] for r in selected];valid=[r for r in cells if r['status']=='ok']
            panel[condition]=dict(total=len(cells),valid=len(valid),correct=sum(r['correct'] for r in cells),
                accuracy_all=sum(r['correct'] for r in cells)/len(cells) if cells else None,
                accuracy_valid=sum(r['correct'] for r in valid)/len(valid) if valid else None,
                statuses=dict(Counter(r['status'] for r in cells)))
            if condition!='B':panel[condition]['mean_regret_valid']=sum(r['regret'] for r in valid)/len(valid) if valid else None
        pairs=[r for r in selected if r['repair_gain'] is not None]
        panel['paired']=dict(n=len(pairs),mean_repair_gain=sum(r['repair_gain'] for r in pairs)/len(pairs) if pairs else None,
            action_changes=sum(r['action_changed'] for r in pairs))
        changed=[r for r in pairs if r['belief_changed']]
        unchanged=[r for r in pairs if not r['belief_changed']]
        panel['paired']['changed_belief_n']=len(changed)
        panel['paired']['changed_belief_mean_repair_gain']=sum(r['repair_gain'] for r in changed)/len(changed) if changed else None
        panel['paired']['unchanged_belief_n']=len(unchanged)
        panel['paired']['unchanged_belief_action_changes']=sum(r['action_changed'] for r in unchanged)
        panel['unique_geometries']=len({r['structure_family'] for r in selected})
        result['panels'][group]=panel
    result['scope']='Development diagnostic on reused validation structures; controls reported separately; not an untouched transfer benchmark.'
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--model',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--checkpoint-hash',required=True)
    p.add_argument('--max-tokens',type=int,default=4096);p.add_argument('--repeats',type=int,default=1)
    p.add_argument('--concurrency',type=int,default=4);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--timeout',type=float,default=180)
    args=p.parse_args()
    if min(args.max_tokens,args.repeats,args.concurrency,args.timeout)<=0:p.error('Budgets must be positive')
    manifest,cases=load();args.output.mkdir(parents=True,exist_ok=False)
    protocol=dict(vars(args),output=str(args.output),temperature=0,top_p=1,top_k=-1,repetition_penalty=1,
        manifest_sha256=sha(HERE/'manifest.json'),inference_determinism='temperature=0 alone does not establish batch invariance; use identical server settings across models')
    (args.output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    lock=threading.Lock()
    def execute(c,rep):
        def call(condition,request):
            seed_condition='paired_P' if condition.startswith('P_') else condition
            seed=int(hashlib.sha256(f'{args.seed}:{c["id"]}:{rep}:{seed_condition}'.encode()).hexdigest()[:8],16)
            body=dict(request,model=args.model,temperature=0,top_p=1,top_k=-1,repetition_penalty=1,max_tokens=args.max_tokens,seed=seed)
            headers={'Content-Type':'application/json'}
            if os.environ.get('OPENAI_API_KEY'):headers['Authorization']='Bearer '+os.environ['OPENAI_API_KEY']
            started=time.monotonic();usage=None
            try:
                req=Request(args.base_url.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers=headers,method='POST')
                with urlopen(req,timeout=args.timeout) as response:payload=json.load(response)
                choice=payload['choices'][0];completion=dict(raw_message=choice['message'],finish_reason=choice['finish_reason']);usage=payload.get('usage')
            except Exception as e:completion=dict(status='infrastructure_failure',error_type=type(e).__name__,http_status=getattr(e,'code',None))
            record=dict(case_id=c['id'],replica=rep,condition=condition,request=body,completion=completion,usage=usage,elapsed_seconds=time.monotonic()-started)
            with lock:
                with (args.output/'calls.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
            return completion
        return dict(run_case(c,call),replica=rep)
    rows=[];jobs=[(c,r) for c in cases for r in range(args.repeats)]
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures=[pool.submit(execute,*job) for job in jobs]
        for fut in as_completed(futures):
            rows.append(fut.result());rows.sort(key=lambda r:(r['case_id'],r['replica']))
            (args.output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
            (args.output/'summary.json').write_text(json.dumps(summarize(rows,len(jobs)),indent=2)+'\n')
            print(f'{len(rows)}/{len(jobs)} complete',flush=True)
    failed=any(r[k]['status']=='infrastructure_failure' for r in rows for k in ('B','O','P_gold','P_model'))
    (args.output/('INCOMPLETE.json' if failed else 'COMPLETE.json')).write_text(json.dumps(protocol,indent=2)+'\n')
    if failed:raise SystemExit('Infrastructure failures; inspect calls.jsonl')

if __name__=='__main__':main()
