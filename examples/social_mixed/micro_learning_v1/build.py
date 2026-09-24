"""Build a frozen, evidence-selected micro dataset; no model calls."""
import json,tarfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
read=lambda p:list(map(json.loads,(ROOT/p).read_text().splitlines()))
old=read('new/task_learning_audit_20260924/old_BP_main.jsonl');new=read('new/task_learning_audit_20260924/new_D.jsonl')
selected=[]
for source,rows in [('old',old),('paired',new)]:
 for r in rows:
  e=r['events'];last=e[-3:]
  if len(e)<3 or e[0]['counts'].get('correct',0)>3:continue
  if sum(x['counts'].get('correct',0) for x in last)/sum(x['samples'] for x in last)<.75:continue
  if sum(x['effective'] for x in e)<2:continue
  if source=='old' and r['kind']!='P':continue
  if source=='paired' and r['kind'] not in ('B','O'):continue
  if r['task_id']=='7ba55d2ed899c21ae256-B':continue # documented prompt/gold mismatch
  selected.append(dict(r,source_cohort=source))
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
write('schedule.jsonl',[dict(update=i,task_ids=[r['id'] for r in records[i%len(records):]+records[:i%len(records)]],replicas=8) for i in range(40)])
(OUT/'manifest.json').write_text(json.dumps(dict(version='micro-learning-v1',tasks=len(records),updates=40,exposures_per_task=40,replicas=8,answers_per_update=8*len(records),historical_calls_rescored=checks,selection='first <=3/8; final3 >=75%; >=3 exposures; >=2 effective groups',excluded=['7ba55d2ed899c21ae256-B: documented prompt/gold conflict'],sha256={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','schedule.jsonl','examples.jsonl']}),indent=2))
print(len(records),checks)
