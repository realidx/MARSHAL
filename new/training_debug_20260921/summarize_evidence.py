import json,gzip,hashlib
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'new/training_chain_evidence_20260921'
out={}
for arm in ('old_bp','new_bp','new_sp'):
 report={};out[arm]=report
 for p in sorted((E/arm/'metrics').glob('*.jsonl')):
  if 'phases' in p.name:continue
  rows=[x for x in map(json.loads,p.read_text().splitlines()) if 'generated_tokens' in x]
  keys=['generated_tokens','candidate_groups','B/effective_groups','P/effective_groups','B/utility_mixed_groups','P/utility_mixed_groups','actor/applied_lr','B/stage/likelihood/effective_groups','B/stage/procedure/effective_groups','B/stage/raw/effective_groups']
  report[p.stem]={ 'updates':len(rows),'first_step':rows[0]['system/step'],'last_step':rows[-1]['system/step'],'metrics':{k:dict(first=v[0],last=v[-1],mean=sum(v)/len(v),min=min(v),max=max(v)) for k in keys if (v:=[r[k] for r in rows if k in r])}}
 groups=Counter();stages=Counter();sizes=Counter();adv_errors=0
 for p in sorted((E/arm/'calls').glob('*.gz')):
  rs=list(map(json.loads,gzip.open(p,'rt')));gs=defaultdict(list)
  for r in rs:gs[r['group']].append(r)
  for g in gs.values():
   groups[g[0].get('kernel',g[0]['kind'])]+=1;stages[g[0].get('b_bridge_stage','not_recorded')]+=1;sizes[len(g)]+=1
 report['sampled_call_windows']={'groups_by_kernel':dict(groups),'groups_by_stage':dict(stages),'group_sizes':dict(sizes),'not_full_training':True}
(ROOT/'new/training_debug_20260921/evidence_summary.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
