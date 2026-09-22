import json,statistics,hashlib
from pathlib import Path
BASE=Path('/tmp/osc-evidence');OUT=Path(__file__).resolve().parent
CHAINS={'O':[('outcome','871236',0,7),('outcome','871285',8,29),('outcome','871623',30,99)],'SP':[('selfplay','871236',0,7),('selfplay','871285',8,29)],'C':[('conditioned','871298',0,43),('conditioned','871607',44,89)]}
def read(p):return json.loads(p.read_text())
def mean(rs,k):
 v=[r[k] for r in rs if isinstance(r.get(k),(float,int))];return sum(v)/len(v) if v else None
results={}
for arm,segs in CHAINS.items():
 metrics=[];val={};static={};identities=[]
 for name,job,lo,hi in segs:
  root=BASE/'training'/name/f'{name}-seed42-{job}'
  ex=read(root/'experiment.json');identities.append(ex)
  metrics.extend(r for r in map(json.loads,(root/'metrics.jsonl').read_text().splitlines()) if lo<=r.get('system/step',-1)<=hi and 'generated_tokens'in r)
  for folder,target in [('validation',val),('static_o_monitor',static)]:
   for p in (root/folder).glob('step-*.json'):
    if 'FAILED' in p.name:continue
    d=read(p);step=d['completed_updates']
    if (lo==0 and step==0) or lo<step<=hi+1:target[step]=d
 assert len({r['system/step'] for r in metrics})==len(metrics)
 assert sum(r['generated_tokens'] for r in metrics)==metrics[-1]['training_response_tokens']
 windows=[]
 for start in range(0,len(metrics),10):
  rs=metrics[start:start+10];w=dict(first=rs[0]['system/step'],last=rs[-1]['system/step'],tokens=rs[-1]['training_response_tokens'])
  for k in ['generated_tokens','actor_train/grad_norm','actor/kl_weighted','actor/clip_fraction','behavior_preupdate_clip_fraction','actor/applied_lr','O/task_coefficient_mass','Pplus/task_coefficient_mass','token_overshoot']:
   w[k]=mean(rs,k)
  for view in ['O','Pplus']:
   samples=sum(r.get(view+'/candidate_groups',0)*8 for r in rs)
   if samples:
    w[view+'/valid']=sum(r[view+'/valid'] for r in rs)/samples
    w[view+'/correct_of_valid']=sum(r[view+'/correct'] for r in rs)/sum(r[view+'/valid'] for r in rs)
    w[view+'/contrast_rate']=sum(r[view+'/semantic_contrast_groups'] for r in rs)/sum(r[view+'/candidate_groups'] for r in rs)
    w[view+'/masked']=sum(r[view+'/semantic_masked'] for r in rs)/samples
  windows.append(w)
 trajectory=[]
 for step,d in sorted(val.items()):
  m=d['metrics'];r=dict(updates=step,tokens=d['training_response_tokens'])
  for k in ['reasoning/O/accuracy','reasoning/O/action_relevant/accuracy','reasoning/O/control/accuracy','reasoning/B/accuracy','reasoning/Pplus/conditional_accuracy','reasoning/Pplus/scored_coverage','games/current_team/all/cohort_player_utility_lower','reasoning/O/conditional_mean_regret']:
   r[k]=m.get(k)
  trajectory.append(r)
 retention=[];prev=None
 for step,d in sorted(static.items()):
  calls={r['task']['id']:r for r in d['calls']};curr={k:r['score']['correct'] for k,r in calls.items()}
  row=dict(updates=step,correct=sum(v is True for v in curr.values()))
  if prev:
   lost=[k for k in curr if prev[k] and not curr[k]];gain=[k for k in curr if not prev[k] and curr[k]]
   row.update(lost=lost,gained=gain)
  retention.append(row);prev=curr
 results[arm]=dict(updates=len(metrics),tokens=metrics[-1]['training_response_tokens'],windows=windows,validation=trajectory,static=retention,
   max_gradient=max(r['actor_train/grad_norm'] for r in metrics),max_clip=max(r['actor/clip_fraction'] for r in metrics),
   min_optimizer_steps=min(r['actor/optimizer_steps_per_rollout'] for r in metrics),max_optimizer_steps=max(r['actor/optimizer_steps_per_rollout'] for r in metrics))
(OUT/'training_summary.json').write_text(json.dumps(results,indent=2)+'\n')
for arm,r in results.items():
 print(arm,'updates,tokens,maxgrad,maxclip',r['updates'],r['tokens'],r['max_gradient'],r['max_clip'])
 print('WINDOWS',json.dumps(r['windows']))
 print('VALIDATION',json.dumps(r['validation']))
