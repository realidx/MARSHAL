import json,tarfile,collections,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from training.b_sft.social_named_probe import present
root=Path('new/micro_learning_evidence_20260925');out={};samples=[]
common={'action':'OFFER','partner_id':1,'proposer_action':[1,0],'partner_action':[0,1]}
for arm,bank in [('13','micro_learning_v1'),('24','micro_learning_24_v1')]:
 tasks={r['id']:r['task'] for r in map(json.loads,open('examples/social_mixed/'+bank+'/tasks.jsonl'))};stats=collections.defaultdict(collections.Counter);per=collections.defaultdict(collections.Counter)
 with tarfile.open(root/f'training_micro{arm}.tar.gz') as tar:
  for n in tar.getnames():
   if '/calls/step-' not in n or not n.endswith('.jsonl'):continue
   step=int(n.split('step-')[1].split('.')[0]);job=n.split('/')[2].split('-')[-1]
   if not ((job=='878813' and step<10) or job=='878930'):continue
   for l in tar.extractfile(n):
    r=json.loads(l);kind=r['kind'];tid=r['task_id']
    if kind not in ['O','B']:continue
    t=tasks[tid];c=collections.Counter(n=1,correct=int(r['score'].get('correct') is True),trunc=int(r['completion']['finish_reason']=='length'));msg=r['completion']['raw_message'];content=msg.get('content') or '';action=None
    try:
     calls=msg.get('tool_calls') or [];assert len(calls)==1
     f=calls[0]['function'];args=json.loads(f['arguments']);assert r['completion']['finish_reason']!='length'
     if kind=='O':
      obj={('response' if f['name'] in ['ACCEPT','REJECT'] else 'action'):f['name'],**args};vis=present(t,t.get('name_variant',0));action=t['input']['legal_actions'][vis['legal_actions'].index(obj)];c['parsed']=1;c['common']=int(action==common);c['action:'+json.dumps(action,sort_keys=True)]=1
     else:
      assert f['name']=='SUBMIT_BELIEFS';j=args['judgments'][0];c['parsed']=1;c['full_undetermined']=int(set(j['possible_preferences'])=={'want','neutral','avoid'} and j['favored']=='undetermined');c['label:'+str(sorted(j['possible_preferences']))+'/'+j['favored']]=1
    except (AssertionError,ValueError,KeyError,TypeError,IndexError):pass
    stats[(kind,step//10)].update(c);per[(tid,step//10)].update(c)
    if step in [0,1,38,39] and r['replica']==0:
     samples.append(dict(arm=arm,step=step,tid=tid,kind=kind,correct=r['score'].get('correct'),action=action,text=content))
 out[arm]={'period':{str(k):dict(v) for k,v in stats.items()},'task_period':{str(k):dict(v) for k,v in per.items()}}
 print('ARM',arm)
 for k,v in sorted(stats.items()):print(k,{a:b for a,b in v.items() if not a.startswith(('action:','label:'))})
 for (tid,p),v in sorted(per.items()):
  if p in [0,3] and tid.endswith('-O'):print(tid,p,v['parsed'],v['common'],v['trunc'])
(root/'shortcut_audit.json').write_text(json.dumps(out,indent=2));(root/'shortcut_samples.json').write_text(json.dumps(samples,indent=2,ensure_ascii=False))
