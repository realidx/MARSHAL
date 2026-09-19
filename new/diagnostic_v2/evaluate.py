"""Offline scoring with missingness and paired condition records preserved."""
import json
from collections import defaultdict,Counter
from build import HERE,ROOT,sha
from training.b_sft.social_bp_training import reward

def load():
    m=json.loads((HERE/'manifest.json').read_text())
    for n,h in m['files'].items():
        if sha(HERE/n)!=h:raise ValueError('Frozen file mismatch: '+n)
    for n,h in m.get('dependencies',{}).items():
        if sha(ROOT/n)!=h:raise ValueError('Scoring dependency changed: '+n)
    tasks={t['id']:t for t in map(json.loads,(HERE/'tasks.jsonl').read_text().splitlines())}
    req={r['task_id']:r for r in map(json.loads,(HERE/'requests.jsonl').read_text().splitlines())}
    assert tasks.keys()==req.keys()
    return m,tasks,req

def score(t,c):
    if t['task']!='analytic_B':return reward(t,c)
    if c.get('status')=='infrastructure_failure':return dict(status='infrastructure_failure',correct=None)
    if c.get('finish_reason')=='length':return dict(status='truncated',correct=False)
    try:
        calls=c['raw_message']['tool_calls'];assert len(calls)==1
        f=calls[0]['function'];assert f['name']=='SUBMIT_BELIEFS'
        a=json.loads(f['arguments']);assert set(a)=={'possible_preferences','favored'}
        p=a['possible_preferences'];assert isinstance(p,list) and p and all(isinstance(x,str) for x in p)
        assert len(p)==len(set(p)) and set(p)<= {'want','neutral','avoid'}
        assert a['favored'] in ('want','neutral','avoid','undetermined')
        gold=t['teacher']['gold'];correct=set(p)==set(gold['possible_preferences']) and a['favored']==gold['favored']
        return dict(status='ok',correct=correct)
    except (KeyError,ValueError,AssertionError,TypeError):return dict(status='format_failure',correct=False)

def summarize(records,tasks,repeats):
    indexed={};scored=[]
    for r in records:
        key=(r['task_id'],r['replica'])
        if key in indexed or key[0] not in tasks or type(key[1]) is not int or not 0<=key[1]<repeats:raise ValueError('Unexpected or duplicate record')
        t=tasks[key[0]];row=dict(task_id=key[0],replica=key[1],case_id=t['case_id'],condition=t['condition'],score=score(t,r['completion']))
        indexed[key]=row;scored.append(row)
    out={}
    for condition in sorted({t['condition'] for t in tasks.values()}):
        ids=[t['id'] for t in tasks.values() if t['condition']==condition];n=len(ids)*repeats
        selected=[r for r in scored if r['condition']==condition]
        healthy=len(selected)==n and all(r['score']['correct'] is not None for r in selected)
        out[condition]=dict(planned=n,returned=len(selected),statuses=dict(Counter(r['score']['status'] for r in selected)),
            accuracy=sum(r['score']['correct'] is True for r in selected)/n if healthy else None)
    paired=[]
    for case in sorted({t['case_id'] for t in tasks.values()}):
        for rep in range(repeats):
            paired.append(dict(case_id=case,replica=rep,conditions={t['condition']:indexed.get((t['id'],rep),{}).get('score') for t in tasks.values() if t['case_id']==case}))
    per_task={tid:dict(condition=t['condition'],scores=[indexed.get((tid,rep),{}).get('score') for rep in range(repeats)]) for tid,t in tasks.items()}
    return dict(conditions=out,per_task=per_task,paired_cases=paired,note='Independent contexts; pairing does not establish internal causal mediation. Unit topics must also be reported separately.'),scored

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--responses');p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    _,tasks,_=load()
    if a.responses:
        print(json.dumps(summarize(list(map(json.loads,open(a.responses))),tasks,a.repeats)[0],indent=2))
    else:print('Verified',len(tasks),'frozen tasks; no model calls')
