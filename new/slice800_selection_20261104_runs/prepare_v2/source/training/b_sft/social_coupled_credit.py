"""Outcome-derived B/P credit prototype; no LM calls, solver labels or optimizer.

Callbacks provide free-text B and native P actions. Branches replay a fixed
public prefix with matched hidden worlds and random seeds. The supplied partner
and future-learner policies execute every remaining move in the native game.
This training sampler is separate from a deployment-time single-request policy.
"""
from copy import deepcopy
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
from random import Random

from training.b_sft.shared_teacher import native

VERSION = 'social-coupled-credit-prototype-v1'


def credits(matrix):
    """Leave-one-out centered returns, NOT ready-made PPO advantages.

    Rows are B samples, columns are P samples. Incomplete comparisons are
    masked as a whole; never silently rank only the successful branches.
    """
    if len(matrix)<2 or any(len(r)<2 for r in matrix) or len({len(r) for r in matrix})!=1:
        raise ValueError('Need a rectangular K>=2, J>=2 outcome matrix')
    if any(v is None for row in matrix for v in row):
        return dict(mask=False,B_credit=None,P_credit=None,reason='Incomplete matched comparison')
    import math
    if any(not math.isfinite(v) for row in matrix for v in row):
        raise ValueError('Nonfinite outcome')
    means=[sum(row)/len(row) for row in matrix]
    b=[v-(sum(means)-v)/(len(means)-1) for v in means]
    p=[[v-(sum(row)-v)/(len(row)-1) for v in row] for row in matrix]
    return dict(mask=True,B_mean_return=means,B_credit=b,P_credit=p,
                scope='Sampled policy-conditioned outcome contrasts; not a causal proof or PPO advantages')


@dataclass
class NativeEpisode:
    raw: dict
    prefix: list

    def __post_init__(self):
        self.raw=deepcopy(self.raw)
        self.rules,self.worlds,_=native(self.raw)
        self.node=self.rules.initial();self.history=[]
        for action in self.prefix:self.step(action)

    def step(self, action):
        # Strict JSON match also rejects booleans and extra fields.
        canonical=lambda x:json.dumps(x,sort_keys=True,allow_nan=False)
        legal=self.rules.actions(self.node)
        match=[a for a in legal if canonical(a.to_dict())==canonical(action)]
        if len(match)!=1:raise ValueError('Invalid native submission')
        self.node=self.rules._apply(self.node,match[0]);self.history.append(match[0].to_dict())

    def visible(self):
        return dict(player=self.raw['ego'],game=self.rules.spec.to_dict(include_private=False),
                    own_preferences=deepcopy(self.raw['own_preferences']),
                    public_type_catalogues=deepcopy(self.raw['type_catalogues']),
                    public_state=deepcopy(self.node.state.public_state()),
                    pending_offer=None if self.node.pending is None else self.node.pending.to_dict(),
                    history=deepcopy(self.history),setup_prefix_length=len(self.prefix),
                    legal_actions=[a.to_dict() for a in self.rules.actions(self.node)])

    def payoff(self, world):
        if not self.node.state.is_terminal:raise ValueError('No payoff before terminal')
        return [float(sum(v*s for v,s in zip(row,self.node.state.goal_satisfaction()))) for row in world]


def normalized_utility(utility, own):
    low=sum(min(x,0) for x in own);high=sum(max(x,0) for x in own)
    if high==low:raise ValueError('No own utility variation')
    return (utility-low)/(high-low)


def experiment(raw,prefix,worlds,sample_b,sample_p,learner,partner,*,k=2,j=2,seed=7):
    """Call signatures:

    B(visible, rng)->text; P(visible, B, rng)->native action;
    learner(visible, rng)->native action; partner(episode, world, rng)->action.
    Only the environment-side partner callback has access to hidden world.
    Worlds receive equal weight, identically for every B/P branch.
    Rollout ValueError/RuntimeError and invalid actions are masked. Root B/P
    sampling errors abort the experiment rather than silently resampling. The existing
    retry/penalty contract must be integrated before live generation/training.
    """
    if k<2 or j<2:raise ValueError('K and J must both be at least two')
    base=NativeEpisode(raw,prefix)
    if base.node.state.is_terminal or base.rules.actor(base.node)!=raw['ego']:
        raise ValueError('Need a nonterminal learner decision')
    worlds=tuple(tuple(tuple(row) for row in w) for w in worlds)
    if not worlds or len(set(worlds))!=len(worlds) or any(w not in base.worlds for w in worlds):
        raise ValueError('Provide distinct admissible worlds with explicit weighting')
    beliefs=[];branches=[];matrix=[]
    for bi in range(k):
        b=sample_b(deepcopy(base.visible()),Random(seed+100000+bi))
        if not isinstance(b,str) or not b.strip():raise ValueError('B must be nonempty free text')
        beliefs.append(b);row=[]
        for pi in range(j):
            # Same P random stream across B; same continuation stream across
            # B AND P for each world. These are explicit common-random-number
            # controls, not a guarantee of identical semantic trajectories.
            pseed=seed+200000+pi
            action=sample_p(deepcopy(base.visible()),b,Random(pseed))
            outcomes=[]
            for wi,world in enumerate(worlds):
                env=NativeEpisode(raw,prefix);rng=Random(seed+300000+wi)
                try:
                    env.step(action)
                    while not env.node.state.is_terminal:
                        if env.rules.actor(env.node)==raw['ego']:
                            move=learner(deepcopy(env.visible()),rng)
                        else:move=partner(env,world,rng)
                        env.step(move)
                    pay=env.payoff(world);reward=normalized_utility(pay[raw['ego']],raw['own_preferences'])
                    outcomes.append(dict(world_index=wi,terminal=True,utilities=pay,reward=reward,history=env.history))
                except (ValueError,RuntimeError) as exc:
                    outcomes.append(dict(world_index=wi,terminal=False,utilities=None,reward=None,
                                         error_type=type(exc).__name__,history=env.history))
            mean=(sum(o['reward'] for o in outcomes)/len(outcomes)
                  if all(o['reward'] is not None for o in outcomes) else None)
            row.append(mean);branches.append(dict(B_index=bi,P_index=pi,B=b,action=action,
                                                 p_seed=pseed,outcomes=outcomes,mean_return=mean))
        matrix.append(row)
    return dict(version=VERSION,actual_LM=False,optimizer_updates=0,seed=seed,
                B_samples=beliefs,distinct_B=len(set(beliefs)),outcome_matrix=matrix,
                credit=credits(matrix),branches=branches,
                sampling=dict(B=k,P=k*j,native_episodes=k*j*len(worlds),worlds=len(worlds),
                              world_weighting='uniform over the explicitly supplied world set'),
                limitations=['Scripted/callback prototype, no deployment single-request adapter yet.',
                             'No exact B or reference-Q teacher is used.',
                             'B contrasts evaluate the current P sampler, not intrinsic belief truth.',
                             'No PPO, token attribution, live retry or failure penalty integration yet.',
                             'World averaging reduces lucky-world effects only when its distribution is appropriate.',
                             'Admissible catalogue worlds are not automatically consistent with observed partner behavior.'])


def fixture():
    own=[1,1,0]
    raw=dict(id='coupled-credit-native',ego=0,history=[],own_preferences=own,
        type_catalogues={'0':[own],'1':[[1,0,1],[-1,0,1]],'2':[[0,1,1],[0,-1,1]]},
        game=dict(n_players=3,n_actions_per_player=[1,1,1],max_changes=1,
                  round_robin=[1,2,0],menu_enabled=False,
                  goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=p,action_id=0) for p in ps])
                         for g,ps in enumerate([(0,1),(0,2),(1,2)])]))
    return raw,[{'action':'PASS'},{'action':'PASS'}]


def greedy_partner(env,world,rng):
    p=env.rules.actor(env.node);actions=env.rules.actions(env.node)
    def value(a):
        child=env.rules._apply(env.node,a)
        return sum(v*s for v,s in zip(world[p],child.state.goal_satisfaction()))
    return max(actions,key=value).to_dict()


def demo():
    raw,prefix=fixture();base=NativeEpisode(raw,prefix)
    def run(worlds):
        bs=iter(['Partner 1 may accept a joint commitment.','Partner 2 may accept a joint commitment.'])
        calls=CounterSampler()
        def p(ctx,b,rng):
            partner=1 if 'Partner 1' in b else 2
            return calls.action(partner)
        return experiment(raw,prefix,worlds,lambda ctx,rng:next(bs),p,
                          lambda ctx,rng:ctx['legal_actions'][0],greedy_partner)
    return dict(single_world_control=run([base.worlds[1]]),
                balanced_uncertainty_control=run(base.worlds),
                note='No informative history: balanced worlds should NOT reward guessing one partner over the other.')


class CounterSampler:
    def __init__(self):self.n=0
    def action(self,partner):
        self.n+=1
        return ({'action':'OFFER','partner_id':partner,'proposer_action':[1],'partner_action':[1]}
                if self.n%2 else {'action':'PASS'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a fresh output file')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result=demo();args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v['credit'] for k,v in result.items() if isinstance(v,dict)},indent=2))
