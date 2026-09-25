import json,tarfile,collections,hashlib,statistics
from pathlib import Path
ROOT=Path(__file__).parent
out={};shared={};metrics={}
for arm in ['d24v2','op16v2']:
 periods=collections.defaultdict(collections.Counter);tasks={};requests={};val={};errors=collections.Counter()
 with tarfile.open(ROOT/f'training_{arm}.tar.gz') as tar:
  for n in tar.getnames():
   if n.startswith('./calls/step-') and n.endswith('.jsonl'):
    step=int(n.split('step-')[1].split('.')[0]);groups=collections.defaultdict(list)
    for l in tar.extractfile(n):
     r=json.loads(l);groups[r['task_id']].append(r)
     if r['kind']!='B':
      req=dict(r['request']);req.pop('model',None)
      requests[(step,r['task_id'],r['replica'])]=hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest()
     weight=1 if arm=='d24v2' else 2/3
     for key in ['task_weight','protocol_weight','kl_weight','loss_weight']:errors[key]+=abs(r[key]-weight)>1e-10
    for tid,rs in groups.items():
     c=collections.Counter(n=len(rs),correct=sum(r['score'].get('correct') is True for r in rs),trunc=sum(r['completion']['finish_reason']=='length' for r in rs),invalid=sum(r['protocol_failure']=='invalid_action' for r in rs),tokens=sum(len(r['response_ids']) for r in rs),groups=1,active=int(any(abs(r['task_advantage'])>1e-9 for r in rs)))
     periods[(step//10,rs[0]['kind'])].update(c)
     tasks.setdefault(tid,dict(kind=rs[0]['kind'],events=[]))['events'].append(dict(step=step,**c))
   elif n.startswith('./validation/step-') and n.endswith('.json'):
    step=int(n.split('step-')[1].split('.')[0]);v=json.load(tar.extractfile(n));ct=collections.defaultdict(collections.Counter)
    for r in v['bp_calls']:
     kind=r['task'].get('paired_view',r['task']['task']);ct[kind].update(dict(n=1,correct=int(r['score'].get('correct') is True),scorable=int(r['score'].get('correct') is not None),trunc=int(r['completion']['finish_reason']=='length')))
    val[step]={k:dict(v) for k,v in ct.items()}
  metrics[arm]=[json.loads(l) for l in tar.extractfile('./metrics.jsonl')]
 for task in tasks.values():task['events'].sort(key=lambda e:e['step'])
 shared[arm]=requests
 out[arm]=dict(periods={str(k):dict(v) for k,v in sorted(periods.items())},tasks=tasks,validation=val,weight_errors=dict(errors))
 with tarfile.open(ROOT/f'calbench_{arm}.tar.gz') as tar:
  out[arm]['calbench']=json.load(tar.extractfile('./games/results.json'))
 print('\nARM',arm,'weight',errors,'exposures',collections.Counter(len(t['events']) for t in tasks.values()))
 print('PERIODS',out[arm]['periods']);print('VALIDATION',val)
 for tid,t in tasks.items():
  if t['kind']=='B':print('B',tid,[(sum(e[k] for e in es)) for es in [t['events'][:5],t['events'][-5:]] for k in ['correct','n','trunc']], 'active',sum(e['active'] for e in t['events']))
print('SHARED_REQUEST_MISMATCH',sum(shared['d24v2'].get(k)!=v for k,v in shared['op16v2'].items()),len(shared['op16v2']))
for arm,rs in metrics.items():
 lrs=[r['actor/applied_lr'] for r in rs if 'actor/applied_lr' in r];print('LR',arm,len(lrs),lrs[:2],lrs[-2:]);out[arm]['lrs']=lrs
(ROOT/'analysis.json').write_text(json.dumps(out,indent=2))
