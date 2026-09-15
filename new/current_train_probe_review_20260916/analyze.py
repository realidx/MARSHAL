import json,collections,statistics
from pathlib import Path
p=Path('/Users/bruce/MARSHAL/runs/current_train_probe_download/current_train_probe_20260915-144136/run/evaluation');out=Path('/Users/bruce/MARSHAL/new/current_train_probe_review_20260916')
read=lambda p:[json.loads(x) for x in p.read_text().splitlines()]
bp=read(p/'bp/bp.jsonl');games=read(p/'sp/games.jsonl');groups=collections.defaultdict(list)
for r in bp:groups[r['task']['id']].append(r)
def stats(rs):
 gs=collections.defaultdict(list)
 for r in rs:gs[r['task']['id']].append(r)
 return dict(n=len(rs),correct=sum(r['score']['reward'] for r in rs),statuses=dict(collections.Counter(r['score']['status'] for r in rs)),mixed=sum(0<sum(r['score']['reward'] for r in g)<len(g) for g in gs.values()),all_wrong=sum(not any(r['score']['reward'] for r in g) for g in gs.values()),all_correct=sum(all(r['score']['reward'] for r in g) for g in gs.values()),fullset=sum(r['score'].get('predicted_full_set',False) for r in rs),wrong_fullset=sum(r['score'].get('predicted_full_set',False) and not r['score']['correct'] for r in rs))
summary={k:stats([r for r in bp if r['task']['probe_kernel']==k]) for k in ['B1','B2','B3','P1','P2','P3','P4']}
summary.update({k:stats([r for r in bp if r['task']['task']==k]) for k in ['B','P']})
summary['completion']={k:stats([r for r in bp if r['task']['probe_completion']==k]) for k in ['binary','linear','mixed']}
print(json.dumps(summary,indent=2))
tasks=[]
for id,rs in groups.items():
 t=rs[0]['task'];tasks.append(dict(id=id,kernel=t['probe_kernel'],mode=t['probe_completion'],case=t.get('p123_case',t.get('p4_case',t.get('b3_case',t.get('b_lesson','')))),**stats(rs)))
(out/'task_summary.json').write_text(json.dumps(tasks,indent=2))
calls=[c for g in games for c in g['calls']];s=json.loads((p/'sp/summary.json').read_text());sg=s['seat_groups'];sp=dict(calls=len(calls),attempts=dict(collections.Counter(c['attempt'] for c in calls)),valid=len([c for c in calls if c['valid']]),first_truncated=sum(c['attempt']==0 and c['completion']['finish_reason']=='length' for c in calls),retry_truncated=sum(c['attempt']==1 and c['completion']['finish_reason']=='length' for c in calls),explanations=sum(bool((c['completion']['raw_message'].get('content') or '').strip()) for c in calls),valid_explanations=sum(c['valid'] and bool((c['completion']['raw_message'].get('content') or '').strip()) for c in calls),utility_mixed=sum(not g['zero_outcome_advantage'] for g in sg),seat_groups=len(sg),protocol_only=sum(g['zero_outcome_advantage'] and max(g['protocol_costs'])>min(g['protocol_costs']) for g in sg),actions=dict(collections.Counter(c['action'].get('action',c['action'].get('response')) for c in calls if c['valid'])))
print('SELFPLAY',json.dumps(sp))
print('UTILITIES')
for reset in sorted(set(g['reset_id'] for g in sg)):
 print(reset,[(g['seat'],g['utilities']) for g in sg if g['reset_id']==reset])
for label,rs in [('bp correct',[r['response'] for r in bp if r['score']['correct']]),('bp wrong completed',[r['response'] for r in bp if not r['score']['correct'] and r['score']['status']=='ok']),('sp valid',[c for c in calls if c['valid']])]:
 v=[r['usage']['completion_tokens'] for r in rs];print(label,'tokens median',statistics.median(v),'mean',round(statistics.mean(v),1),'max',max(v))
(out/'summary.json').write_text(json.dumps(dict(bp=summary,sp=sp),indent=2))
# Compact human-review set: one success and one completed error per kernel plus loop examples.
with (out/'trace_review.txt').open('w') as f:
 for k in ['B1','B2','B3','P1','P2','P3','P4']:
  for status in ['correct','wrong','truncated']:
   rs=[r for r in bp if r['task']['probe_kernel']==k and (r['score']['correct'] if status=='correct' else r['score']['status']=='truncated' if status=='truncated' else r['score']['status']=='ok' and not r['score']['correct'])]
   if not rs:continue
   r=rs[0];f.write('\n### '+k+' '+status+' '+r['task']['id']+' replica '+str(r['replica'])+'\n'+json.dumps(r['task']['teacher'])+'\n'+r['response']['request']['messages'][-1]['content']+'\nRESPONSE\n'+json.dumps(r['response']['completion']['raw_message'],ensure_ascii=False)+'\n')
