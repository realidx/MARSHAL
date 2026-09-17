"""Native discussion fixture; run with PYTHONPATH=. python this_file.py.
No LM calls, optimizer, production protocol changes, or setup evidence.
"""
import json
from pathlib import Path
from copy import deepcopy
from training.b_sft.shared_teacher import native,SharedWindow
from benac_p.endgame_diagnose import decode_action
reqs=[[(0,0),(1,0)],[(1,1),(2,0)],[(0,0),(1,1),(2,0)],[(1,0),(2,0)],[(1,0),(1,1),(2,0)]]
raw=dict(id='forward-refusal',ego=0,own_preferences=[1,0,1,0,0],type_catalogues={'0':[[1,0,1,0,0]],'1':[[1,1,x,0,0] for x in (1,0,-1)],'2':[[0,1,0,-1,-1]]},history=[],game=dict(n_players=3,n_actions_per_player=[1,2,1],goals=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=p,action_id=a) for p,a in req]) for i,req in enumerate(reqs)],round_robin=[0,2,1],max_changes=1,menu_enabled=False))
prefix=[dict(action='OFFER',partner_id=1,proposer_action=[1],partner_action=[0,0]),dict(response='ACCEPT'),dict(action='OFFER',partner_id=1,proposer_action=[0],partner_action=[1,0])]
r,w,_=native(raw);n=r.initial()
for a in prefix:n=r._apply(n,decode_action(a))
t=SharedWindow(r,n,w,turns=2,max_nodes=10000,seconds=10).solve()

# Independently check every leaf payoff from ALL_OF requirements.
leaf_checks=0
for entry in t.entries:
 if entry.actor is not None:
  continue
 assert entry.node.state.is_terminal
 commitments=entry.node.state.snapshot_commitments()
 satisfied=[all(commitments[p][a] for p,a in req) for req in reqs]
 for wi,world in enumerate(w):
  direct=[sum(v*int(flag) for v,flag in zip(row,satisfied)) for row in world]
  assert direct==entry.payoff[wi].tolist()
  leaf_checks+=1

results=[]
for wi,world in enumerate(w):
 label=t.labels(0,tuple(range(len(w))),1,world[1])
 branches=[]
 for ai,a in enumerate(t.entries[0].actions):
  i=t.entries[0].children[ai]
  history=deepcopy(prefix)+[a.to_dict()]
  while t.entries[i].actor is not None:
   actor=t.entries[i].actor
   act=t.action(i,world[actor]);history.append(act.to_dict())
   i=t.entries[i].children[t.entries[i].actions.index(act)]
  replay=r.initial()
  for action in history:
   replay=r._apply(replay,decode_action(action))
  assert replay.state.is_terminal
  assert replay.state.snapshot_commitments()==t.entries[i].node.state.snapshot_commitments()
  branches.append(dict(root_action=a.to_dict(),history=history,
                       commitments=replay.state.snapshot_commitments(),
                       utilities=t.values[i][wi].tolist()))
 results.append(dict(target_preference=world[1][2],world=world,root_values=label,branches=branches))
assert [[a['own'] for a in x['root_values']['actions']] for x in results]==[[2.,1.],[1.,1.],[1.,1.]]
assert results[0]['root_values']['social_optimal_actions']==[{'response':'REJECT'}]
assert results[1]['root_values']['social_optimal_actions']==[{'response':'REJECT'}]
assert len(results[2]['root_values']['social_optimal_actions'])==2

# Explicitly check the later clean offer on both root branches.
clean_checks=[]
for response in ('REJECT','ACCEPT'):
 node=r._apply(n,decode_action({'response':response}))
 row=[int(response=='ACCEPT'),1]
 offer=dict(action='OFFER',partner_id=2,proposer_action=row,partner_action=[1])
 node=r._apply(node,decode_action(offer))
 values={}
 for answer in ('REJECT','ACCEPT'):
  leaf=r._apply(node,decode_action({'response':answer}))
  c=leaf.state.snapshot_commitments()
  flags=[all(c[p][a] for p,a in req) for req in reqs]
  values[answer]=sum(v*int(flag) for v,flag in zip(w[0][2],flags))
 assert values=={'REJECT':0,'ACCEPT':1 if response=='REJECT' else -1}
 clean_checks.append(dict(first_response=response,offer=offer,player_2_values=values))

# Deadline control: same commitments and pending offer, no later proposal.
late=deepcopy(raw);late['game']['round_robin']=[0,1,2]
late_prefix=deepcopy(prefix[:2])+[dict(action='PASS')]+deepcopy(prefix[2:])
lr,lw,_=native(late);ln=lr.initial()
for action in late_prefix:
 ln=lr._apply(ln,decode_action(action))
lt=SharedWindow(lr,ln,lw,turns=1,max_nodes=10000,seconds=10).solve()
late_labels=[lt.labels(0,tuple(range(len(lw))),1,world[1]) for world in lw]
assert all(x['social_optimal_actions']==[{'response':'ACCEPT'}] for x in late_labels)

out=dict(fixture=raw,setup_prefix=prefix,results=results,
         clean_offer_checks=clean_checks,certificate=t.certificate,
         verification=dict(native_branch_replays=6,leaf_world_payoff_checks=leaf_checks),
         deadline_control=dict(fixture=late,setup_prefix=late_prefix,labels=late_labels),
         compatible_types_after_root_reject=[1,0,-1],
         limitations=[
          'Constructed native setup, independent of private types; not an autonomous opening.',
          'Short two-proposal-turn suffix reaches terminal; no generic cutoff evaluator validated.',
          'All residual ties remain admissible for root B; selected native-order winner is only a representative trace.',
          'Old shared solver verifies a selected finite-window pure-policy fixed point, not every equilibrium.',
          'No automatic B corpus labels or LM training.'])
path=Path('new/local_data/social_runs/forward_refusal_discussion_v1.json')
path.parent.mkdir(parents=True,exist_ok=True)
if path.exists():
 assert json.loads(path.read_text())==json.loads(json.dumps(out)), 'Existing artifact differs; use a new version'
else:
 path.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(dict(output=str(path),nodes=len(t.entries),verification=out['verification'],
                     root_values=[[a['own'] for a in x['root_values']['actions']] for x in results],
                     deadline_all_accept=True)))
