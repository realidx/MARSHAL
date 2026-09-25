import json,tarfile,collections,statistics,hashlib,math
from pathlib import Path
ROOT=Path(__file__).parent
output={}
for arm in ['13','24']:
 t=tarfile.open(ROOT/f'training_micro{arm}.tar.gz');g=collections.defaultdict(list);period=collections.defaultdict(collections.Counter);errors=collections.Counter();per={};met=[];validation={}
 for n in t.getnames():
  if '/calls/step-' not in n or not n.endswith('.jsonl'):continue
  step=int(n.split('step-')[1].split('.')[0]);job=n.split('/')[2].split('-')[-1]
  if not ((job=='878813' and step<10) or job=='878930'):continue
  for l in t.extractfile(n):
   r=json.loads(l);g[(step,r['task_id'])].append(r)
 for (step,tid),rs in sorted(g.items()):
  c=collections.Counter();vals=[r['score']['reward'] for r in rs if r['score']['status']!='format_failure' and r['completion']['finish_reason']!='length'];mean=statistics.mean(vals) if vals else 0;std=statistics.pstdev(vals) if vals else 0
  for r in rs:
   ok=r['score']['status']!='format_failure' and r['completion']['finish_reason']!='length';a=(r['score']['reward']-mean)/(std+1e-6) if ok else 0
   errors['advantage_mismatch']+=abs(a-r['task_advantage'])>1e-6
   errors['weight_mismatch']+=r['loss_weight']!=1
   c['calls']+=1;c['correct']+=r['score'].get('correct') is True;c['trunc']+=r['completion']['finish_reason']=='length';c['invalid']+=r.get('protocol_failure')=='invalid_action';c['tokens']+=len(r['response_ids']);c['positive']+=r['task_advantage']>0
  c['groups']=1;c['active']=any(abs(r['task_advantage'])>1e-8 for r in rs)
  period[(step//10,rs[0]['kind'])].update(c)
  entry=per.setdefault(tid,dict(kind=rs[0]['kind'],events=[]));entry['events'].append(dict(step=step,**c))
 for n in t.getnames():
  if n.endswith('/metrics.jsonl'):
   job=n.split('/')[2].split('-')[-1]
   for l in t.extractfile(n):
    r=json.loads(l)
    if 'actor/applied_lr' in r:met.append(dict(job=job,**r))
  if '/validation/step-' in n and n.endswith('.json'):
   step=int(n.split('step-')[1].split('.')[0]);job=n.split('/')[2].split('-')[-1]
   if job=='878930' or (job=='878813' and step<=10):
    r=json.load(t.extractfile(n));cs=r.get('bp_calls',[]);ct=collections.defaultdict(collections.Counter)
    for x in cs:
     v=x['task'].get('paired_view',x['task']['task']);ct[v]['n']+=1;ct[v]['correct']+=x['score'].get('correct') is True;ct[v]['trunc']+=x['completion']['finish_reason']=='length'
    validation[step]={k:dict(v) for k,v in ct.items()}
 output[arm]=dict(periods={str(k):dict(v) for k,v in period.items()},errors=dict(errors),per_task=per,validation=validation,total_tokens=sum(v['tokens'] for v in period.values()))
 print('ARM',arm,'tasks',len(per),'exposures',collections.Counter(len(v['events']) for v in per.values()),'tokens',output[arm]['total_tokens'],'errors',errors)
 print('PERIODS',output[arm]['periods']);print('VALIDATION',validation)
 for tid,v in per.items():
  es=v['events'];rate=lambda xs:sum(x['correct'] for x in xs)/sum(x['calls'] for x in xs)
  print(tid,v['kind'],'first5',round(rate(es[:5]),3),'last5',round(rate(es[-5:]),3),'active',sum(e['active'] for e in es))
(ROOT/'analysis.json').write_text(json.dumps(output,indent=2))
