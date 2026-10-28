"""Value of future public behavior history beyond decision-time physical observations.

An explicit new information channel, NOT a replacement for query-answer S.
The restricted agent remembers all its own decision-time observations/actions,
including commitments, pending offers, legal menus and private query answers.
Only extra public transcript evidence between those decisions is hidden.
Perfect recall is retained via realization-sequence information sets.
"""
from collections import defaultdict
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from training.b_sft.social_private_teacher import observed_slots
from new.benac_slice_pilot.metrics import _root_weights, _subtree, _groups
from .common import stable
from .values import extreme_value


def physical_observation(tree, index, ego, wi):
    e=tree.entries[index];node=e.node;world=tree.worlds[wi]
    return stable(dict(turn=node.state.turn_index,commitments=node.state.snapshot_commitments(),
        investigation_used=node.state.investigation_used,
        pending=None if node.pending is None else node.pending.to_dict(),
        own=world[ego],answers=sorted((p,g,world[p][g]) for p,g in set(observed_slots(node,ego))),
        legal=[a.to_dict() for a in e.actions]))


def public_behavior_value(tree, *, ego, root_index, root_weights, k,
                          seconds=5., max_variables=100000, hide_history=True):
    """Ex ante information value inside k decisions, fixed actual reference.

    Prefix history/belief at the entrance is fixed and NOT masked. This is not
    the value of ALL opponent behavior: any evidence inherent in a required
    physical observation remains available. Full and restricted optimize under
    identical true world weights/partner policies, never a fabricated posterior.
    hide_history=False is an independent sequence-form check of the full DP.
    """
    return public_history_value(tree,ego=ego,
        entries=[dict(root_index=root_index,world_masses=root_weights)],k=k,
        seconds=seconds,max_variables=max_variables,hide_history=hide_history)


def public_history_value(tree, *, ego, entries, k, seconds=5.,
                         max_variables=100000, hide_history=True):
    """Ex ante value over one root or a forest of first-focal-decision roots.

    world_masses are JOINT entrance/world masses, not independently normalized
    posteriors. Multiple roots must precede any focal action since tree root:
    this excludes retroactively forgetting the focal's own actions/observations.
    The same physical observation remains visible. Opponents keep the original
    full-reference policy, and no continuation is re-solved after a signal.
    """
    if type(k) is not int or k<1 or not entries:
        raise ValueError('Positive k and a focal decision root are required')
    roots={};order=[];counts={};seen=set()
    own_before={0:0}
    if len(entries)>1:
        for i,e in enumerate(tree.entries):
            for child in e.children:own_before[child]=own_before[i]+int(e.actor==ego)
    for entrance in entries:
        root=entrance['root_index'];masses=np.asarray(entrance['world_masses'],dtype=float)
        weights=_root_weights(tree,root,masses)
        if tree.entries[root].actor!=ego:raise ValueError('Not a focal entrance')
        if sum(weights[ids].sum()>0 for ids in _groups(tree,root,ego,None))!=1:
            raise ValueError('Each root must be one focal information cell')
        if len(entries)>1 and own_before[root]:raise ValueError('Cannot mask earlier focal decision memory')
        branch,branchcounts=_subtree(tree,root,ego)
        if seen.intersection(branch):raise ValueError('Entrance subtrees must be disjoint')
        seen.update(branch);order.extend(branch);counts.update(branchcounts);roots[root]=weights*masses.sum()
    total=sum(m.sum() for m in roots.values());roots={i:m/total for i,m in roots.items()}
    active=np.flatnonzero(sum(roots.values())>0);nworlds=len(tree.worlds)
    # Fixed-reference continuation values, independently computed on the native tree.
    baseline={}
    for i in reversed(order):
        e=tree.entries[i]
        baseline[i]=e.payoff[:,ego] if e.actor is None else np.einsum('aw,aw->w',tree.policy[i],np.stack([baseline[c] for c in e.children]))
    last={root:np.zeros(nworlds,dtype=int) for root in roots};reach={root:m.copy() for root,m in roots.items()}
    rowids=[0];cols=[0];data=[1.];rhs=[1.];nvars=1;cells={};assign={};objective=defaultdict(float)
    cell_nodes=defaultdict(set)
    for i in order:
        if i not in reach:continue
        e=tree.entries[i]
        if e.actor is None or counts[i]>=k:
            for wi in active:objective[int(last[i][wi])]+=reach[i][wi]*baseline[i][wi]
            continue
        for child in e.children:last[child]=last[i].copy()
        if e.actor==ego:
            for wi in active:
                parent=int(last[i][wi]);obs=physical_observation(tree,i,ego,int(wi))
                key=(parent,obs) if hide_history else (parent,i,obs)
                if key not in cells:
                    variables=np.arange(nvars,nvars+len(e.actions));nvars+=len(e.actions)
                    if nvars>max_variables:raise RuntimeError('Behavior-information variable budget exceeded')
                    row=len(rhs);rhs.append(0.)
                    rowids.extend([row]*(1+len(variables)));cols.extend([parent,*variables]);data.extend([-1.,*([1.]*len(variables))])
                    cells[key]=(parent,variables)
                parent,variables=cells[key];assert len(variables)==len(e.actions)
                assign[i,int(wi)]=(parent,variables);cell_nodes[key].add(i)
                for ai,child in enumerate(e.children):last[child][wi]=variables[ai]
        for ai,child in enumerate(e.children):reach[child]=reach[i] if e.actor==ego else reach[i]*tree.policy[i][ai]
    A=coo_matrix((data,(rowids,cols)),shape=(len(rhs),nvars)).tocsr();c=np.zeros(nvars)
    for seq,v in objective.items():c[seq]=v
    result=linprog(-c,A_eq=A,b_eq=rhs,bounds=(0,None),method='highs',options={'time_limit':seconds})
    if not result.success:raise RuntimeError('Behavior-information LP unavailable: '+result.message)
    assert np.max(np.abs(A@result.x-rhs))<1e-7
    policy={}
    for (i,wi),(parent,variables) in assign.items():
        if i not in policy:policy[i]=tree.policy[i].copy()
        q=np.maximum(result.x[variables],0.);q=q/q.sum() if q.sum()>1e-12 else np.eye(1,len(variables),0)[0]
        policy[i][:,wi]=q
    replay={}
    for i in reversed(order):
        e=tree.entries[i]
        replay[i]=e.payoff[:,ego] if e.actor is None else np.einsum('aw,aw->w',policy.get(i,tree.policy[i]),np.stack([replay[ch] for ch in e.children]))
    restricted=float(c@result.x)
    assert abs(sum(float(m@replay[root]) for root,m in roots.items())-restricted)<1e-7
    full=sum(float(m.sum())*extreme_value(tree,ego,root,m,k)['value'] for root,m in roots.items())
    if restricted>full+1e-7:raise AssertionError('Restricted information exceeds full-information optimum')
    if not hide_history:assert abs(full-restricted)<1e-7
    return dict(channel=('entry-and-future-public-history-v1' if len(entries)>1 else 'future-public-history-beyond-physical-observations-v1'),
        V_full=full,V_restricted=restricted,S=max(0.,full-restricted),
        merged_information_cells=sum(len(nodes)>1 for nodes in cell_nodes.values()),
        sequence_variables=nvars,policy_replay_verified=True,
        entrances=len(roots),scope='Physical observations, own decision recall and private answers retained; forest inputs use joint entrance/world masses')
