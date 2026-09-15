"""Audit fixed readable B smoke results without additional model calls."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from training.b_sft.social_b_evaluation import request, payload, score_attempt, summarize
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'new/local_data/social_runs/b_eval_readable_smoke_r1'
DATA=ROOT/'new/local_data/social_runs/b_curriculum_eval_v1'
def rows(path):return list(map(json.loads,path.read_text().splitlines()))
def main():
    tasks={t['id']:t for t in rows(DATA/'tasks.jsonl')}
    calls=rows(OUT/'calls.jsonl');checks=rows(OUT/'checkpoints.jsonl')
    jobs=json.loads((OUT/'jobs.json').read_text());config=json.loads((OUT/'run_config.json').read_text())
    summary=json.loads((OUT/'summary.json').read_text());fail=[]
    def check(ok,label):
        if not ok:fail.append(label)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    sources={p:sha(ROOT/p.split('/mas/',1)[1])==h for p,h in config['source_hashes'].items()}
    data={p:sha(DATA/p)==h for p,h in config['data_hashes'].items()}
    check(all(sources.values()),'source hashes');check(all(data.values()),'data hashes')
    selected=json.loads((ROOT/'new/local_data/social_runs/b_eval_readable_smoke_jobs.json').read_text())
    check(sorted(jobs)==sorted(selected),'fixed subset')
    ci={(r['mode'],r['job'],r['checkpoint']):r for r in calls}
    check(len(ci)==len(calls)==35,'35 unique first calls')
    for mode,jid,ids in jobs:
        prior=[]
        for tid in ids:
            r=ci[mode,jid,tid];t=tasks[tid]
            check(r['attempt']==0,'no retry')
            check(request(t,mode=mode,prior_turns=prior)==r['request'],'exact request '+tid)
            check(score_attempt(t,r)==r['score'],'score '+tid)
            check(0<=r['usage']['completion_tokens']<=1024,'tokens '+tid)
            events=[]
            for m in r['request']['messages']:
                if m['role']=='user':
                    d=json.loads(m['content']);events.extend(d.get('history',d.get('new_history',[])))
            shown=payload(t['input'])
            check(events==shown['history'],'lossless events '+tid)
            for p,vector in enumerate(t['input']['public_state']['commitments']):
                check(shown['public_state']['committed_action_ids'][str(p)]==[f'action_{i}' for i,b in enumerate(vector) if b==1],'commitment conversion')
            if mode=='sequential':prior.append(dict(task=t,message=r['raw_message']))
    for cr in checks:
        r=ci[cr['mode'],cr['job'],cr['checkpoint']]
        check(cr['first']==cr['final']==r['score'],'checkpoint score')
    for m in ('independent','sequential'):
        for w in ('first','final'):
            s=summarize([r[w] for r in checks if r['mode']==m])
            check(all(summary['modes'][m][w][k]==v for k,v in s.items()),'summary '+m+w)
    old=rows(ROOT/'new/local_data/social_runs/b_eval_native_r1/checkpoints.jsonl')
    oi={(r['mode'],r['job'],r['checkpoint']):r for r in old}
    comparison={}
    for m in ('independent','sequential'):
        keys=[k for k in ci if k[0]==m]
        comparison[m]=dict(points=len(keys),old_first_statuses=dict(Counter(oi[k]['first']['status'] for k in keys)),
            old_first_exact=sum(oi[k]['first']['exact'] is True for k in keys),new_first_exact=sum(ci[k]['score']['exact'] for k in keys))
    js=[j for r in calls for j in r['score']['judgments']]
    pairs=rows(DATA/'pairs.jsonl');category={}
    for cat in ('formation','maintain','update','uninformative'):
        ps=[p for p in pairs if p['category']==cat and ('independent',p['after'],p['after']) in ci]
        exact=0
        for p in ps:
            j=next(j for j in ci['independent',p['after'],p['after']]['score']['judgments'] if (j['player'],j['goal'])==(p['query']['player'],p['query']['goal']))
            exact+=j['set_exact'] and j['favored_exact']
        category[cat]=dict(pair_endpoints=len(ps),query_exact=exact)
    report=dict(failures=fail,source_hashes_match=sources,data_hashes_match=data,calls=len(calls),
        max_prompt_tokens=max(r['usage']['prompt_tokens'] for r in calls),max_completion_tokens=max(r['usage']['completion_tokens'] for r in calls),
        favored_rule_violations=sum((len(j['prediction']['possible_preferences'])>1 and j['prediction']['favored']!='undetermined') or (len(j['prediction']['possible_preferences'])==1 and j['prediction']['favored']!=j['prediction']['possible_preferences'][0]) for j in js),
        same_checkpoint_comparison=comparison,independent_selected_pair_queries=category,
        sampling_note='Same temperature 0.7; default filtering and seed were not explicitly fixed. This is a selected regression subset, not a generalization estimate.')
    (OUT/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
