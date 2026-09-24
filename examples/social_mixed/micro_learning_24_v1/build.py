"""Build a frozen, evidence-selected micro dataset; no model calls."""
import json,tarfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
read=lambda p:list(map(json.loads,(ROOT/p).read_text().splitlines()))
old=read('new/task_learning_audit_20260924/old_BP_main.jsonl');new=read('new/task_learning_audit_20260924/new_D.jsonl')
# Keep the eight legacy P acquisition cases; supplement only with evidenced B/O.
base=read('examples/social_mixed/micro_learning_v1/tasks.jsonl')
selected=[dict(r['evidence']) for r in base if r['evidence']['source_cohort']=='old']
bad={r['id'] for r in json.loads((ROOT/'new/dataset_redesign_20260924/b_prompt_contract.json').read_text())}
def rate(events):
 return sum(e['counts'].get('correct',0) for e in events)/sum(e['samples'] for e in events)
for kind in ('B','O'):
 candidates=[]
 for r in new:
  e=r['events']
  if r['kind']!=kind or r['task_id'] in bad or len(e)<4:continue
  gain=rate(e[-2:])-rate(e[:2])
  if gain<.125 or rate(e[-2:])<.5 or sum(x['effective'] for x in e)<2:continue
  candidates.append(dict(r,source_cohort='paired',selection_gain=gain))
 candidates.sort(key=lambda r:(-r['selection_gain'],-rate(r['events'][-2:]),r['task_id']))
 selected.extend(candidates[:8])
# Seven eligible paired B; eighth is an old formation task, without previous belief.
r=next(r for r in old if r['task_id']=='aa5cada26d5bda6a337c')
assert len(r['events'])==3 and rate(r['events'][-1:])-rate(r['events'][:1])>=.125
selected.append(dict(r,source_cohort='old',evidence_tier='weaker: only three exposures; not stable mastery'))
assert len(selected)==24
banks={'old':{t['id']:t for t in read('examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl')},'paired':{t['id']:t for t in read('examples/social_mixed/paired_bank_v2/tasks.jsonl')}}
wanted={r['task_id']:r for r in selected};requests={};examples={};checks=0
archives=['new/old_bp_full_training_calls_20260924/860494-steps-0-102.tar.gz','new/old_bp_full_training_calls_20260924/861241-steps-100-205.tar.gz','new/d_evidence_20260924/training/d0-72-874127.tar.gz','new/d_evidence_20260924/training/d72-148-875169.tar.gz']
from training.b_sft.social_bp_training import reward
for archive in archives:
 with tarfile.open(ROOT/archive) as tf:
  for m in tf:
   if '/step-' not in m.name or 'calls/' not in m.name or not m.name.endswith('.jsonl'):continue
   step=int(m.name.split('step-')[1].split('.')[0])
   if '860494' in archive and step>99:continue
   for line in tf.extractfile(m):
    r=json.loads(line);tid=r['task_id']
    if tid not in wanted:continue
    req=dict(r['request']);req.pop('seed',None);req.pop('model',None)
    if tid in requests and requests[tid]!=req:raise ValueError('Request changed '+tid)
    requests[tid]=req
    task=banks[wanted[tid]['source_cohort']][tid]
    s=reward(task,r['completion']);assert s['correct']==r['score']['correct'],(tid,step,s,r['score'])
    checks+=1
    key=(tid,bool(s['correct']))
    examples.setdefault(key,dict(task_id=tid,step=step,archive=archive,completion=r['completion'],score=r['score'],advantage=r['task_advantage']))
records=[]
for e in selected:
 tid=e['task_id'];task=banks[e['source_cohort']][tid];assert task['split']=='train'
 records.append(dict(id=tid,task=task,request=requests[tid],evidence=e,scorer='training.b_sft.social_bp_training.reward'))
def write(name,rows):
 (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
write('tasks.jsonl',records);write('examples.jsonl',examples.values())
pools={k:sorted([r['id'] for r in records if r['evidence']['kind']==k]) for k in ('O','P','B')}
assert all(len(v)==8 for v in pools.values())
write('schedule.jsonl',[dict(update=i,task_ids=[tid for k in ('O','P','B') for tid in pools[k][4*(i%2):4*(i%2)+4]],replicas=8) for i in range(40)])
(OUT/'manifest.json').write_text(json.dumps(dict(version='micro-learning-24-v1',tasks=len(records),updates=40,exposures_per_task=20,replicas=8,answers_per_update=96,historical_calls_rescored=checks,selection='P: legacy acquisition set; B/O: >=4 exposures, first2 to last2 gain >=0.125, last2 >=0.5, >=2 effective groups; known contract conflicts excluded',excluded=['7ba55d2ed899c21ae256-B: documented prompt/gold conflict'],sha256={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','schedule.jsonl','examples.jsonl']}),indent=2))
print(len(records),checks)
