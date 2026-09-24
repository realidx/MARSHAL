import tarfile,json,collections,hashlib,pathlib
arcs=['new/d67_training_20260924/d67-first-67-updates.tar.gz','new/d67_125_continuation_20260924/d67-125-continuation.tar.gz']; tasks=collections.defaultdict(list);cfg=[];metrics=[]
for arc in arcs:
 with tarfile.open(arc) as t:
  for m in t:
   if m.name.endswith('/resolved_config.json'):cfg.append(json.load(t.extractfile(m)))
   if m.name.endswith('/metrics.jsonl'):metrics.extend(json.loads(l) for l in t.extractfile(m))
   if '/calls/step-' not in m.name or not m.isfile():continue
   step=int(m.name.split('step-')[-1].split('.')[0]);groups=collections.defaultdict(list)
   for l in t.extractfile(m):
    r=json.loads(l);groups[r['task_id']].append(r)
   for tid,rs in groups.items():
    c=collections.Counter()
    for r in rs:
     s=r['score'];lab='truncated' if r['finish_reason']=='length' else 'invalid' if s['status']!='ok' or r.get('protocol_failure') else 'masked' if s.get('semantic_eligible') is False or s.get('semantic_outcome')=='masked' else 'correct' if s.get('correct') else 'wrong';c[lab]+=1
    req=dict(rs[0]['request']);req.pop('seed',None);req.pop('model',None)
    tasks[tid].append(dict(step=step,kind=rs[0]['kind'],counts=dict(c),reward=sum(r['score']['reward'] for r in rs)/8,effective=any(abs(r['task_advantage'])>1e-12 for r in rs),hash=hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest()))
for es in tasks.values():es.sort(key=lambda e:e['step'])
def diff(a,b,path=''):
 if isinstance(a,dict) and isinstance(b,dict):
  for k in a.keys()|b.keys():yield from diff(a.get(k),b.get(k),path+'/'+k)
 elif a!=b:yield (path,a,b)
print('CONFIG_DIFF',json.dumps(list(diff(*cfg))))
report={}
for kind in ['O','B','Pplus']:
 ts=[es for es in tasks.values() if es[0]['kind']==kind];out={'exposure':dict(collections.Counter(len(es) for es in ts)),'request_changed':sum(len(set(e['hash'] for e in es))>1 for es in ts),'pairs':{}}
 for a,b in [(0,1),(1,2),(0,2)]:
  eligible=[es for es in ts if len(es)>b]; cs=[collections.Counter() for _ in range(2)]
  for es in eligible:
   for c,i in zip(cs,[a,b]):c.update(es[i]['counts'])
  out['pairs'][f'{a+1}-{b+1}']={'n':len(eligible),'counts':list(map(dict,cs)),'reward':[sum(es[i]['reward'] for es in eligible)/len(eligible) for i in [a,b]],'gain':sum(es[b]['reward']>es[a]['reward'] for es in eligible),'loss':sum(es[b]['reward']<es[a]['reward'] for es in eligible),'same':sum(es[b]['reward']==es[a]['reward'] for es in eligible),'always_zero':sum(all(es[i]['reward']==0 for i in range(b+1)) for es in eligible)}
 report[kind]=out
print(json.dumps(report,indent=2));pathlib.Path('new/d67_125_continuation_20260924/exposure_125_audit.json').write_text(json.dumps(report,indent=2))
for step in [65,66,67,68,78,98,118,124]:
 r=next(r for r in metrics if r.get('system/step')==step and 'actor/loss'in r);print('OPTIM',step,{k:r.get(k) for k in ['actor/applied_lr','actor/kl_weighted','actor_train/grad_norm','actor/clip_fraction']})
