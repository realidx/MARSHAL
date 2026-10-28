"""Extend terminal payoff decomposition to provably frozen commitment tails."""
from pathlib import Path
import numpy as np
from new import A2H2_structure_20261026 as d
from training.b_sft.social_private_teacher import observed_slots

VERSION='A2H2-action-goal-frozen-tail-audit-v2'
REG=d.ROOT/'examples/strategic_slices/versions/A2H2_structure_frozen_tail_v2_20261026/SNAPSHOT.json'


def decomposition(indexed,row,node):
    if node.pending is not None:return None
    rules=indexed.rules;worlds=rules.worlds;focal=row['actor'];base=node.state.goal_satisfaction();result=[]
    future=list(rules.spec.round_robin[node.state.turn_index+1:])
    lookup={o['action']:o for o in row.get('offers',[])}
    for ai,action in enumerate(rules.actions(node)):
        if action.to_dict().get('action')!='OFFER':continue
        response=rules._apply(node,action)
        if any(response.state.offer_used[p]<rules.offer_limit for p in future):return None
        accept=next(a for a in rules.actions(response)if a.to_dict()['response']=='ACCEPT')
        accepted=rules._apply(response,accept);delta=accepted.state.goal_satisfaction()-base
        partner=action.offer.partner_id;cases=[];qlo=qhi=0.
        for wi,m in zip(row['world_ids'],row['posterior']):
            if m<=0:continue
            world=worlds[wi];own=float(np.dot(world[partner],delta))
            compatible=[w for w in worlds if w[partner]==world[partner]and all(w[p][g]==world[p][g]for p,g in observed_slots(response,partner))]
            social=[float(sum(np.dot(w[p],delta)for p in range(rules.spec.n_players)if p!=partner))for w in compatible]
            if own>d.EPS:lo=hi=1.;reason='strict_own_accept'
            elif own<-d.EPS:lo=hi=0.;reason='strict_own_reject'
            elif min(social)>d.EPS:lo=hi=1.;reason='own_tie_robust_social_accept'
            elif max(social)<-d.EPS:lo=hi=0.;reason='own_tie_robust_social_reject'
            else:lo=0.;hi=1.;reason='social_belief_or_remaining_tie_not_resolved'
            u0=float(np.dot(world[focal],base));du=float(np.dot(world[focal],delta))
            qlo+=m*min(u0+lo*du,u0+hi*du);qhi+=m*max(u0+lo*du,u0+hi*du)
            cases.append(dict(world_id=wi,posterior=m,partner_type=world[partner],partner_own_gain=own,
                own_gain_by_goal=(np.array(world[partner])*delta).tolist(),other_gain_range=[min(social),max(social)],
                acceptance_bounds=[lo,hi],reason=reason))
        assert qlo-1e-7<=row['Q'][ai]<=qhi+1e-7
        o=lookup[ai];expected=o['Q_reject']+o['acceptance']*(o['Q_accept']-o['Q_reject'])
        assert abs(expected-row['Q'][ai])<1e-7
        result.append(dict(action=ai,offer=action.to_dict(),goal_satisfaction_delta=delta.tolist(),
            Q=row['Q'][ai],acceptance=o['acceptance'],own_accept=o['Q_accept'],own_reject=o['Q_reject'],
            independent_Q_bounds=[qlo,qhi],strictly_reconstructed=abs(qhi-qlo)<1e-7,cases=cases,
            frozen_tail_proof=dict(native_terminal_after_response=not future,remaining_proposers=future,
                offer_used_after_proposal=response.state.offer_used,offer_limit=rules.offer_limit,
                no_future_offer_possible=True,note='PASS and INVESTIGATE cannot change commitments or utility; no new cutoff/evaluator')))
    return result


if __name__=='__main__':
    d.VERSION,d.REG=VERSION,REG
    d.terminal_decomposition=decomposition
    original=d.c.snapshot
    def snapshot(out,config,inputs=None):
        config=dict(config,terminal_bounds='Native terminal OR all remaining proposers have already exhausted offer quota after this proposal; exact payoff-freeze proof; otherwise no decomposition',
            diagnostic_extension='Original v1 native replay and labels unchanged; extend only independent payoff bounds')
        return original(out,config,inputs)
    d.c.snapshot=snapshot
    d.main()
