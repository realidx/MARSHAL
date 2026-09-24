import tarfile,json,collections,statistics,copy
from training.social_mixed.reasoning_scoring import score
from training.social_mixed.reasoning_training import group_advantages
root='new/d_interaction_chains_20260925/'
bank={r['id']:r for r in map(json.loads,open('examples/social_mixed/interaction_bank_v1/tasks.jsonl'))}
allrows={};out={}
for label,file in [('old','d0-25-877247.tar.gz'),('fixed','d0-43-878558-fixed.tar.gz')]:
 t=tarfile.open(root+'training/'+file);rows=[];stats=collections.defaultdict(collections.Counter);groups=collections.defaultdict(list)
 for n in t.getnames():
  if '/calls/step-' not in n:continue
  step=int(n.split('step-')[1].split('.')[0])
  if step>=20:continue
  rr=[dict(json.loads(l),step=step) for l in t.extractfile(n)];rows+=rr
  for r in rr:groups[r['group']].append(r)
 for g,rs in groups.items():
  key=rs[0]['kind']+'/'+rs[0]['training_mode'];s=stats[key];s['groups']+=1;s['active']+=any(abs(r['task_advantage'])>1e-8 for r in rs)
  short=rs[0]['training_mode']=='short_interaction'
  if not short:
   corrected=[score(dict(bank[r['task_id']],name_variant=0 if label=='old' else bank[r['task_id']].get('name_variant',0)),r['completion']) for r in rs]
   aa,_=group_advantages(corrected,rs,'standard_sequence');s['rescored_active']+=any(abs(a)>1e-8 for a in aa)
  else:corrected=[r['score'] for r in rs];aa=[r['task_advantage'] for r in rs]
  for r,c,a in zip(rs,corrected,aa):
   r['rescored']=c;r['recomputed_advantage']=a
   s['calls']+=1;s['tokens']+=len(r['response_ids']);s['trunc']+=r['completion']['finish_reason']=='length';s['correct']+=r['score'].get('correct') is True;s['rescored_correct']+=c.get('correct') is True;s['positive']+=r['task_advantage']>0;s['recomputed_positive']+=a>0
   s['adv_changed']+=abs(r['task_advantage']-a)>1e-6;s['incorrectly_penalized']+=r.get('protocol_failure')=='invalid_action' and c['status']=='ok'
   s['rescored_mismatch']+=r['score'].get('reward')!=c.get('reward')
   if not short:
    calls=r['completion'].get('raw_message',{}).get('tool_calls') or [];action=calls[0]['function']['name'] if len(calls)==1 else 'NO_TOOL';s['action/'+action]+=1
 for key,s in stats.items():s['mean_tokens']=s['tokens']/s['calls']
 out[label]={k:dict(s) for k,s in stats.items()};allrows[label]=rows
keys=lambda rs:{(r['step'],r['group'],r['replica'],r.get('decision',0)):r for r in rs}
a=keys(allrows['old']);b=keys(allrows['fixed']);pairs=[(v,b[k]) for k,v in a.items() if k in b]
out['paired']={'matched_calls':len(pairs),'same_task':sum(x['task_id']==y['task_id'] for x,y in pairs),'same_request_messages':sum(x['request']['messages']==y['request']['messages'] for x,y in pairs)}
# Compare unaffected display variant 0 only, by period and task; same exposure.
for label,rs in allrows.items():
 c=collections.defaultdict(collections.Counter)
 for r in rs:
  if r['training_mode']!='static' or bank[r['task_id']].get('name_variant',0)!=0:continue
  s=c[(r['kind'],'0-9' if r['step']<10 else '10-19')];s['n']+=1;s['correct']+=r['rescored'].get('correct') is True;s['trunc']+=r['completion']['finish_reason']=='length'
 out[label+'_variant0']={str(k):dict(v) for k,v in c.items()}
print(json.dumps(out,indent=2))
