import json,collections,math,hashlib,statistics
from pathlib import Path
from training.b_sft.social_b_rl import reward
from training.b_sft.social_b_evaluation import score_attempt
root=Path('new/local_data/social_runs/b_grpo_vllm_r1')
tasks={t['id']:t for t in map(json.loads,Path('new/local_data/social_runs/b_curriculum_eval_v1/tasks.jsonl').read_text().splitlines())}
rows=[];errors=[];detail_differences=[]
for p in sorted((root/'native_reward_calls').glob('*.jsonl')):
 last=-1
 for num,line in enumerate(p.read_text().splitlines(),1):
  r=json.loads(line);step=r['global_step']
  if step is not None:last=step
  r['_phase']='train' if step is not None else ('val0' if last<0 else 'val5')
  r['_file']=p.name;r['_line']=num
  t=tasks[r['checkpoint']]
  if reward(t,r['completion'])!=r['reward']:errors.append(['reward',p.name,num])
  recomputed=score_attempt(t,r['completion'])
  if {k:v for k,v in recomputed.items() if k!='detail'}!={k:v for k,v in r['score'].items() if k!='detail'}:errors.append(['score',p.name,num])
  elif recomputed!=r['score']:detail_differences.append([p.name,num])
  if len(r['token_ids'])>1024:errors.append(['budget',p.name,num])
  if t['split']!=('train' if step is not None else 'validation'):errors.append(['split',p.name,num])
  rows.append(r)
def stats(rs):
 cats=collections.defaultdict(lambda:[0,0])
 for r in rs:
  judgments={(j['player'],j['goal']):j for j in r['score'].get('judgments',[])}
  for q in r['category_queries']:
   query=q['query'];key=(query['player'],query['goal']);j=judgments.get(key,{})
   cats[q['category']][0]+=int(j.get('set_exact',False) and j.get('favored_exact',False));cats[q['category']][1]+=1
 return dict(n=len(rs),statuses=dict(collections.Counter(r['reward']['status'] for r in rs)),exact=sum(r['score'].get('exact') is True for r in rs),reward_mean=statistics.mean(r['reward']['reward'] for r in rs),query_exact=sum(j.get('set_exact',False) and j.get('favored_exact',False) for r in rs for j in r['score'].get('judgments',[])),queries=sum(r['score']['query_count'] for r in rs),categories=dict(cats),max_tokens=max(map(lambda r:len(r['token_ids']),rs)))
summary={phase:stats([r for r in rows if r['_phase']==phase]) for phase in ['train','val0','val5']}
groups=collections.defaultdict(list)
for r in rows:
 if r['_phase']=='train':groups[(r['global_step'],r['checkpoint'])].append(r)
summary['groups']=dict(n=len(groups),sizes=dict(collections.Counter(len(v) for v in groups.values())),varying=sum(len({r['reward']['reward'] for r in v})>1 for v in groups.values()),valid_varying=sum(len({r['reward']['reward'] for r in v if r['reward']['status']=='ok'})>1 for v in groups.values()),all_zero=sum(all(r['reward']['reward']==0 for r in v) for v in groups.values()))
history=json.loads((root/'checkpoints/checkpoint-9/pipeline/worker_state_pipeline.json').read_text())['log_history']
keys=['actor/lr','actor/pg_loss','actor/kl_loss','actor_train/grad_norm','actor/optimizer_steps_per_rollout','critic/score/mean','val_correct/all/mean']
summary['steps']=[{k:m[k] for k in keys if k in m} for m in history]
summary['group_metric_check']=[]
for i,m in enumerate(history):
 rs=[r for r in rows if r['global_step']==i]
 if len(rs)!=32 or abs(statistics.mean(r['reward']['reward'] for r in rs)-m['critic/score/mean'])>1e-6:errors.append(['step_rewards',i])
 gs=[v for (step,_),v in groups.items() if step==i]
 varying=sum(len({r['reward']['reward'] for r in v})>1 for v in gs)/len(gs)
 # ROLL's metric counts constant 0.5 groups as mixed, despite zero reward variance.
 mixed=sum(not all(r['reward']['reward']==0 for r in v) and not all(r['reward']['reward']==1 for r in v) for v in gs)/len(gs)
 logged=m['group/mixed_groups_ratio']
 summary['group_metric_check'].append(dict(step=i,reward_varying_ratio=varying,roll_mixed_ratio=mixed,logged=logged))
 if abs(mixed-logged)>1e-6:errors.append(['group_metric',i])
summary['times_seconds']={k:sum(m.get(k,0) for m in history) for k in ['time/step_generate','time/step_train','time/step_model_update','time/ref_log_probs_values','time/old_log_probs','time/val_step','time/actor_train/do_checkpoint/total']}
manifest=json.loads((root/'run_manifest.json').read_text());summary['source_hash_differences']=[f for f,h in manifest['source_hashes'].items() if Path(f).exists() and hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h]
summary['errors']=errors
summary['diagnostic_text_differences']=detail_differences
(root/'audit.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='steps'},indent=2))
(root/'audited_calls.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
