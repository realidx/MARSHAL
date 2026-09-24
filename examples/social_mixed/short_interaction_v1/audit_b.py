"""Reproducible B failure audit; preserves representative raw requests/answers."""
import collections,json,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parent
arcs=['new/d67_training_20260924/d67-first-67-updates.tar.gz','new/d67_125_continuation_20260924/d67-125-continuation.tar.gz']
groups=collections.defaultdict(lambda:collections.defaultdict(list))
for arc in arcs:
 with tarfile.open(arc) as tar:
  for m in tar:
   if '/calls/step-' not in m.name or not m.isfile():continue
   step=int(m.name.split('step-')[-1].split('.')[0])
   for line in tar.extractfile(m):
    r=json.loads(line)
    if r['kind']=='B':groups[r['task_id']][step].append(r)
def label(r):
 if r['finish_reason']=='length':return 'truncated'
 if r['score']['status']!='ok' or r.get('protocol_failure'):return 'invalid'
 return 'correct' if r['score'].get('correct') else 'wrong'
out=[];examples=[]
for tid,steps in groups.items():
 counts=collections.Counter(label(r) for rs in steps.values() for r in rs)
 item=dict(task_id=tid,exposures=len(steps),steps=sorted(steps),counts=dict(counts))
 item['never_correct']=counts['correct']==0
 out.append(item)
 if len(steps)>=3 and item['never_correct']:
  examples.append(dict(**item,request=next(iter(steps.values()))[0]['request'],answers=[dict(step=s,label=label(r),text=r.get('text'),completion=r.get('completion'),score=r['score']) for s,rs in sorted(steps.items()) for r in rs]))
(ROOT/'b_failure_audit.json').write_text(json.dumps(dict(tasks=out,three_exposure_never_correct=[{k:v for k,v in e.items() if k not in ('request','answers')} for e in examples]),indent=2))
(ROOT/'b_failure_examples.json').write_text(json.dumps(examples,indent=2))
print('three exposure never correct',len(examples));print(collections.Counter(label(r) for steps in groups.values() for rs in steps.values() for r in rs))
for e in examples:print(e['task_id'],e['counts'])
