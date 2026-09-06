"""Task-relevant diagnostic family and fast, exact two-turn screening.

Selection is on reference gaps before any LLM call. This conditional family
must be reported separately from the unfiltered generated population.
"""
from dataclasses import replace
from itertools import combinations
import math
import numpy as np
from benac_p.belief import BeliefState
from benac_p.controlled import SoftProgressPolicy
from benac_p.menu_diagnose import fixture
from benac_p.observations import build_player_observation
from benac_p.schema import ActionRef, Goal, PassProposal, VALUE_TO_PREFERENCE, response_actions
from benac_p.state import GameState


def dependency_candidate(seed):
    rng=np.random.default_rng(seed)
    spec,prior,_=fixture()
    refs=[ActionRef(0,0),ActionRef(0,1),ActionRef(1,0),ActionRef(1,1),ActionRef(2,0)]
    possible=[r for k in (2,3) for r in combinations(refs,k)
              if len({a.player_id for a in r})>1 and r not in [g.required_actions for g in spec.goals]]
    requirement=possible[int(rng.integers(len(possible)))]
    own=int(rng.choice([-1,0,1]));extra=rng.choice([-1,0,1],size=(2,2))
    hypotheses=tuple(tuple(tuple(row)+(VALUE_TO_PREFERENCE[int(extra[i,j])],)
                            for j,row in enumerate(world)) for i,world in enumerate(prior.hypotheses))
    weight=float(rng.choice([.4,.5,.6]))
    prior=BeliefState((1,2),hypotheses,(math.log(weight),math.log(1-weight)))
    prefs=np.column_stack((spec.private_preferences,[own,*extra[0]]))
    spec=replace(spec,goals=spec.goals+(Goal(5,requirement),),private_preferences=prefs,seed=seed)
    policies={i:SoftProgressPolicy(temperature=float(rng.choice([.2,.25,.3]))) for i in (1,2)}
    return spec,prior,policies


def screen(spec,belief,policies):
    """Enumerate terminal payoff vectors, preserving a single latent world.

    Independent of BayesPlanner recursion. All final decisions share cached
    per-world Q vectors for each physical state. Used only for preselection.
    """
    if spec.round_robin!=(0,0):raise ValueError('Two ego turns required.')
    state=GameState(spec);prior=np.array(belief.probabilities);cache={}
    def terminal_q(child):
        key=child.snapshot_commitments()
        if key in cache:return cache[key]
        actions=child.legal_proposals();qs=[]
        for action in actions:
            if isinstance(action,PassProposal):q=np.full(len(prior),child.reward(0),dtype=float)
            else:
                offer=action.offer;actor=offer.partner_id
                obs=build_player_observation(child,actor,pending_offer=offer,pending_proposer_id=0)
                rewards=[]
                for response in response_actions(offer):
                    final=child.clone();final.resolve_offer(offer,response);rewards.append(final.reward(0))
                q=np.array([sum(p*r for (_,p),r in zip(policies[actor].response_distribution(
                    replace(obs,own_preferences=h[actor-1]),offer),rewards)) for h in belief.hypotheses])
            qs.append(q)
        cache[key]=actions,np.array(qs)
        return cache[key]
    rows=[]
    for action in state.legal_proposals():
        if isinstance(action,PassProposal):
            child=state.clone();child.apply_pass();_,q=terminal_q(child);value=float(max(q@prior))
            rows.append((action,value,value));continue
        offer=action.offer;actor=offer.partner_id
        obs=build_player_observation(state,actor,pending_offer=offer,pending_proposer_id=0)
        likelihood=np.array([[p for _,p in policies[actor].response_distribution(
            replace(obs,own_preferences=h[actor-1]),offer)] for h in belief.hypotheses])
        adaptive=frozen=0.
        for i,response in enumerate(response_actions(offer)):
            joint=prior*likelihood[:,i];prob=joint.sum();posterior=joint/prob
            child=state.clone();child.resolve_offer(offer,response);_,q=terminal_q(child)
            values=q@posterior;frozen_values=q@prior
            fi=next(j for j,v in enumerate(frozen_values) if max(frozen_values)-v<=1e-10)
            adaptive+=prob*max(values);frozen+=prob*values[fi]
        rows.append((action,float(adaptive),float(frozen)))
    best=max(rows,key=lambda row:row[1]);frozen_best=max(rows,key=lambda row:row[2])
    return dict(adaptive_value=best[1],adaptive_action=best[0].to_dict(),
                root_action_regret=best[1]-frozen_best[1],same_action_update_gain=best[1]-best[2])
