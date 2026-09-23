"""Observed training feedback only. Sampling outcomes are not mastery certificates."""
import tarfile,gzip,json,hashlib
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'new/task_learning_audit_20260924'

def fingerprint(r):
 q=dict(r['request']);q.pop('seed',None);q.pop('model',None)
 return hashlib.sha256(json.dumps(q,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def ingest(lines,step,source,store):
 groups=defaultdict(list)
 for line in lines:
  r=json.loads(line);groups[r['group']].append(r)
 for group,rs in groups.items():
  counts=Counter()
  for r in rs:
   s=r['score'];finish=r.get('finish_reason',r.get('completion',{}).get('finish_reason'))
   if finish=='length':label='truncated'
   elif s.get('status')!='ok' or r.get('protocol_failure'):label='invalid'
   elif s.get('semantic_outcome')=='masked' or s.get('semantic_eligible') is False:label='masked'
   else:label='correct' if s.get('correct',s.get('reward')==1) else 'wrong'
   counts[label]+=1
  first=rs[0];store[first['task_id']].append(dict(step=step,source=source,group=group,kind=first['kind'],skill=first['skill'],kernel=first['kernel'],canonical=first.get('canonical_id'),slot=first.get('exposure_slot'),request_sha256=fingerprint(first),samples=len(rs),counts=dict(counts),effective=any(abs(r.get('task_advantage',0))>1e-12 for r in rs)))

stores={'old_BP_observed':defaultdict(list),'new_D':defaultdict(list)}
for p in sorted((ROOT/'new/training_chain_evidence_20260921/old_bp/calls').glob('*.gz')):
 with gzip.open(p,'rt') as f:ingest(f,int(p.name.split('-step-')[1].split('.')[0]),p.name,stores['old_BP_observed'])
for fn in ['d0-72-874127.tar.gz','d72-148-875169.tar.gz']:
 with tarfile.open(ROOT/'new/d_evidence_20260924/training'/fn) as t:
  for m in t.getmembers():
   if m.name.startswith('./calls/step-') and m.name.endswith('.jsonl'):
    ingest(t.extractfile(m),int(m.name.split('step-')[1].split('.')[0]),fn,stores['new_D'])
reports={}
for name,store in stores.items():
 records=[];aggregate=defaultdict(Counter)
 for tid,events in sorted(store.items()):
  events.sort(key=lambda e:(e['step'],e['source']));kind=events[0]['kind'];total=Counter()
  for e in events:total.update(e['counts'])
  flips=[]
  for a,b in zip(events,events[1:]):
   if a['request_sha256']!=b['request_sha256']:continue
   if a['counts'].get('correct')==8 and b['counts'].get('wrong',0)>0:
    flips.append(dict(start=a['step'],end=b['step'],next_counts=b['counts']))
  recovery=[]
  for f in flips:
   if any(e['step']>f['end'] and e['counts'].get('correct')==8 and e['request_sha256']==next(x['request_sha256'] for x in events if x['step']==f['end']) for e in events):recovery.append(f)
  zero_correct=total['correct']==0 and total['wrong']>0
  persistent=zero_correct and len(events)>=3 and total['wrong']>=24
  row=dict(task_id=tid,kind=kind,skill=events[0]['skill'],kernel=events[0]['kernel'],exposures=len(events),counts=dict(total),never_observed_correct=zero_correct,persistent_failure_observed=persistent,all_correct_then_error=flips,recovered_to_8_of_8=recovery,events=events)
  records.append(row);a=aggregate[kind];a['unique_tasks']+=1;a['groups']+=len(events);a['effective_groups']+=sum(e['effective'] for e in events);a.update(total);a['revisited_tasks']+=len(events)>1;a['never_correct_tasks']+=zero_correct;a['persistent_failure_tasks']+=persistent;a['tasks_with_8_correct_then_error']+=bool(flips);a['tasks_with_recovery']+=bool(recovery)
  a['tasks_last_all_correct']+=events[-1]['counts'].get('correct')==8
 (OUT/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in records))
 reports[name]=dict(by_task={k:dict(v) for k,v in aggregate.items()},observed_steps=sorted({e['step'] for es in store.values() for e in es}),examples={k:dict(persistent=[r['task_id'] for r in records if r['kind']==k and r['persistent_failure_observed']][:8],recovery=[r['task_id'] for r in records if r['kind']==k and r['recovered_to_8_of_8']][:8]) for k in aggregate})
(OUT/'summary.json').write_text(json.dumps(reports,indent=2)+'\n')
print(json.dumps({k:{'by_task':v['by_task'],'observed_steps_count':len(v['observed_steps']),'examples':v['examples']} for k,v in reports.items()},indent=2))
