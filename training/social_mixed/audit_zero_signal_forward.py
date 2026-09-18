"""Forward native replay of every P4 action/world under its frozen policy.

Uses neither cached teacher values nor terminal payoff arrays. This verifies
returns for the selected strategy, not uniqueness or policy robustness.
"""
from copy import copy
import json
import numpy as np
from training.social_mixed.audit_zero_signal import SOURCE,OUT,read,cell,reconstruct,stable,solve,VALUES


def forward(e,start,world_index,node):
    entry=e.tree.entries[start];world=e.tree.worlds[world_index]
    if entry.actor is None:
        assert node.state.is_terminal
        bits=node.state.snapshot_commitments();satisfaction=[]
        for goal in e.rules.spec.goals:
            flags=[bits[r.player_id][r.action_id] for r in goal.required_actions]
            satisfaction.append(float(all(flags)) if goal.binary else sum(flags)/len(flags))
        return np.array([sum(v*s for v,s in zip(prefs,satisfaction)) for prefs in world]),1
    total=np.zeros(e.tree.n);paths=0
    for ai,action in enumerate(entry.actions):
        probability=e.tree.policy[start][ai,world_index]
        if probability==0:continue
        child=e.rules.step(node,action,realized_world=world)
        payoff,count=forward(e,entry.children[ai],world_index,child)
        total+=probability*payoff;paths+=count
    return total,paths


def main():
    results=[]
    for t in read(SOURCE/'bp_train.jsonl'):
        if not (cell(t) or '').startswith('P4/'):continue
        inp=t['input'];raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior']
        root,_,_=solve(stable([raw,inp['imposed_setup']]));e=copy(root);e.weights=root.weights.copy();entry=e.tree.entries[0]
        weights=e._weights(inp['player'],own,[]);values=[];paths=0
        for ai,action in enumerate(entry.actions):
            value=np.zeros(e.tree.n)
            for wi,world in enumerate(e.tree.worlds):
                if weights[wi]==0:continue
                actual=e.rules.step(entry.node,action,realized_world=world)
                payoff,count=forward(e,entry.children[ai],wi,actual)
                value+=weights[wi]*payoff;paths+=count
            values.append(value.tolist())
        np.testing.assert_allclose(values,t['teacher']['action_values'],atol=1e-9,rtol=0)
        results.append(dict(id=t['id'],profile=t['background_profile'],worlds=len(e.tree.worlds),actions=len(values),positive_probability_terminal_paths=paths,values=values,matched=True))
    (OUT/'p4_forward_replay.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(dict(tasks=len(results),paths=sum(r['positive_probability_terminal_paths'] for r in results),all_matched=True)))

if __name__=='__main__':main()
