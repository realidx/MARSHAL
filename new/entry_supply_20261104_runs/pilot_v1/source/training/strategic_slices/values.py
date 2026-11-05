"""Exact best/worst contingent window values against one fixed reference."""
import numpy as np
from new.benac_slice_pilot.metrics import _groups, _root_weights, _subtree, masked_answer_value


def extreme_value(tree, ego, root, weights, k, maximize=True):
    if k < 1 or tree.entries[root].actor != ego:
        raise ValueError('A positive ego-decision window is required')
    weights = _root_weights(tree, root, weights)
    if sum(weights[ids].sum() > 0 for ids in _groups(tree, root, ego, None)) != 1:
        raise ValueError('Entrance must be one player information set')
    order, counts = _subtree(tree, root, ego)
    reach = {root: weights}
    for index in order:
        entry = tree.entries[index]
        controlled = entry.actor == ego and counts[index] < k
        for ai, child in enumerate(entry.children):
            reach[child] = reach[index] if controlled else reach[index] * tree.policy[index][ai]
    values, policies = {}, {}
    for index in reversed(order):
        entry = tree.entries[index]
        if entry.actor is None:
            values[index] = entry.payoff[:, ego]
            continue
        av = np.stack([values[child] for child in entry.children])
        if entry.actor == ego and counts[index] < k:
            probs = np.zeros_like(tree.policy[index])
            for ids in _groups(tree, index, ego, None):
                masses = reach[index][ids]
                q = av[:, ids] @ (masses / masses.sum()) if masses.sum() else np.zeros(len(entry.actions))
                ai = int(np.argmax(q) if maximize else np.argmin(q))
                probs[ai, ids] = 1
            policies[index] = probs
        else:
            probs = tree.policy[index]
        values[index] = np.einsum('aw,aw->w', probs, av)
    return dict(value=float(weights @ values[root]),
                root_Q=[float(weights @ values[c]) for c in tree.entries[root].children], policy=policies)


def window_values(tree, ego, root, weights, k):
    best = extreme_value(tree, ego, root, weights, k)
    worst = extreme_value(tree, ego, root, weights, k, maximize=False)
    return dict(V_star=best['value'], V_min=worst['value'],
                C_span=max(0.0, best['value'] - worst['value']), root_Q=best['root_Q'])


def cached_extreme_value(tree,ego,root,weights,k,maximize=True,cache=None):
    """Same exact terminal values; reuse fixed-profile tails after the window.

    Tail tables are lazy and depend on player/reference, never on the sampled
    hidden world or entrance posterior. The caller's cache must be scoped to
    this immutable reference. The exhaustive implementation above is retained
    as an independent CPU audit, including tied-action semantics.
    """
    if k<1 or tree.entries[root].actor!=ego:
        raise ValueError('A positive ego-decision window is required')
    weights=_root_weights(tree,root,weights)
    if sum(weights[ids].sum()>0 for ids in _groups(tree,root,ego,None))!=1:
        raise ValueError('Entrance must be one player information set')
    cache={} if cache is None else cache
    key=('frozen-terminal-tail-v1',ego)
    table=cache.get(key)
    if table is None:
        table=(np.empty((len(tree.entries),tree.w)),np.zeros(len(tree.entries),dtype=bool))
        cache[key]=table
    tails,known=table
    computed=0
    def reference_value(start):
        nonlocal computed
        pending=[(start,False)]
        while pending:
            index,expanded=pending.pop()
            if known[index]:continue
            entry=tree.entries[index]
            if entry.actor is None:tails[index]=entry.payoff[:,ego]
            elif not expanded:
                pending.append((index,True));pending.extend((c,False) for c in entry.children if not known[c]);continue
            else:
                tails[index]=np.einsum('aw,aw->w',tree.policy[index],np.stack([tails[c] for c in entry.children]))
            known[index]=True;computed+=1
        return tails[start]
    order=[];counts={root:0};reach={root:weights};pending=[root]
    while pending:
        index=pending.pop();order.append(index);entry=tree.entries[index]
        if entry.actor is None or counts[index]>=k:continue
        controlled=entry.actor==ego
        for ai,child in enumerate(entry.children):
            if child in counts:raise ValueError('Expected a tree, not a shared-node graph')
            counts[child]=counts[index]+int(controlled)
            reach[child]=reach[index] if controlled else reach[index]*tree.policy[index][ai]
            pending.append(child)
    values={};policies={}
    for index in reversed(order):
        entry=tree.entries[index]
        if entry.actor is None or counts[index]>=k:
            values[index]=reference_value(index);continue
        av=np.stack([values[c] for c in entry.children])
        if entry.actor==ego:
            probs=np.zeros_like(tree.policy[index])
            for ids in _groups(tree,index,ego,None):
                masses=reach[index][ids]
                q=av[:,ids]@(masses/masses.sum()) if masses.sum() else np.zeros(len(entry.actions))
                ai=int(np.argmax(q) if maximize else np.argmin(q));probs[ai,ids]=1
            policies[index]=probs
        else:probs=tree.policy[index]
        values[index]=np.einsum('aw,aw->w',probs,av)
    return dict(value=float(weights@values[root]),root_Q=[float(weights@values[c]) for c in tree.entries[root].children],
        policy=policies,window_nodes=len(order),tail_nodes_computed=computed)
