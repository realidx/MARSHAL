"""Exploratory teacher-only discovery; run from repository root. Not a model eval."""
import sys,json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from pathlib import Path
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.preference_contract import belief
rs=[json.loads(l) for l in Path('examples/social_mixed/data_distribution_v1/bp_train.jsonl').read_text().splitlines()]
seen=set();found=[];attempts=[]
for r in rs:
 i=r['input'];g=i['game']
 if r['background_profile']!='balanced' or g['n_players']!=2 or max(g['n_actions_per_player'])>2:continue
 raw,own=reconstruct(i);raw['background_prior']=i['background_prior'];raw['game']['round_robin']=[1,0]
 key=json.dumps(raw,sort_keys=True)
 if key in seen:continue
 seen.add(key)
 try:e=PrivateEpisode(raw,[],seconds=15,max_nodes=10000,max_sweeps=64)
 except Exception as ex:print('FAIL',r['id'],str(ex),flush=True);attempts.append(dict(id=r['id'],error=str(ex)));continue
 reaches={0:e.weights};paths={0:[]};n=0
 for ix,en in enumerate(e.tree.entries):
  if ix not in reaches:continue
  reach=reaches[ix]
  if en.actor is None:continue
  weights=reach*np.array([w[0]==own for w in e.tree.worlds])
  if en.actor==0 and en.node.pending is None and en.node.state.turn_index==1 and weights.sum()>1e-12 and not any(a.get('action')=='INVESTIGATE' for a in paths[ix]):
   p=weights/weights.sum();q=e.tree.world_weights*np.array([w[0]==own for w in e.tree.worlds]);q/=q.sum();pay=np.array([e.tree.values[c] for c in en.children]);acts=[a.to_dict() for a in en.actions];vp=np.einsum('awp,w->ap',pay,p);vq=np.einsum('awp,w->ap',pay,q);ap=acceptable(vp,0,actions=acts);aq=acceptable(vq,0,actions=acts)
   if not set(ap)&set(aq):
    row=dict(source_id=r['id'],mode=r['completion_mode'],raw=raw,own=own,events=paths[ix],posterior=p.tolist(),prior=q.tolist(),actions=acts,accepted=ap,blind_accepted=aq,reach=float(weights.sum()),values=vp.tolist(),blind_values=vq.tolist());found.append(row);n+=1
  for j,c in enumerate(en.children):
   cr=reach*e.tree.policy[ix][j]
   if cr.sum()>1e-12:reaches[c]=cr;paths[c]=paths[ix]+[en.actions[j].to_dict()]
 print('DONE',r['id'],r['kernel'],r['completion_mode'],len(e.tree.entries),'found',n,flush=True)
 attempts.append(dict(id=r['id'],found=n,nodes=len(e.tree.entries)))
Path('new/bp_composition_diagnostic_v1/discovery.json').write_text(json.dumps(dict(attempts=attempts,candidates=found),indent=2))
print('TOTAL',len(found))
