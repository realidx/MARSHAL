"""Freeze size extensions using structural criteria only; no model outcomes."""
import argparse,json,hashlib
from pathlib import Path
from dataclasses import asdict
import numpy as np
from training.social_mixed.core import seed_for
from training.social_mixed.structure_coverage import geometry_id
from training.social_mixed.frozen.benac_p.generator import GeneratorConfig,generate_game
from examples.final_evaluation.team_benac import digest,ROOT
SEED=2026092601

def build(players,folder):
 if players not in (2,4):raise ValueError('Keep the existing three-player suite')
 rows=[]
 for binary in (True,False):
  for rounds in (2,4):
   for profile,weights in [('balanced',dict(want=1,neutral=1,avoid=1)),('avoid_heavy',dict(want=1,neutral=1,avoid=2))]:
    for instance in range(2):
     ident=f'team-{players}p-{"binary" if binary else "linear"}-{rounds}r-{profile}-{instance}'
     cfg=GeneratorConfig(n_players=players,actions_per_player=2,n_goals=3,n_rounds=rounds,goal_arities=(2,) if players==2 else (2,3),linear_goal_fraction=0 if binary else 1)
     seed=seed_for(SEED,ident,'geometry');g=generate_game(seed,cfg).to_dict()
     for k in ('private_preferences','seed','metadata'):g.pop(k,None)
     owners={a['player_id'] for goal in g['goals'] for a in goal['required_actions']}
     if owners!=set(range(players)):raise ValueError('Unused player')
     rng=np.random.default_rng(seed_for(SEED,ident,'world'));probs=np.array(list(weights.values()),dtype=float);probs/=probs.sum()
     for attempt in range(10000):
      world=rng.choice([1,0,-1],size=(players,3),p=probs)
      if (world==1).any(axis=1).all() and (world!=0).any(axis=0).all():break
     else:raise ValueError('Prior rejection budget exhausted')
     rows.append(dict(id=ident,players=players,rounds=rounds,split='test',evaluation_split='overlap_not_audited',structure_family=geometry_id(g),background_profile=profile,raw=dict(game=g,history=[],preference_generation=dict(version='public-prior-margin-v1',values=[-1,0,1],background_prior=dict(version='public-prior-margin-v1',name=profile,weights=weights))),realized_world=world.tolist(),prompt_clarification='required-commitments-v1',geometry_generation=dict(seed=seed,config=asdict(cfg)),preference_redraw=dict(seed=seed_for(SEED,ident,'world'),rejections=attempt)))
 # Audit against the same bank inventory as the original team suite; no outcome filtering.
 audit=json.loads((Path(__file__).with_name('team_benac_v1')/'overlap_audit.json').read_text())
 families=set();sources={}
 for name in audit['source_hashes']:
  p=ROOT/name
  if not p.exists():raise FileNotFoundError(p)
  sources[name]=digest(p)
  for line in p.read_text().splitlines():
   row=json.loads(line);t=row['task'] if isinstance(row.get('task'),dict) else row
   g=t.get('input',t.get('raw',{})).get('game')
   if g:families.add(geometry_id(g))
 for row in rows:row['evaluation_split']='seen_in_audited_banks' if row['structure_family'] in families else 'unseen_in_audited_banks'
 folder.mkdir(parents=True,exist_ok=False)
 (folder/'resets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
 (folder/'overlap_audit.json').write_text(json.dumps(dict(source_hashes=sources,scope='Same historical bank inventory as team v1; not per-model training membership'),indent=2))
 m=dict(version='team-benac-size-v1',players=players,games=16,repeats=1,temperature=0,max_tokens=1024,retries=1,seed=SEED,selection='Native connected geometry and valid public-prior worlds; no model, utility or solver outcome filtering',files={n:digest(folder/n) for n in ('resets.jsonl','overlap_audit.json')})
 (folder/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');return m
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--players',type=int,choices=[2,4],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.players,a.output)))
