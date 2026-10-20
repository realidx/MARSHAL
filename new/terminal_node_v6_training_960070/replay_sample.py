import json,tarfile,time
from pathlib import Path
from training.strategic_slices.terminal_training import TrainingData
from training.strategic_slices.terminal_analysis import audit_game
root=Path('new/terminal_node_v6_training_960070')
data=TrainingData('new/local_data/strategic_slices_oracle_consistent_candidates_v4','new/local_data/strategic_slices_terminal_selected_v4')
by_id={r['id']:r for r in data.train};calls={};games=[]
with tarfile.open(root/'raw/training-960070.tar.gz.part000','r|gz') as tar:
 for member in tar:
  if member.name in ('run/calls/step-0.jsonl','run/calls/step-306.jsonl'):
   for line in tar.extractfile(member):
    c=json.loads(line)
    if c['selected_for_continuation']:calls[(c['group'],c['replica'])]=c
  if member.name in ('run/games/step-0.jsonl','run/games/step-306.jsonl'):
   games.extend(json.loads(line) for line in tar.extractfile(member))
chosen={}
for game in games:
 row=by_id[game['slice_id']];n=data.parents[row['parent_id']]['players'];key=(n,row['k'])
 if key not in chosen or (game['controlled_decisions'],game['cursor'])>(chosen[key]['controlled_decisions'],chosen[key]['cursor']):chosen[key]=game
results=[]
for (n,k),game in sorted(chosen.items()):
 row=by_id[game['slice_id']];game=dict(game,calls=[calls[(x['group'],x['replica'])] for x in game['selected_nodes']]);t=time.perf_counter();tree,_=data.reference(row)
 report=audit_game(tree,row,game,dict(seed=42,replicas=8,max_tokens=1024,context=16384,temperature=1.,top_p=1.,top_k=-1,repetition_penalty=1.),{})
 results.append(dict(players=n,k=k,cursor=game['cursor'],seconds=time.perf_counter()-t,report=report))
 print(n,k,'PASS',len(report['decisions']),'decisions',flush=True)
(root/'review_20261017/independent_replay.json').write_text(json.dumps(results,indent=2)+'\n')
