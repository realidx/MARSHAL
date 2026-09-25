import json,collections
from pathlib import Path
r=Path('new/d24_partner32_evidence_20260926');tr=r/'training/decomposed-seed42-881010'
bank=Path('examples/social_mixed/micro24_v1_partner_choice_v1/tasks.jsonl'); newids={json.loads(s)['id'] for s in bank.read_text().splitlines()}
data=collections.defaultdict(list);per=collections.defaultdict(list)
for p in sorted((tr/'calls').glob('step-*.jsonl'),key=lambda p:int(p.stem.split('-')[1])):
 step=int(p.stem.split('-')[1])
 for s in p.open():
  c=json.loads(s);tag=('new_' if c['task_id'] in newids else 'old_')+c['kind'];small=dict(step=step,correct=bool(c['score'].get('correct')),trunc=c['finish_reason']=='length',adv=c['task_advantage'],length=len(c['response_ids']),group=c['group'])
  data[(tag,step//10)].append(small);per[c['task_id']].append(small)
for (tag,b),rows in sorted(data.items()):print(tag,b,'n',len(rows),'correct',sum(x['correct'] for x in rows),'trunc',sum(x['trunc'] for x in rows),'len',round(sum(x['length'] for x in rows)/len(rows)),'signal',len({x['group'] for x in rows if abs(x['adv'])>1e-8}))
print('exposure',collections.Counter(len({x['step'] for x in v}) for v in per.values()))
for tid in sorted(newids):
 rows=per[tid];print(tid,[sum(x['correct'] for x in rows if x['step']//10==b) for b in range(4)])
(r/'audit').mkdir(exist_ok=True);(r/'audit/training.json').write_text(json.dumps({tid:rows for tid,rows in per.items()},indent=2))
