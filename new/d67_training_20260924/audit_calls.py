import json,tarfile,hashlib
from pathlib import Path
from collections import defaultdict,Counter
P=Path(__file__).parent
archive=P/'d67-first-67-updates.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='104329df9b88f69cfaceeab04e6a9c4d6865a3dda7703ddd52e57e08659d236e'
tasks=defaultdict(list);validations={};metrics=[];examples={}
with tarfile.open(archive) as tar:
 for m in tar:
  if '/calls/step-' in m.name and m.isfile():
   step=int(m.name.split('step-')[-1].split('.')[0]);groups=defaultdict(list)
   for line in tar.extractfile(m):
    r=json.loads(line);groups[r['group']].append(r)
   for g,rs in groups.items():
    c=Counter()
    for r in rs:
     s=r['score'];label='truncated' if r['finish_reason']=='length' else 'invalid' if s['status']!='ok' or r.get('protocol_failure') else 'masked' if s.get('semantic_outcome')=='masked' or s.get('semantic_eligible') is False else 'correct' if s.get('correct') else 'wrong';c[label]+=1
    r=rs[0];req=dict(r['request']);req.pop('seed',None);req.pop('model',None)
    tasks[r['task_id']].append(dict(step=step,kind=r['kind'],counts=dict(c),effective=any(abs(x['task_advantage'])>1e-12 for x in rs),request_hash=hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest(),tier=r['difficulty']['tier'],tokens=sum(len(x['response_ids']) for x in rs)))
    if c['wrong']==8:examples[r['task_id']]=dict(step=step,request=req,response=r.get('text'),score=r['score'])
  elif '/validation/step-' in m.name and m.name.endswith('.json'):
   v=json.load(tar.extractfile(m));validations[int(m.name.split('step-')[-1].split('.')[0])]=v
  elif m.name.endswith('/metrics.jsonl'):
   metrics=[json.loads(l) for l in tar.extractfile(m)]
summary={}
def rate(e):
 c=e['counts'];n=c.get('correct',0)+c.get('wrong',0)
 return c.get('correct',0)/n if n else None
for kind in ('O','B','Pplus'):
 ts={k:sorted(v,key=lambda e:e['step']) for k,v in tasks.items() if v[0]['kind']==kind};events=[e for v in ts.values() for e in v];counts=Counter();pairs=[];zero=[]
 for tid,es in ts.items():
  for e in es:counts.update(e['counts'])
  if len(es)>1 and all(rate(e)is not None for e in (es[0],es[-1])):
   assert es[0]['request_hash']==es[-1]['request_hash'];pairs.append((tid,rate(es[0]),rate(es[-1])))
  if len(es)>1 and all(e['counts'].get('correct',0)==0 for e in es) and sum(e['counts'].get('wrong',0) for e in es)>=16:zero.append(tid)
 summary[kind]=dict(groups=len(events),unique=len(ts),exposure_histogram=dict(Counter(len(v) for v in ts.values())),counts=dict(counts),effective=sum(e['effective'] for e in events),repeated_scored=len(pairs),first=sum(a for _,a,b in pairs)/len(pairs),last=sum(b for _,a,b in pairs)/len(pairs),gained=sum(b>a for _,a,b in pairs),lost=sum(b<a for _,a,b in pairs),equal=sum(b==a for _,a,b in pairs),repeated_zero=zero,
 all8_then_semantic_error=sum(es[0]['counts'].get('correct')==8 and es[-1]['counts'].get('wrong',0)>0 for es in ts.values() if len(es)>1),
 windows={str(lo):dict(groups=len(es:=[e for e in events if lo<=e['step']<hi]),effective=sum(e['effective'] for e in es)) for lo,hi in [(0,20),(20,40),(40,50),(50,67)]})
summary['validation']={step:{k:v for k,v in x['metrics'].items() if k.endswith(('macro_accuracy','scored_coverage','isolated_B_both_correct','must_change/both_correct'))} for step,x in sorted(validations.items())}
summary['validation_flips']={}
for lo,hi in [(0,20),(20,40),(40,60),(0,60)]:
 a={r['task']['id']:r for r in validations[lo]['bp_calls']};b={r['task']['id']:r for r in validations[hi]['bp_calls']};out={}
 for kind in ('O','B','Pplus'):
  common=[k for k in a.keys()&b.keys() if a[k]['task']['paired_view']==kind and a[k]['score'].get('correct') is not None and b[k]['score'].get('correct') is not None]
  out[kind]=dict(comparable=len(common),gained=[k for k in common if not a[k]['score']['correct'] and b[k]['score']['correct']],lost=[k for k in common if a[k]['score']['correct'] and not b[k]['score']['correct']])
 summary['validation_flips'][f'{lo}-{hi}']=out
(P/'call_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
(P/'per_task.jsonl').write_text(''.join(json.dumps(dict(id=k,events=sorted(v,key=lambda e:e['step'])))+'\n' for k,v in sorted(tasks.items())))
(P/'repeated_zero_examples.json').write_text(json.dumps({k:examples[k] for kind in ('O','B','Pplus') for k in summary[kind]['repeated_zero'] if k in examples},indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('O','B','Pplus')},indent=2))
print('flips',json.dumps({s:{k:{'gained':len(v['gained']),'lost':len(v['lost'])} for k,v in d.items()} for s,d in summary['validation_flips'].items()}))
