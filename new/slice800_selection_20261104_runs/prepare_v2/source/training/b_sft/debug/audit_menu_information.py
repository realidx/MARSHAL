"""Native MENU/OFFER audit with fixed-partner belief-use ablations.

The frozen-belief learner still sees and acts in each actual physical state but
does not update its type weights. This is an implementable deliberately limited
learner policy, NOT an information-theoretic no-observation optimum. Positive
gains identify candidates; zero gains do not prove information universally useless.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np

from training.b_sft.social_b_oracle import BeliefOracle, canonical
from training.b_sft.social_b_dataset import random_fixture
from training.b_sft.social_cases import bundle_fixture
from training.b_sft.social_cases_expand import information_fixture
from training.b_sft.shared_teacher import SearchLimit, TOL


def learner_values(tree, player, *, frozen=False):
    """Best response with history likelihoods vs a fixed-prior response policy."""
    if not frozen:
        updates,_=tree.response(player)
    else:
        values=[None]*len(tree.entries);updates={}
        for i in reversed(range(len(tree.entries))):
            e=tree.entries[i]
            if e.actor is None:values[i]=e.payoff;continue
            av=np.stack([values[c] for c in e.children])
            if e.actor!=player:values[i]=np.einsum('aw,awp->wp',tree.policy[i],av);continue
            probs=np.zeros((len(e.actions),tree.w))
            for ids in tree.groups[player]:
                weights=tree.world_weights[ids];means=np.einsum('awp,w->ap',av[:,ids,:],weights/weights.sum())
                own=means[:,player];social=means.sum(axis=1)-own
                primary=np.flatnonzero(own>=own.max()-TOL)
                final=primary[social[primary]>=social[primary].max()-TOL]
                probs[np.ix_(final,ids)]=1/len(final)
            updates[i]=probs;values[i]=np.einsum('aw,awp->wp',probs,av)
    policy=list(tree.policy)
    for i,p in updates.items():policy[i]=p
    return tree.evaluate(policy),policy


def best(rows, field):
    primary=max(r[field][0] for r in rows)
    tied=[r for r in rows if r[field][0]>=primary-TOL]
    social=max(r[field][1] for r in tied)
    return [r for r in tied if r[field][1]>=social-TOL]


def direct_value(tree,policy,player,own,root_action):
    """Re-execute native transitions and goal conjunctions, ignoring cached Q."""
    ids=[i for i,w in enumerate(tree.worlds) if w[player]==tuple(own)]
    weights=tree.world_weights[ids];weights=weights/weights.sum()
    def walk(i,node,wi):
        e=tree.entries[i]
        if e.actor is None:
            if node.state.turn_index<tree.end and not node.state.is_terminal:raise AssertionError('Premature leaf')
            commitments=node.state.snapshot_commitments()
            flags=[all(commitments[a.player_id][a.action_id] for a in g.required_actions) for g in tree.rules.spec.goals]
            return np.array([sum(v*on for v,on in zip(row,flags)) for row in tree.worlds[wi]],dtype=float)
        value=np.zeros(tree.n)
        for j,(a,child) in enumerate(zip(e.actions,e.children)):
            if policy[i][j,wi]:value+=policy[i][j,wi]*walk(child,tree.rules._apply(node,a),wi)
        return value
    root=tree.entries[0];child=root.children[root_action]
    values=[walk(child,tree.rules._apply(root.node,root.actions[root_action]),wi) for wi in ids]
    return np.average(values,axis=0,weights=weights)


def audit_root(raw,prefix,*,max_nodes=30000,seconds=3):
    oracle=BeliefOracle(raw,prefix,max_nodes=max_nodes,seconds=seconds)
    if oracle.node.pending is not None:raise ValueError('Compare proposal mechanisms at a proposal node')
    player=oracle.rules.actor(oracle.node)
    if player!=raw['ego']:raise ValueError('Root must be the learner proposal turn')
    tree=oracle.solve();full,full_policy=learner_values(tree,player);frozen,frozen_policy=learner_values(tree,player,frozen=True)
    ids=[i for i,w in enumerate(tree.worlds) if w[player]==tuple(raw['own_preferences'])]
    weights=tree.world_weights[ids];weights=weights/weights.sum()
    def expectation(v):
        mean=np.average(v[ids],axis=0,weights=weights)
        return [float(mean[player]),float(mean.sum()-mean[player])]
    def immediate(i):
        e=tree.entries[i]
        if e.actor is not None and e.node.pending is not None:
            return np.einsum('aw,awp->wp',tree.policy[i],np.stack([immediate(c) for c in e.children]))
        return np.array(tree.worlds)@e.node.state.goal_satisfaction()
    def later_learner(i):
        e=tree.entries[i]
        return e.actor==player or any(later_learner(c) for c in e.children)
    rows=[]
    for action,child in zip(tree.entries[0].actions,tree.entries[0].children):
        f=expectation(full[child]);b=expectation(frozen[child]);now=expectation(immediate(child))
        rows.append(dict(action=action.to_dict(),kind=action.to_dict().get('action'),
            full=f,frozen=b,immediate=now,later_learner=later_learner(child),
            belief_use_gain=[f[0]-b[0],f[1]-b[1]]))
    winners=best(rows,'full');ordinary=[r for r in rows if r['kind']!='MENU']
    candidates=[r for r in winners if r['kind']=='MENU' and
                (r['belief_use_gain'][0]>TOL or abs(r['belief_use_gain'][0])<=TOL and r['belief_use_gain'][1]>TOL)]
    # Compare MENU against ordinary root actions under the SAME partner policy.
    ordinary_best=best(ordinary,'full')
    menu_best=best([r for r in rows if r['kind']=='MENU'],'full') if any(r['kind']=='MENU' for r in rows) else []
    def strictly_better(a,b):return a[0]>b[0]+TOL or abs(a[0]-b[0])<=TOL and a[1]>b[1]+TOL
    immediate_only=[]
    for r in menu_best:
        if strictly_better(r['full'],ordinary_best[0]['full']) and not r['later_learner']:
            immediate_only.append(r['action'])
    witnesses=[]
    for r in winners:
        if r['belief_use_gain'][0]<=TOL:continue
        ai=next(i for i,a in enumerate(tree.entries[0].actions) if canonical(a.to_dict())==canonical(r['action']))
        for label,policy in (('full',full_policy),('frozen',frozen_policy)):
            direct=direct_value(tree,policy,player,raw['own_preferences'],ai)
            assert np.allclose([direct[player],direct.sum()-direct[player]],r[label],atol=TOL,rtol=0)
        child=tree.entries[tree.entries[0].children[ai]];branches=[]
        if child.node.pending is not None:
            ci=tree.entries[0].children[ai]
            for ri,(response,next_i) in enumerate(zip(child.actions,child.children)):
                mass=weights*tree.policy[ci][ri,ids];probability=float(mass.sum())
                if probability<=0:continue
                next_e=tree.entries[next_i]
                next_full=[];next_frozen=[]
                if next_e.actor==player:
                    # Own profile is the same on every conditioned world.
                    wi=ids[0]
                    next_full=[a.to_dict() for j,a in enumerate(next_e.actions) if full_policy[next_i][j,wi]>0]
                    next_frozen=[a.to_dict() for j,a in enumerate(next_e.actions) if frozen_policy[next_i][j,wi]>0]
                branches.append(dict(response=response.to_dict(),probability=probability,
                    joint_belief=[dict(preferences=tree.worlds[wi],weight=float(m/probability)) for wi,m in zip(ids,mass) if m>0],
                    public_commitments=next_e.node.state.snapshot_commitments(),
                    next_full_actions=next_full,next_frozen_actions=next_frozen))
        witnesses.append(dict(action=r['action'],direct_native_values_verified=True,branches=branches))
    return dict(source=raw['id'],menu_enabled=raw['game'].get('menu_enabled',False),
        raw=raw,prefix=prefix,nodes=len(tree.entries),certificate=tree.certificate,
        root_actions=len(rows),winners=[r['action'] for r in winners],actions=rows,
        menu_information_candidates=[r['action'] for r in candidates],
        strict_menu_advantage_without_later_learner=immediate_only,
        information_witnesses=witnesses,
        limitation='Frozen-prior ablation includes evidence encoded in physical states. Positive value is a belief-use diagnostic, not pure information value or a retention verdict.')


def immediate_fixture():
    reqs=[[(0,0),(1,0)],[(0,1),(1,1)],[(1,0),(2,0)]]
    raw=dict(id='terminal-menu-matching',ego=0,history=[],own_preferences=[1,1,0],
        type_catalogues={'0':[[1,1,0]],'1':[[1,-1,1],[-1,1,1]],'2':[[0,0,1]]},
        game=dict(n_players=3,n_actions_per_player=[2,2,1],goals=[dict(goal_id=g,binary=True,
            required_actions=[dict(player_id=p,action_id=a) for p,a in req]) for g,req in enumerate(reqs)],
            round_robin=[1,2,0],max_changes=1,menu_enabled=False))
    return raw,[dict(action='PASS'),dict(action='PASS')]


def run(out,seeds=12):
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True)
    jobs=[]
    raw,prefix=information_fixture('independent')
    # Stop before the first of two consecutive learner proposal turns, rather
    # than after it: the old tiny probe accidentally missed this opportunity.
    for mode in ('independent','two_types','wait_for_better'):
        r,p=information_fixture(mode)
        jobs.append((r,p[:3]))
    jobs.append(immediate_fixture())
    # Known terminal opportunity: measures immediate option-matching advantages.
    for seed in range(951000,951000+seeds):
        try:
            r,p,_,_=random_fixture(seed)
            node=BeliefOracle(r,p).node
            from training.b_sft.shared_teacher import native
            from benac_p.endgame_diagnose import decode_action
            rules,_,_=native(r)
            # Preference-independent setup to the penultimate proposer turn.
            while node.state.turn_index < len(r['game']['round_robin'])-2:
                a={'action':'PASS'};p.append(a);node=rules._apply(node,decode_action(a))
            r['ego']=rules.actor(node);r['own_preferences']=list(r['type_catalogues'][str(r['ego'])][0])
            jobs.append((r,p))
        except (ValueError,SearchLimit) as exc:
            jobs.append((dict(id=f'fixture-{seed}',error=str(exc)),[]))
    results=[]
    for raw,prefix in jobs:
        for menu in (False,True):
            r=deepcopy(raw)
            if 'error' in r:result=dict(source=r['id'],status='fixture_failure',detail=r['error'])
            else:
                r['game']['menu_enabled']=menu;r['id']+=('-menu' if menu else '-offer')
                try:result=dict(status='ok',**audit_root(r,prefix))
                except (ValueError,SearchLimit) as exc:result=dict(source=r['id'],status='solver_failure',detail=str(exc))
            results.append(result)
            with (out/'roots.jsonl').open('a') as f:f.write(json.dumps(result)+'\n')
            print(json.dumps({k:result[k] for k in ('source','status','nodes','root_actions') if k in result}),flush=True)
    successes=[r for r in results if r['status']=='ok']
    summary=dict(statuses=dict(Counter(r['status'] for r in results)),
        menu_roots=sum(r['menu_enabled'] for r in successes),
        menu_information_candidate_roots=sum(bool(r['menu_information_candidates']) for r in successes),
        strict_menu_advantage_without_later_learner_roots=sum(bool(r['strict_menu_advantage_without_later_learner']) for r in successes),
        decision='No automatic retention/deletion from a finite diagnostic. Default training remains MENU-disabled pending a certified information-value witness.',
        source_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--seeds',type=int,default=12)
    a=p.parse_args();run(a.out,a.seeds)
