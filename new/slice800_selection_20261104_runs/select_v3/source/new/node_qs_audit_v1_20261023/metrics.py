"""Current-information Q and per-item omission, with a frozen opponent profile.

The omitted agent receives observation keys, never true entry indices/beliefs.
Its forest has perfect recall from the entry onwards. Counterfactual prefix
masses treat the focal player's earlier actions as interventions.
"""
from collections import defaultdict
import json

import numpy as np

from training.b_sft.decision_policy import optimal_indices, is_offer_response
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.equilibrium import _reach

TOL = 1e-9
EPS = 1e-8


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def stage(entry):
    return 2*entry.node.state.turn_index + int(entry.node.pending is not None)


class Observations:
    def __init__(self, tree, focal):
        self.tree, self.focal = tree, focal
        self.base, self.slots = {}, {}

    def key(self, index, wi, omitted=None):
        cache = (index, omitted)
        if cache not in self.base:
            entry = self.tree.entries[index]
            state = entry.node.state
            history = [event.to_dict() for event in state.transcript
                       if not (omitted and omitted[0] == 'history'
                               and event.turn_index == omitted[1])]
            # All compulsory current-state facts remain available. Constant
            # rules/goals/public preferences are shared by this entire tree.
            self.base[cache] = stable(dict(turn=state.turn_index,
                commitments=state.snapshot_commitments(),
                query_used=state.query_used, offer_used=state.offer_used,
                pending=None if entry.node.pending is None else entry.node.pending.to_dict(),
                legal=[a.to_dict() for a in entry.actions], history=history))
            self.slots[cache] = tuple(slot for slot in observed_slots(entry.node, self.focal)
                if not (omitted and omitted[0] == 'private' and slot == omitted[1:]))
        world = self.tree.worlds[wi]
        answers = tuple((p, g, world[p][g]) for p, g in self.slots[cache])
        return (self.base[cache], world[self.focal], answers)


def contingent_values(tree, focal, reach=None):
    """Full-information BR at all positive-CF nodes; retain admissible ref ties.

    At zero-CF nodes this uses the existing prior fallback convention. Their
    Q output is separately identified as not a fresh subtree BR certificate.
    """
    reach = _reach(tree, focal) if reach is None else reach
    values = [None]*len(tree.entries)
    for i in reversed(range(len(tree.entries))):
        entry = tree.entries[i]
        if entry.actor is None:
            values[i] = entry.payoff
            continue
        children = np.stack([values[c] for c in entry.children])
        if entry.actor != focal:
            values[i] = np.einsum('aw,awp->wp', tree.policy[i], children)
            continue
        probs = np.zeros_like(tree.policy[i])
        for ids in tree.information_groups[i]:
            weights = reach[i][ids]
            if weights.sum() == 0:
                weights = tree.world_weights[ids]
            means = np.einsum('awp,w->ap', children[:, ids], weights/weights.sum())
            best = optimal_indices(means, focal, entry.actions, TOL)
            p = np.zeros(len(entry.actions))
            p[best] = tree.policy[i][best, ids[0]]
            if p.sum() <= 0:
                p[best] = 1.
            p /= p.sum()
            probs[:, ids] = p[:, None]
        values[i] = np.einsum('aw,awp->wp', probs, children)
    return values


def forest_response(tree, focal, roots, *, omitted=None, observations=None):
    """Solve a fixed-opponent perfect-recall single-player forest exactly by DP.

    roots maps original tree indices to joint entry/world masses, NOT separate
    posteriors. A merged decision uses one distribution for every compatible
    entry/world. Original indices are bookkeeping only, absent from its key.
    A realization sequence in the key prevents forgetting post-entry actions
    or observations. No reference focal-action likelihood enters belief.
    """
    observations = observations or Observations(tree, focal)
    total = sum(float(m.sum()) for m in roots.values())
    if total <= 0:
        raise ValueError('Positive joint forest mass required')
    reach = {i: m.copy()/total for i, m in roots.items()}
    last = {i: np.zeros(tree.w, dtype=int) for i in roots}
    nodes, seen, stack = [], set(), list(roots)
    while stack:
        i = stack.pop()
        if i in seen:
            raise ValueError('Forest roots must have disjoint subtrees')
        seen.add(i); nodes.append(i); stack.extend(tree.entries[i].children)
    order = sorted(nodes, key=lambda i: stage(tree.entries[i]))
    cells, assigned, by_stage = {}, {}, defaultdict(list)
    nseq = 1
    for i in order:
        entry = tree.entries[i]
        by_stage[stage(entry)].append(i)
        if entry.actor is None:
            continue
        for child in entry.children:
            last[child] = last[i].copy()
        if entry.actor == focal:
            for wi in np.flatnonzero(reach[i] > 0):
                key = (int(last[i][wi]), observations.key(i, int(wi), omitted))
                if key not in cells:
                    seqs = tuple(range(nseq, nseq+len(entry.actions)))
                    nseq += len(entry.actions)
                    cells[key] = dict(seqs=seqs, members=[], actions=entry.actions,
                                      stage=stage(entry))
                cell = cells[key]
                assert cell['stage'] == stage(entry)
                assert cell['actions'] == entry.actions
                cell['members'].append((i, int(wi)))
                assigned[i, int(wi)] = key
                for ai, child in enumerate(entry.children):
                    last[child][wi] = cell['seqs'][ai]
        for ai, child in enumerate(entry.children):
            reach[child] = reach[i].copy() if entry.actor == focal else reach[i]*tree.policy[i][ai]
    cells_by_stage = defaultdict(list)
    for cell in cells.values():
        cells_by_stage[cell['stage']].append(cell)
    values, policies = {}, {}
    max_spread = 0.
    for level in sorted(by_stage, reverse=True):
        for i in by_stage[level]:
            entry = tree.entries[i]
            if entry.actor is None:
                values[i] = entry.payoff
            elif entry.actor != focal:
                values[i] = np.einsum('aw,awp->wp', tree.policy[i],
                    np.stack([values[ch] for ch in entry.children]))
            else:
                policies[i] = np.zeros_like(tree.policy[i])
        for cell in cells_by_stage[level]:
            mean = np.zeros((len(cell['actions']), tree.n)); mass = 0.
            for i, wi in cell['members']:
                weight = reach[i][wi]; mass += weight
                mean += weight*np.stack([values[ch][wi] for ch in tree.entries[i].children])
            assert mass > 0
            mean /= mass
            best = optimal_indices(mean, focal, cell['actions'], TOL)
            p = np.zeros(len(cell['actions'])); p[best] = 1./len(best)
            for i, wi in cell['members']:
                policies[i][:, wi] = p
            max_spread = max(max_spread, float(np.ptp([policies[i][0, wi] for i, wi in cell['members']])))
        for i in by_stage[level]:
            if tree.entries[i].actor == focal:
                values[i] = np.einsum('aw,awp->wp', policies[i],
                    np.stack([values[ch] for ch in tree.entries[i].children]))
    # Replay selected policy using a separate native reverse preorder.
    replay = {}
    for i in sorted(nodes, reverse=True):
        entry = tree.entries[i]
        replay[i] = entry.payoff if entry.actor is None else np.einsum('aw,awp->wp',
            policies.get(i, tree.policy[i]), np.stack([replay[ch] for ch in entry.children]))
    for i in roots:
        np.testing.assert_allclose(values[i], replay[i], atol=1e-10, rtol=0)
    return dict(values={i: values[i] for i in roots},
        root_policy={i: policies.get(i) for i in roots}, nodes=len(nodes),
        cells=len(cells), sequences=nseq, shared_policy_spread=max_spread,
        merged_cells=sum(len({i for i, _ in c['members']}) > 1 for c in cells.values()),
        replay_verified=True)


def full_context(tree, i, ids, cf_mass, joint_mass, values, reference_values):
    entry = tree.entries[i]; p = entry.actor
    mass = float(cf_mass[ids].sum())
    weights = cf_mass[ids] if mass > 0 else tree.world_weights[ids]
    posterior = weights/weights.sum()
    means = np.einsum('awp,w->ap', np.stack([values[ch][ids] for ch in entry.children]), posterior)
    ref = np.einsum('awp,w->ap', np.stack([reference_values[ch][ids] for ch in entry.children]), posterior)
    own = means[:, p]; best = optimal_indices(means, p, entry.actions, TOL)
    own_best = np.flatnonzero(own >= own.max()-TOL)
    lower = own[own < own.max()-EPS]
    actions = [a.to_dict() for a in entry.actions]
    query = [a for a, action in enumerate(actions) if action.get('action') == 'INVESTIGATE']
    nonquery = [a for a in range(len(actions)) if a not in query]
    immediate = np.array([posterior@np.einsum('wg,g->w', tree.types[:, p],
        tree.entries[ch].node.state.goal_satisfaction())[ids] for ch in entry.children])
    row = dict(node=i, actor=p, phase='response' if entry.node.pending else 'proposal',
        turn=entry.node.state.turn_index, own_type=list(tree.worlds[ids[0]][p]),
        private_answers=[list((q, g, tree.worlds[ids[0]][q][g])) for q, g in observed_slots(entry.node, p)],
        world_ids=list(map(int, ids)), posterior=posterior.tolist(),
        counterfactual_mass=mass, reference_mass=float(joint_mass[ids].sum()),
        belief='reference_counterfactual' if mass > 0 else 'zero_CF_conditional_prior',
        Q_scope='contingent_BR' if mass > 0 else 'legacy_global_BR_fallback_not_fresh_subtree_optimum',
        actions=actions, Q=own.tolist(), Q_others=(means.sum(axis=1)-own).tolist(),
        Q_reference=ref[:, p].tolist(),
        optimal=list(map(int, best)), own_optimal=list(map(int, own_best)),
        span=float(np.ptp(own)), best_minus_next_distinct=(float(own.max()-lower.max()) if len(lower) else None),
        query_gap=(float(own[query].max()-own[nonquery].max()) if query and nonquery else None),
        immediate_child_utility=immediate.tolist(),
        immediate_optimal_overlap=bool(set(np.flatnonzero(immediate >= immediate.max()-TOL)) & set(best)),
        S_private=None if mass == 0 else 0., S_history=None if mass == 0 else 0.,
        S_items=[], unavailable_S_items=0)
    if entry.node.pending is None:
        offers = []
        for ai, action in enumerate(actions):
            if action['action'] != 'OFFER':
                continue
            response_i = entry.children[ai]; response = tree.entries[response_i]
            ac = next(a for a, x in enumerate(response.actions) if x.to_dict().get('response') == 'ACCEPT')
            re = next(a for a, x in enumerate(response.actions) if x.to_dict().get('response') == 'REJECT')
            accept_probs = tree.policy[response_i][ac, ids]
            qac = float(posterior@values[response.children[ac]][ids, p])
            qre = float(posterior@values[response.children[re]][ids, p])
            offers.append(dict(action=ai, acceptance=float(posterior@accept_probs),
                acceptance_type_range=float(np.ptp(accept_probs[posterior > 0])),
                own_accept_minus_reject=qac-qre,
                Q_accept=qac, Q_reject=qre,
                static_accepted_utility=float(posterior@np.einsum('wg,g->w', tree.types[:, p],
                    tree.entries[response.children[ac]].node.state.goal_satisfaction())[ids])))
        row['offers'] = offers
        if offers:
            static = np.array([x['static_accepted_utility'] for x in offers])
            static_best = {offers[j]['action'] for j in np.flatnonzero(static >= static.max()-TOL)}
            dynamic_best = {x['action'] for x in offers if own[x['action']] >= max(own[y['action']] for y in offers)-TOL}
            row['offer_static_dynamic_disjoint'] = not bool(static_best & dynamic_best)
    return row


def measure(tree):
    """All full-information cells, all identifiable per-item omission forests."""
    reference_values = tree.evaluate()
    joint = [None]*len(tree.entries); joint[0] = tree.world_weights.copy()
    for i, entry in enumerate(tree.entries):
        for ai, child in enumerate(entry.children):
            joint[child] = joint[i]*tree.policy[i][ai]
    rows, count = [], dict(forests=0, forest_nodes=0, nontrivial_forests=0,
        maximum_replay_or_shared_policy_error=0., negative_S_failures=0)
    for focal in range(tree.n):
        reach = _reach(tree, focal)
        values = contingent_values(tree, focal, reach)
        focal_rows = []
        observations = Observations(tree, focal)
        tasks = defaultdict(lambda: defaultdict(list))
        for i, entry in enumerate(tree.entries):
            if entry.actor != focal:
                continue
            for cell, ids in enumerate(tree.information_groups[i]):
                row = full_context(tree, i, ids, reach[i], joint[i], values, reference_values)
                row['cell'] = cell
                focal_rows.append(row)
                masks = [('private', p, g) for p, g in observed_slots(entry.node, focal)]
                masks += [('history', event.turn_index) for event in entry.node.state.transcript]
                if row['counterfactual_mass'] == 0:
                    row['unavailable_S_items'] = len(masks)
                    continue
                for mask in masks:
                    tasks[mask][observations.key(i, int(ids[0]), mask)].append(row)
        for mask, groups in sorted(tasks.items()):
            for members in groups.values():
                count['forests'] += 1
                if len(members) == 1:
                    row = members[0]
                    row['S_items'].append(dict(omitted=list(mask), S=0.,
                        full_contexts=1, note='Retained evidence/support identifies the full entry context'))
                    continue
                roots = {}
                for row in members:
                    i = row['node']; ids = row['world_ids']
                    roots.setdefault(i, np.zeros(tree.w))[ids] = reach[i][ids]
                result = forest_response(tree, focal, roots, omitted=mask, observations=observations)
                count['nontrivial_forests'] += 1
                count['forest_nodes'] += result['nodes']
                count['maximum_replay_or_shared_policy_error'] = max(
                    count['maximum_replay_or_shared_policy_error'], result['shared_policy_spread'])
                group_loss = 0.; group_mass = sum(m.sum() for m in roots.values())
                for row in members:
                    i = row['node']; ids = row['world_ids']; posterior = np.array(row['posterior'])
                    masked = posterior@result['values'][i][ids]
                    own = float(masked[focal]); full = max(row['Q'])
                    loss = full-own
                    if loss < -EPS:
                        raise AssertionError(f'Omission improves own full-information optimum: {loss}, {i}, {mask}')
                    loss = max(0., loss)
                    root_probs = result['root_policy'][i][:, ids[int(np.flatnonzero(posterior > 0)[0])]]
                    item = dict(omitted=list(mask), S=loss, V_full=full, V_omitted=own,
                        omitted_action_probabilities=root_probs.tolist(),
                        full_contexts=len(members), forest_public_roots=len(roots),
                        chosen_probability_outside_full_optimal=float(root_probs[[a for a in range(len(root_probs))
                            if a not in row['optimal']]].sum()),
                        response_secondary_loss=(max(0., max(row['Q_others'][a] for a in row['own_optimal'])
                            -float(masked.sum()-masked[focal]))
                            if row['phase']=='response' and loss <= EPS else None),
                        replay_verified=True)
                    row['S_items'].append(item)
                    channel = 'S_private' if mask[0]=='private' else 'S_history'
                    row[channel] = max(row[channel], loss)
                    group_loss += row['counterfactual_mass']/group_mass*loss
                assert group_loss >= -EPS
        rows.extend(focal_rows)
    rows.sort(key=lambda r:(r['node'], r['cell']))
    return rows, count
