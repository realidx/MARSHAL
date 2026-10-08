import json,hashlib
from pathlib import Path
from training.strategic_slices.terminal_training import TrainingData
from training.strategic_slices.terminal_training_evaluate import Validator
from training.strategic_slices.common import stable
repo=Path.cwd();out=repo/'new/terminal_hf_test_calbench_20261008/audit';out.mkdir(exist_ok=True)
data=TrainingData(repo/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',repo/'new/local_data/strategic_slices_terminal_selected_v4')
results={}
for label,job in [('best',919181),('latest',919182)]:
 root=Path('/home/e/e1300530/tmp')/f'terminal-test-{label}-{job}'
 report=json.loads((root/'report.json').read_text());calls=report['slice_calls']+report['full_games']['calls'];lookup={stable(c['request']):c for c in calls};assert len(lookup)==len(calls)
 used=[]
 fields=('prompt_ids','response_ids','behavior_log_probs','text','finish_reason','completion','request','usage','elapsed_seconds')
 def replay(requests):
  result=[]
  for req in requests:
   key=stable(req);assert key in lookup,'Original Validator made a different request';used.append(key)
   result.append({k:lookup[key][k] for k in fields})
  return result
 cfg=dict(seed=42,workers=64,max_tokens=1024,context=16384,temperature=0.,top_p=1.,top_k=-1,repetition_penalty=1.)
 rebuilt=Validator(data,replay,cfg,repeats=8,split='test').run()
 checks={k:rebuilt[k]==report[k] for k in ['slices','slice_games','slice_calls','generated_response_tokens']}
 checks.update({'full_'+k:rebuilt['full_games'][k]==report['full_games'][k] for k in ['metrics','games','calls']})
 assert set(used)==set(lookup) and len(used)==len(calls)
 results[label]=dict(checks=checks,requests_replayed=len(used),all_requests_exact_match=True)
 (out/'replay.json').write_text(json.dumps(results,indent=2)+'\n')
 print(label,json.dumps(results[label]),flush=True)
 if not all(checks.values()):
  differences=[]
  for i,(left,right) in enumerate(zip(rebuilt['slice_calls'],report['slice_calls'])):
   if left!=right:
    differences.append(dict(index=i,keys_left_only=sorted(set(left)-set(right)),keys_right_only=sorted(set(right)-set(left)),changed={k:dict(replay=left[k],original=right[k]) for k in set(left)&set(right) if left[k]!=right[k]}))
  (out/(label+'-call-differences.json')).write_text(json.dumps(differences,indent=2)+'\n')
  print('call differences',len(differences),differences[:1],flush=True)
 assert checks['slices'] and checks['slice_games'] and checks['full_metrics'] and checks['full_games']
