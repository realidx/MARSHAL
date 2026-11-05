"""Independent native one-remaining-proposal review of a real information node."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from .run import snapshot,inputs
from new.sparse_solver_v1_20261023.common import parents,write,sha
from new.sparse_solver_v1_20261023.probe import build
from training.b_sft.decision_policy import optimal_indices


def remaining_proposal(rules,node,world):
    """No reference probabilities: enumerate the final proposal and rational response."""
    actor=rules.actor(node);rows=[]
    assert node.state.turn_index==len(rules.spec.round_robin)-1 and node.pending is None
    for a in rules.actions(node):
        child=rules.step(node,a,realized_world=world)
        if child.pending is None:
            assert child.state.is_terminal
            value=np.array(rules.terminal_payoffs(child,world))
        else:
            responder=rules.actor(child);actions=rules.actions(child)
            payoffs=np.array([rules.terminal_payoffs(rules.step(child,b,realized_world=world),world) for b in actions])
            best=optimal_indices(payoffs,responder,actions,1e-9)
            value=payoffs[best].mean(axis=0)
        rows.append(dict(action=a.to_dict(),terminal_payoffs=value.tolist()))
    best=max(row['terminal_payoffs'][actor] for row in rows)
    return dict(actor=actor,best_value=best,
        best_actions=[r for r in rows if r['terminal_payoffs'][actor]>=best-1e-9],all_actions=rows)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    identity=inputs('terminal')[0]
    snapshot(args.output,dict(operation='Independent native terminal enumeration of real parent0 node5570 cell2',
        input_run=str(args.run),input_label_sha256=sha(args.run/'cases/0/labels.jsonl.gz'),
        index=0,node=5570,cell=2,terminal_response='own optimal, then others sum; remaining ties uniform',
        reference_policy_used_for_new_payoffs=False),{0:identity})
    parent=parents()[0];tree=build(parent,seconds=60)
    with gzip.open(args.run/'cases/0/labels.jsonl.gz','rt') as stream:
        row=next(r for r in map(json.loads,stream) if r['node']==5570 and r['cell']==2)
    ids=[wi for wi,p in zip(row['world_ids'],row['posterior']) if p>0]
    assert len(ids)==1
    world=tree.worlds[ids[0]];node=tree.entries[5570].node;rules=tree.rules
    branches=[]
    for a in rules.actions(node):
        nextnode=rules.step(node,a,realized_world=world)
        result=remaining_proposal(rules,nextnode,world)
        branches.append(dict(response=a.to_dict(),immediate_payoffs=np.einsum('pg,g->p',world,nextnode.state.goal_satisfaction()).tolist(),**result))
    independently_computed=[r['best_value'] for r in branches]
    np.testing.assert_allclose(independently_computed,row['Q'],atol=1e-9,rtol=0)
    write(args.output/'CASE_REVIEW.json',dict(parent_index=0,node=5570,cell=2,
        raw_game=parent['raw']['game'],true_complete_world=world,
        own_type=row['own_type'],own_answer=row['private_answers'],
        history=[e.to_dict() for e in node.state.transcript],pending=node.pending.to_dict(),
        oracle_Q=row['Q'],S_private=row['S_private'],independent_branches=branches,
        interpretation='A free unilateral commitment can destroy a later mutually beneficial exchange by changing the responder fallback payoff.'))
    write(args.output/'COMPLETE.json',dict(native_enumeration_matches_Q=True,
        review_sha256=sha(args.output/'CASE_REVIEW.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(Q=independently_computed,S_private=row['S_private'],passed=True))


if __name__=='__main__':main()
