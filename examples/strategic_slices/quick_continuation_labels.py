"""Three-case diagnostic: fixed terminal partner, raw versus reference-rollout leaves.

Exact continuation is a diagnostic teacher, not a cheap approximation or a
full best-response value function. No frozen corpus is modified.
"""
import argparse
from copy import copy
import json
from pathlib import Path
import numpy as np
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import replay_node, write_json
from training.strategic_slices.diagnose_bounded import root_entrances
from training.strategic_slices.values import extreme_value
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights


def run(case):
    rules=PrivateInvestigationRules(case['raw'])
    node=replay_node(rules,case['history'])
    prior=world_weights(rules.worlds,case['raw']['background_prior'])
    kwargs=dict(world_weights=prior,max_nodes=20000,seconds=12)
    short=BoundedPrivateWindow(rules,node,rules.worlds,lookahead_rr=1,**kwargs).solve()
    full=BoundedPrivateWindow(rules,node,rules.worlds,lookahead_rr=len(rules.spec.round_robin),**kwargs).solve()
    short.audit_native();full.audit_native()
    assert all(e.node.state.is_terminal for e in full.entries if e.actor is None)
    entrance=root_entrances(short)[0]
    ego=entrance['ego'];weights=np.array(entrance['entry_world_weights'])
    mapping={};stack=[(0,0)]
    while stack:
        si,fi=stack.pop();mapping[si]=fi
        s,f=short.entries[si],full.entries[fi]
        if s.actor is not None:
            assert [a.to_dict() for a in s.actions]==[a.to_dict() for a in f.actions]
            stack.extend(zip(s.children,f.children))
    fixed=copy(short)
    fixed.policy={si:full.policy[fi].copy() for si,fi in mapping.items() if short.entries[si].actor is not None}
    continuation=copy(fixed)
    continuation.entries=[copy(e) for e in short.entries]
    for si,e in enumerate(continuation.entries):
        if e.actor is None:e.payoff=full.values[mapping[si]].copy()
    def terminal_replay(policy):
        override={mapping[si]:p for si,p in policy.items()}
        values={}
        for fi in reversed(range(len(full.entries))):
            e=full.entries[fi]
            if e.actor is None:values[fi]=e.payoff[:,ego]
            else:values[fi]=np.einsum('aw,aw->w',override.get(fi,full.policy[fi]),np.stack([values[c] for c in e.children]))
        return float(weights@values[0])
    rows=[]
    for k in (1,2,3):
        for name,tree in [('original_short',short),('fixed_partner_raw_leaf',fixed),('fixed_partner_reference_continuation',continuation)]:
            best=extreme_value(tree,ego,0,weights,k)
            terminal=terminal_replay(best['policy'])
            if tree is continuation:assert abs(terminal-best['value'])<1e-8
            q=np.array(best['root_Q'])
            rows.append(dict(k=k,arm=name,objective_value=best['value'],terminal_value=terminal,
                root_Q=q.tolist(),best_root_actions=np.flatnonzero(q>=q.max()-1e-8).tolist()))
    return dict(name=case['name'],cutoff=short.cutoff,terminal_cutoff=full.cutoff,
        terminal_unrestricted_best=extreme_value(full,ego,0,weights,100)['value'],
        actions=[a.to_dict() for a in full.entries[0].actions],rows=rows,
        continuation_replay_verified=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=Path('new/local_data/strategic_slices_terminal_pair_quick_v1/cases.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    cases=json.loads(args.cases.read_text())[:3]
    results=[run(c) for c in cases]
    write_json(args.output,dict(scope='Three existing investigation entrances; convenience diagnostic, no population claim.',
        continuation='Exact rollout of the fixed terminal reference for all players after cutoff; also focal after its k decisions. Not an omniscient per-world best response.',
        evaluation='Canonical DP tie choice, evaluated against the same terminal partner with terminal-reference focal continuation; not best over all tied prefixes.',
        results=results))
    for r in results:
        print(r['name'],'terminal best',r['terminal_unrestricted_best'])
        for row in r['rows']:print(row['k'],row['arm'],row['best_root_actions'],round(row['terminal_value'],6))


if __name__=='__main__':main()
