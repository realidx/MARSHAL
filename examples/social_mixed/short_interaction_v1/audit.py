"""Offline qualification; no model calls or changes to active training banks."""
import json,random,hashlib
from pathlib import Path
from training.social_mixed.short_interaction import ShortInteraction, decision_request, decode_action
ROOT=Path(__file__).resolve().parents[3]
def main():
 source=ROOT/'examples/social_mixed/compact_bank_200/tasks.jsonl';out=Path(__file__).parent;rows=[]
 for task in map(json.loads,source.read_text().splitlines()):
  if task['paired_view']!='O':continue
  row=dict(id=task['id'],canonical_id=task['canonical_id'],split=task['split'])
  if task['input']['game']['n_players']!=2:row.update(status='excluded',reason='not_two_player')
  elif task['operation_curriculum']['remaining']<2:row.update(status='excluded',reason='insufficient_horizon')
  else:
   try:
    env=ShortInteraction(task,seconds=3,max_nodes=30000,max_sweeps=128)
    trajectories=[]
    for seed in range(8):
     rng=random.Random(seed)
     def agent(inp):
      req=decision_request(inp)
      tool=rng.choice(req['tools'])['function'];args=rng.choice(tool['parameters']['enum'])
      return decode_action(inp,dict(raw_message=dict(tool_calls=[dict(function=dict(name=tool['name'],arguments=json.dumps(args)))])))
     trajectories.append(env.rollout(agent,seed))
    row.update(status='qualified',max_ego_decisions=env.max_decisions,policy_sha256=env.tree.certificate['policy_sha256'],
      random_native_rewards=[r['terminal_utility'] for r in trajectories],decision_counts=[r['ego_decisions'] for r in trajectories])
   except Exception as exc:row.update(status='excluded',reason=type(exc).__name__+': '+str(exc))
  rows.append(row)
 (out/'qualification.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
   note='Random native actions test plumbing, not Q0 learnability. Search failures are not invalid labels.',parents=rows),indent=2)+'\n')
 from collections import Counter
 print(Counter(r['status'] for r in rows));print(Counter(r.get('reason','qualified') for r in rows))
if __name__=='__main__':main()
