import json
from pathlib import Path
import numpy as np
from training.strategic_slices.terminal_training import TrainingData
from training.strategic_slices.values import extreme_value
repo=Path.cwd();data=TrainingData(repo/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',repo/'new/local_data/strategic_slices_terminal_selected_v4');results=[];checked={}
for row in sorted(data.test,key=lambda r:(r['parent_id'],r['id'])):
 tree,_=data.reference(row)
 for i,m in enumerate(row['members']):
  key=(row['reference_id'],row['ego'],m['root_index'],row['k'],tuple(m['world_weights']))
  if key not in checked:checked[key]=extreme_value(tree,row['ego'],m['root_index'],m['world_weights'],row['k'])['root_Q']
  q=np.asarray(checked[key]);old=np.asarray(m['root_Q']);delta=float(np.max(np.abs(q-old)))
  results.append(dict(slice_id=row['id'],member=i,delta=delta,flat=bool(q.max()-q.min()<=1e-7)))
 if len(results)%25==0:print('members checked',len(results),flush=True)
out=repo/'new/terminal_hf_test_calbench_20261008/audit';out.mkdir(exist_ok=True)
report=dict(members=len(results),unique_recomputations=len(checked),max_delta=max(r['delta'] for r in results),mismatches=[r for r in results if r['delta']>1e-7],rows=results)
(out/'root_q.json').write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='rows'},flush=True)
