"""Recompute paired test differences from extracted original reports."""
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np
cli=argparse.ArgumentParser();cli.add_argument('best',type=Path);cli.add_argument('latest',type=Path);cli.add_argument('--output',type=Path,required=True);args=cli.parse_args()
a=json.loads(args.best.read_text());b=json.loads(args.latest.read_text())
def success(r):return r['status']=='terminal' and all(r['step_rewards'])
assert len(a['slice_games'])==len(b['slice_games'])
pool=Path(__file__).resolve().parents[2]/'local_data/strategic_slices_oracle_consistent_candidates_v4/candidates.jsonl'
metadata={r['id']:r for r in map(json.loads,pool.read_text().splitlines())} if pool.exists() else {}
counts=defaultdict(int);by_parent=defaultdict(list);by_k=defaultdict(lambda:dict(n=0,best_success=0,latest_success=0))
for x,y in zip(a['slice_games'],b['slice_games']):
 for key in ['slice_id','replica','seed','member_index','world_index']:assert x[key]==y[key],key
 sx,sy=success(x),success(y);counts[str((sx,sy))]+=1
 by_parent[x['parent_id']].append(int(sx)-int(sy))
 k=x.get('k',metadata.get(x['slice_id'],{}).get('k'))
 if k is not None:
  row=by_k[k];row['n']+=1;row['best_success']+=sx;row['latest_success']+=sy
values=[np.asarray(v) for _,v in sorted(by_parent.items())];rng=np.random.default_rng(42)
bootstrap=[]
for _ in range(10000):
 selected=rng.integers(len(values),size=len(values));bootstrap.append(np.concatenate([values[i] for i in selected]).mean())
result=dict(paired_outcomes=dict(counts),parent_clusters=len(values),best_minus_latest=float(np.concatenate(values).mean()),parent_bootstrap_95_ci=np.quantile(bootstrap,[.025,.975]).tolist(),bootstrap_seed=42,bootstrap_draws=10000,per_k=dict(by_k),scores=dict(best=a['slices'],latest=b['slices']))
args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
