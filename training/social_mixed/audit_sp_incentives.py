"""Native constructive witnesses, not an oracle policy or exhaustive planner."""
import argparse
from collections import Counter
from itertools import product
import hashlib
import json
from pathlib import Path
from training.social_mixed.weighted_rules import OutcomeRules


def replay(rules, world, target):
    node=rules.initial(); trace=[]
    while not node.state.is_terminal:
        actions=rules.actions(node)
        chosen=None
        if node.pending is not None:
            chosen=next(a for a in actions if a.to_dict().get('response')=='ACCEPT')
        else:
            actor=rules.actor(node);bits=node.state.snapshot_commitments()
            options=[]
            for a in actions:
                d=a.to_dict()
                if d['action']!='OFFER':continue
                partner=d['partner_id']
                proposed={actor:d['proposer_action'],partner:d['partner_action']}
                if all(all(not x or target[p][j] for j,x in enumerate(v)) for p,v in proposed.items()):
                    added=sum(x and not bits[p][j] for p,v in proposed.items() for j,x in enumerate(v))
                    if added:options.append((added,json.dumps(d,sort_keys=True),a))
            chosen=max(options,key=lambda x:x[:2])[2] if options else next(a for a in actions if a.to_dict()['action']=='PASS')
        trace.append(dict(player=rules.actor(node),action=chosen.to_dict()))
        node=rules.step(node,chosen,realized_world=world)
    return list(rules.terminal_payoffs(node,world)),trace


def audit(reset):
    rules=OutcomeRules(reset['raw']);world=reset['realized_world'];sizes=rules.spec.n_actions_per_player
    zero=[[0]*n for n in sizes];base,_=replay(rules,world,zero)
    certificates=[];seen=set();upper=[float("-inf")]*len(sizes)
    for flat in product((0,1),repeat=sum(sizes)):
        target=[];offset=0
        for n in sizes:target.append(flat[offset:offset+n]);offset+=n
        satisfaction=[(float(all(target[a.player_id][a.action_id] for a in g.required_actions)) if g.binary
                       else sum(target[a.player_id][a.action_id] for a in g.required_actions)/len(g.required_actions)) for g in rules.spec.goals]
        for i in range(len(sizes)):
            upper[i]=max(upper[i],sum(v*x for v,x in zip(world[i],satisfaction)))
        u,path=replay(rules,world,target)
        signature=tuple(u)
        if signature not in seen:
            seen.add(signature);certificates.append(dict(utility=u,path=path))
    improvements=[max(c['utility'][i]-base[i] for c in certificates) for i in range(len(sizes))]
    pareto=any(all(u>=b for u,b in zip(c['utility'],base)) and any(u>b for u,b in zip(c['utility'],base)) for c in certificates)
    harmful=any(any(u<b for u,b in zip(c['utility'],base)) for c in certificates)
    return dict(id=reset['id'],geometry=reset.get('geometry_source_id'),players=len(sizes),
                mode='binary' if all(g.binary for g in rules.spec.goals) else 'linear',
                baseline=base,compatible_state_upper=upper,witness_max_improvement=improvements,pareto_witness=pareto,
                harmful_interaction_witness=harmful,certificates=certificates)


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path('examples/social_mixed/data_reasoning_v5_candidate/selfplay_train.jsonl'))
    p.add_argument('--output',type=Path,default=Path('new/training_readiness_20260920/sp_incentives.json'));args=p.parse_args()
    payload=args.data.read_bytes();rows=[json.loads(l) for l in payload.splitlines()];results=[]
    for i,row in enumerate(rows):
        results.append(audit(row))
        if i%50==0:print(f'{i}/{len(rows)}',flush=True)
    summary=dict(resets=len(results),with_any_improvement=sum(any(x>0 for x in r['witness_max_improvement']) for r in results),
                 all_players_have_some_improvement=sum(all(x>0 for x in r['witness_max_improvement']) for r in results),
                 pareto_witness=sum(r['pareto_witness'] for r in results),harmful_witness=sum(r['harmful_interaction_witness'] for r in results),
                 players_with_no_possible_gain=sum(sum(u<=b for u,b in zip(r['compatible_state_upper'],r['baseline'])) for r in results))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(source=str(args.data),sha256=hashlib.sha256(payload).hexdigest(),
        limitation='Constructive full-information feasible paths; absence is not impossibility, acceptance is not incentive compatibility, and no policy receives hidden information.',summary=summary,results=results),indent=2))
    print(summary)

if __name__=='__main__':main()
