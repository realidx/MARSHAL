import json, statistics, collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
r=ROOT/'examples/social_mixed/results/mixed-851174'
a=[json.loads(x) for x in (r/'metrics.jsonl').read_text().splitlines()]
result={'updates':len(a),'tokens':a[-1]['training_response_tokens'],'budget_fraction':a[-1]['training_response_tokens']/6553600,'training_groups':{},'validation':[]}
for k in ('B','P','selfplay'):
 result['training_groups'][k]={name:sum(x[k+'/'+name] for x in a) for name in ('groups','mixed_groups','utility_mixed_groups','outcome_incomplete_groups')}
for p in sorted((r/'validation').glob('*.json')):
 d=json.loads(p.read_text());v={'step':p.stem,'metrics':d['metrics'],'kinds':{}}
 for k in ('B','P','selfplay'):
  calls=[c for c in d['calls'] if c['kind']==k];actions=collections.Counter();expl=0
  for c in calls:
   m=c['completion'].get('raw_message',{});expl+=bool((m.get('content')or '').strip())
   actions.update(t['function']['name'] for t in m.get('tool_calls')or [])
  v['kinds'][k]={'n':len(calls),'mean_tokens':statistics.mean(len(c['response_ids']) for c in calls),'explanations':expl,'actions':dict(actions)}
 v['mean_player_utility']=statistics.mean(u for g in d['games'] for u in g['terminal_utility'])
 result['validation'].append(v)
result['initial_anomalies']={k:a[0][k] for k in ('actor/loss','actor/kl','actor/pg_loss','actor_train/grad_norm','behavior_actor_logprob_abs_mean','behavior_actor_logprob_abs_max','actor/first_update_changed_norm_tensors')}
print(json.dumps(result,indent=2))
