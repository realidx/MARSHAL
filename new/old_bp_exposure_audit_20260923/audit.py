"""Offline exposure reconstruction; no training or model calls."""
import json,gzip
from pathlib import Path
from collections import Counter,defaultdict
from training.social_mixed.curriculum_sampling import select
from training.social_mixed.distribution_sampling import select as baseline
ROOT=Path(__file__).resolve().parents[2]
base=ROOT/'new/training_chain_evidence_20260921/old_bp'
rows=[json.loads(l) for l in (ROOT/'examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl').open()]
out={'calls_matches':[], 'coverage':{}, 'validation':[]}
for p in sorted((base/'calls').glob('*.gz')):
 s=int(p.name.split('-step-')[1].split('.')[0]);actual={r['task_id'] for r in map(json.loads,gzip.open(p,'rt'))}
 out['calls_matches'].append(dict(file=p.name,match=actual=={r['id'] for r in select(rows,s,42)}))
metrics=[json.loads(l) for l in (base/'metrics/860494.jsonl').open()]
out['first100_group_count_matches']=all(len(select(rows,r['system/step'],42))*8==r['rows'] for r in metrics if 'rows' in r and 0<=r['system/step']<100)
for n in (50,100,200):
 counts=Counter(t['id'] for s in range(n) for t in select(rows,s,42))
 roles={}
 for role in ('bridge','history','reduced','result'):
  ts=[t for t in rows if role in t.get('practice_units',{})];vs=[counts[t['id']] for t in ts]
  roles[role]=dict(total=len(ts),seen=sum(v>0 for v in vs),minimum=min(vs),maximum=max(vs))
 out['coverage'][n]=dict(groups=sum(counts.values()),seen=len(counts),total=len(rows),roles=roles)
for p in sorted((base/'validation').glob('*.gz')):
 r=json.load(gzip.open(p,'rt'));groups=defaultdict(list);correct={}
 for c in r['bp_calls']:
  t=c['task'];v=int(c['score'].get('correct',False));correct[t['id']]=v
  groups[t['task']+'/'+t['pool']].append(v)
 out['validation'].append(dict(file=p.name,step=int(p.name.split('-step-')[1].split('.')[0]),groups={k:[sum(v),len(v)] for k,v in groups.items()},correct=correct))
out['validation'].sort(key=lambda r:r['step'])
for prev,r in zip(out['validation'],out['validation'][1:]):
 a,b=prev['correct'],r['correct'];keys=a.keys()&b.keys();r['transitions']=dict(lost=sum(a[k] and not b[k] for k in keys),gained=sum(not a[k] and b[k] for k in keys))
(ROOT/'new/old_bp_exposure_audit_20260923/results.json').write_text(json.dumps(out,indent=2)+'\n')
print('calls match',all(r['match'] for r in out['calls_matches']),'first100 counts',out['first100_group_count_matches'])
print(json.dumps(out['coverage'],indent=2))
for r in out['validation']:
 if r['step'] in (0,50,100,140,200):print(r['step'],r['groups'])
print('transitions',[(r['step'],r.get('transitions')) for r in out['validation']])
