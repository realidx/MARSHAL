"""Select terminal neighborhoods on one initial-state certified oracle profile.

All entrance masses are prior times the SAME oracle's full prefix likelihood.
No epsilon exploration, exogenous prefix, entrance re-solve or prior reset.
"""
from collections import defaultdict
from itertools import permutations,product
import numpy as np
from training.b_sft.social_private_teacher import observed_slots
from .common import digest,stable
from .values import window_values, masked_answer_value
from .behavior_information import public_behavior_value

CONTRACT = 'initial-terminal-oracle-consistent-v1'


def canonical_parent(raw):
    """Ignore arbitrary player/action/goal names when counting distinct parents."""
    game=raw['game'];n=game['n_players'];representations=[]
    for players in permutations(range(n)):
        for actions in product(*(tuple(permutations(range(k))) for k in game['n_actions_per_player'])):
            goals=[]
            for g,goal in enumerate(game['goals']):
                geometry=(bool(goal['binary']),tuple(sorted((players[a['player_id']],actions[a['player_id']][a['action_id']]) for a in goal['required_actions'])))
                goals.append((geometry,g))
            goals.sort();order=[g for _,g in goals]
            coordinates=[0]*n;types=[None]*n
            for p in range(n):
                coordinates[players[p]]=game['n_actions_per_player'][p]
                types[players[p]]=sorted(tuple(row[g] for g in order) for row in raw['type_catalogues'][str(p)])
            prior=raw['background_prior']['weights'];total=sum(prior.values())
            representations.append(stable((coordinates,[geometry for geometry,_ in goals],
                [players[p] for p in game['round_robin']],game['max_changes'],types,
                {k:v/total for k,v in prior.items()})))
    return digest(min(representations))


def oracle_reach(tree):
    """Joint public-history/world masses, retaining private-answer uncertainty."""
    reach={0:tree.world_weights.copy()}; histories={0:[]}
    for i,e in enumerate(tree.entries):
        if i not in reach:continue
        for ai,child in enumerate(e.children):
            masses=reach[i]*tree.policy[i][ai]
            if masses.sum()>0:
                reach[child]=masses
                histories[child]=histories[i]+[ai]
    return reach,histories


def entrance_pool(tree, threshold=1e-10, *, max_remaining_proposals=3):
    """Enumerate same-profile entrances; an expanded range needs an initial terminal oracle.

    The historical default remains three proposals. None includes all reachable
    entrances of an already certified complete parent; it never extends a tree
    or substitutes a cutoff value. Local controlled decision counts stay k=1/2/3.
    """
    if max_remaining_proposals is not None and (type(max_remaining_proposals) is not int or max_remaining_proposals < 1):
        raise ValueError('Positive proposal bound or None required')
    if max_remaining_proposals is None or max_remaining_proposals > 3:
        if (not tree.certificate or not tree.certificate.get('verified')
                or tree.entries[0].node.state.turn_index != 0
                or any(not e.node.state.is_terminal for e in tree.entries if e.actor is None)):
            raise ValueError('Expanded entrances require a certified initial terminal tree')
    reach,histories=oracle_reach(tree);pool=[]
    total=len(tree.rules.spec.round_robin)
    for i,masses in reach.items():
        e=tree.entries[i]
        if e.actor is None:continue
        remaining=total-e.node.state.turn_index
        if remaining < 1 or (max_remaining_proposals is not None and remaining > max_remaining_proposals):continue
        ego=e.actor;future=list(tree.rules.spec.round_robin[e.node.state.turn_index:])
        positions=[j for j,p in enumerate(future) if p==ego]
        for ids in tree.information_groups[i]:
            joint=np.zeros(tree.w);joint[ids]=masses[ids]
            mass=float(joint.sum())
            if mass<=threshold:continue
            weights=joint/mass;world=tree.worlds[int(ids[0])]
            pool.append(dict(root_index=i,ego=ego,own=list(world[ego]),
                private_results=[(p,g,world[p][g]) for p,g in observed_slots(e.node,ego)],
                history=histories[i],entry_world_weights=weights.tolist(),oracle_information_set_mass=mass,
                remaining_proposals=remaining,decision_kind='response' if e.node.pending is not None else 'proposal',
                focal_next_proposal_offset=positions[0] if positions else None,
                focal_remaining_proposals=len(positions)))
    return pool


def stratified_entrances(pool, limit=24):
    """Cycle seats/remaining turns/action kinds, then likelihood-ranked members."""
    groups=defaultdict(list)
    for row in pool:
        key=(row['ego'],row['remaining_proposals'],row['decision_kind'],
             row['focal_next_proposal_offset'] if row['focal_next_proposal_offset'] is not None else -1)
        groups[key].append(row)
    for key in groups:
        groups[key].sort(key=lambda r:(-r['oracle_information_set_mass'],digest((r['history'],r['own'],r['private_results']))))
    result=[]
    while groups and len(result)<limit:
        for key in sorted(list(groups)):
            result.append(groups[key].pop(0))
            if not groups[key]:del groups[key]
            if len(result)==limit:break
    return result


def decision_capacity(tree,root,ego,weights):
    """Positive-world native branches: capacity is not realized rollout length."""
    order=[];pending=[root]
    while pending:
        i=pending.pop();order.append(i);pending.extend(tree.entries[i].children)
    lo={};hi={};types={}
    for i in reversed(order):
        e=tree.entries[i]
        if e.actor is None:lo[i]=hi[i]=0;types[i]=set();continue
        children=list(e.children)
        increment=int(e.actor==ego)
        lo[i]=increment+min(lo[c] for c in children)
        hi[i]=increment+max(hi[c] for c in children)
        types[i]=set().union(*(types[c] for c in children))
        if increment:types[i].add('response' if e.node.pending is not None else 'proposal')
    return dict(min_focal_decisions_over_native_branches=lo[root],max_focal_decisions_over_native_branches=hi[root],
                possible_focal_decision_kinds=sorted(types[root]),scope='All legal native continuations, not oracle rollout probabilities')


def measure_parent(tree,parent_id,limit=24,cap=16):
    pool=entrance_pool(tree);chosen=stratified_entrances(pool,limit)
    values=tree.evaluate();rows=[];diagnostics=[]
    for entrance in chosen:
        root=entrance['root_index'];ego=entrance['ego'];weights=entrance['entry_world_weights']
        capacity=decision_capacity(tree,root,ego,weights)
        curves=[dict(k=k,**window_values(tree,ego,root,weights,k)) for k in (1,2,3)]
        previous_c=previous_s=0.
        eid=digest((parent_id,root,ego,entrance['own'],entrance['private_results']))[:24]
        for metric in curves:
            c=metric['C_span'];increment=c-previous_c;previous_c=c
            if c<=.1:continue
            query=[]
            for ai,action in enumerate(tree.entries[root].actions):
                action=action.to_dict()
                if action.get('action')!='INVESTIGATE':continue
                slot=(action['player'],action['goal'])
                support={w[slot[0]][slot[1]] for w,m in zip(tree.worlds,weights) if m>0}
                if len(support)<=1:s=conditional=0.
                else:
                    result=masked_answer_value(tree,ego=ego,root_index=root,root_weights=weights,query_slot=slot,k=metric['k'])
                    s=result['S'];conditional=max(0.,result['full']['root_action_values'][ai]-result['masked']['root_action_values'][ai])
                query.append(dict(slot=list(slot),S=s,S_given_query=conditional))
            behavior=public_behavior_value(tree,ego=ego,root_index=root,root_weights=weights,k=metric['k'],seconds=10.)
            assert abs(behavior['V_full']-metric['V_star'])<1e-7
            s_query=max((x['S'] for x in query),default=0.);s=max(s_query,behavior['S'])
            keep=metric['k']==1 or increment>.05 or s-previous_s>.05
            previous_s=s
            diagnostics.append(dict(entrance_id=eid,k=metric['k'],C_span=c,S_query=s_query,S_future_history=behavior['S'],eligible=keep))
            if not keep:continue
            reference_value=float(np.array(weights)@values[root][:,ego])
            member=dict(root_index=root,history=entrance['history'],history_encoding='native-action-indices',probability=1.,
                world_weights=weights,joint_world_masses=weights,remaining_proposals=entrance['remaining_proposals'],
                **{key:metric[key] for key in ('V_star','V_min','C_span','root_Q')})
            rows.append(dict(id=digest((eid,metric['k']))[:24],entrance_id=eid,parent_id=parent_id,ego=ego,k=metric['k'],
                V_star=metric['V_star'],V_min=metric['V_min'],C_span=c,members=[member],
                entry_kind='oracle-reach-singleton',information_scope='one-entrance-conditioned-on-own-information',
                information_channels=dict(query_answer=s_query,future_public_history=behavior['S'],entry_and_future_public_history=None),
                query_details=query,future_history_diagnostic=behavior,
                group_reach_probability=entrance['oracle_information_set_mass'],
                decision_kind=entrance['decision_kind'],focal_next_proposal_offset=entrance['focal_next_proposal_offset'],
                focal_remaining_proposals=entrance['focal_remaining_proposals'],decision_capacity=capacity,
                k_is_maximum_controlled_decisions=True,reference_value=reference_value,reference_window_gain=metric['V_star']-reference_value,
                information_positive=s>.05,detectable_information_value=s>1e-6))
    # Preserve distinct entrances before additional k windows of one entrance.
    rows.sort(key=lambda r:(not r['information_positive'],r['k'],r['id']))
    strata=defaultdict(list)
    for row in rows:
        strata[(row['ego'],row['members'][0]['remaining_proposals'],row['decision_kind'])].append(row)
    selected=[];seen=set()
    # Do not let numerous k=1 entrances crowd out eligible k=2/3 windows.
    for ego,k in sorted({(r['ego'],r['k']) for r in rows}):
        row=next(r for r in rows if r['ego']==ego and r['k']==k)
        selected.append(row);seen.add(row['entrance_id'])
    for unique_only in (True,False):
        while len(selected)<cap:
            progressed=False
            for key in sorted(strata):
                row=next((r for r in strata[key] if r['id'] not in {x['id'] for x in selected}
                          and (not unique_only or r['entrance_id'] not in seen)),None)
                if row is not None:
                    selected.append(row);seen.add(row['entrance_id']);progressed=True
                if len(selected)==cap:break
            if not progressed:break
    return selected,dict(reachable_information_cells=len(pool),sampled_information_cells=len(chosen),
        eligible_windows=len(rows),retained=len(selected),distinct_retained_histories=len({tuple(r['members'][0]['history']) for r in selected}),
        distinct_retained_entrances=len({r['entrance_id'] for r in selected}),curves=diagnostics)


def prefix_joint_mass(tree, history, ego, posterior):
    """Independent path-only likelihood reconstruction for readback auditing."""
    masses=tree.world_weights.copy();index=0
    for ai in history:
        masses*=tree.policy[index][ai];index=tree.entries[index].children[ai]
    support=np.flatnonzero(np.asarray(posterior)>0)
    if not len(support):raise ValueError('Empty posterior')
    world=tree.worlds[int(support[0])];slots=observed_slots(tree.entries[index].node,ego)
    mask=np.array([w[ego]==world[ego] and all(w[p][g]==world[p][g] for p,g in slots) for w in tree.worlds])
    masses*=mask
    if masses.sum()<=0:raise ValueError('Oracle-zero-probability entrance')
    if not np.allclose(masses/masses.sum(),posterior,atol=1e-9,rtol=0):
        raise ValueError('Posterior does not follow the saved oracle prefix')
    return index,masses
