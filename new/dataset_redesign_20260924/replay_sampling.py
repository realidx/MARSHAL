"""Offline schedule replay: planned exposure is not observed learning."""
import json
from pathlib import Path
from collections import Counter
from copy import deepcopy
from training.social_mixed.reasoning_bank import load
from training.social_mixed.reasoning_training import ReasoningCollector
from training.social_mixed.coverage_sampling import plan,VERSION
from training.social_mixed.task_difficulty import describe
D=Path(__file__).resolve().parent
c=ReasoningCollector({'bp_train':load('train')},lambda _:[])
relations=Counter()
for step in range(148):
 c.state['block']=step
 for cid,v,slot in plan(c):
  relations[slot.split('-')[0]]+=1
c.state['block']=148
clone=ReasoningCollector({'bp_train':load('train')},lambda _:[])
clone.restore(deepcopy(c.state),arm='decomposed')
assert plan(clone)==plan(deepcopy(c))
summary={'version':VERSION,'updates':148,'groups_per_view':592,'relations_slots':dict(relations),'views':{}}
for v in ('O','B','Pplus'):
 ids=[cid for cid in c.schedule if v!='Pplus' or c.views[cid,v].get('p_train_eligible',True)]
 counts=[c.state['coverage'].get(v+':'+cid,{}).get('count',0) for cid in ids]
 assert max(counts)-min(counts)<=1
 summary['views'][v]={'eligible':len(ids),'unseen':counts.count(0),'once':counts.count(1),'twice':counts.count(2),'min':min(counts),'max':max(counts)}
(D/'sampling_replay_v3.json').write_text(json.dumps(summary,indent=2)+'\n')
rows=[dict(id=t['id'],split=t['split'],canonical_id=t['canonical_id'],**describe(t)) for t in load('train')+load('validation')]
(D/'structural_difficulty.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
print(json.dumps(summary,indent=2))
