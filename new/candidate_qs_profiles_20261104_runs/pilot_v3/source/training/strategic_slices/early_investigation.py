"""Full-terminal investigation diagnostics at every player's first proposal.

Partners retain the saved initial oracle. Focal best responses optimize ALL
remaining decisions, including responses, with the native information partition.
No equilibrium search, horizon cutoff, or changed payoffs are used.
"""
import numpy as np

from .common import digest
from .oracle_consistent import oracle_reach
from training.b_sft.social_private_teacher import observed_slots


def terminal_response_values(tree, ego, *, forbid_queries=False):
    """World values of a full contingent BR, using counterfactual own reach.

    Forbidding queries removes them at every future own decision, not only the
    entrance. Histories still reveal partner behavior; partners may investigate.
    Zero counterfactual cells use the declared prior/own-information convention.
    """
    reach = [None]*len(tree.entries)
    reach[0] = tree.world_weights.copy()
    for i, entry in enumerate(tree.entries):
        for a, child in enumerate(entry.children):
            reach[child] = reach[i] if entry.actor == ego else reach[i]*tree.policy[i][a]
    values = [None]*len(tree.entries)
    for i in range(len(tree.entries)-1, -1, -1):
        entry = tree.entries[i]
        if entry.actor is None:
            values[i] = entry.payoff[:, ego]
            continue
        av = np.stack([values[ch] for ch in entry.children])
        if entry.actor != ego:
            values[i] = np.einsum('aw,aw->w', tree.policy[i], av)
            continue
        allowed = [a for a, action in enumerate(entry.actions)
                   if not forbid_queries or action.to_dict().get('action') != 'INVESTIGATE']
        if not allowed:
            raise ValueError('Query prohibition removed every legal action')
        values[i] = np.zeros(tree.w)
        for ids in tree.information_groups[i]:
            mass = reach[i][ids]
            if mass.sum() <= 0:
                mass = tree.world_weights[ids]
            q = av[np.ix_(allowed, ids)] @ (mass/mass.sum())
            chosen = allowed[int(np.argmax(q))]
            values[i][ids] = av[chosen, ids]
    return values


def measure_early_investigation(tree, parent_id, tolerance=1e-8):
    schedule = list(tree.rules.spec.round_robin)
    reach, histories = oracle_reach(tree)
    frozen = tree.evaluate()
    rows = []
    for ego in range(tree.n):
        first = schedule.index(ego)
        roots = [i for i in reach if tree.entries[i].actor == ego
                 and tree.entries[i].node.pending is None
                 and tree.entries[i].node.state.turn_index == first]
        full = terminal_response_values(tree, ego)
        prohibited = terminal_response_values(tree, ego, forbid_queries=True)
        for root in roots:
            entry = tree.entries[root]
            actions = [a.to_dict() for a in entry.actions]
            queries = [i for i, a in enumerate(actions) if a.get('action') == 'INVESTIGATE']
            other = [i for i in range(len(actions)) if i not in queries]
            if not queries or observed_slots(entry.node, ego):
                raise ValueError('Expected an unused investigation budget at first proposal')
            for ids in tree.information_groups[root]:
                masses = np.zeros(tree.w); masses[ids] = reach[root][ids]
                mass = float(masses.sum())
                if mass <= 1e-10:
                    continue
                posterior = masses/mass
                q = np.array([posterior @ full[ch] for ch in entry.children])
                nq = np.array([posterior @ prohibited[ch] for ch in entry.children])
                fq = np.array([posterior @ frozen[ch][:, ego] for ch in entry.children])
                best_query = float(q[queries].max()); best_other = float(q[other].max())
                no_queries = float(nq[other].max()); optimum = float(q.max())
                if no_queries > optimum+tolerance:
                    raise AssertionError('Forbidding information acquisition increased value')
                own = list(tree.worlds[int(ids[0])][ego])
                eid = digest((parent_id, root, ego, own, []))[:24]
                query_details = []
                for ai in queries:
                    action = actions[ai]; p, g = action['player'], action['goal']
                    support = sorted({tree.worlds[wi][p][g] for wi in np.flatnonzero(posterior > 0)})
                    query_details.append(dict(action_index=ai, slot=[p, g], answer_support=support,
                                              informative=len(support)>1, Q=float(q[ai])))
                delta = best_query-best_other
                reference_value = float(posterior @ frozen[root][:, ego])
                if abs(optimum-reference_value) > 1e-7:
                    raise AssertionError('Reachable best response disagrees with certified reference')
                rows.append(dict(id=eid, parent_id=parent_id, ego=ego, root_index=root,
                    history=histories[root], own=own, world_weights=posterior.tolist(),
                    oracle_information_set_mass=mass, proposal_turn_index=first,
                    remaining_proposals=len(schedule)-first,
                    own_proposals_after_investigation=schedule[first+1:].count(ego),
                    omitted_by_three_proposal_neighborhood=len(schedule)-first>3,
                    full_terminal_best_response=True, actions=actions, root_Q=q.tolist(),
                    frozen_continuation_root_Q=fq.tolist(), reference_value=reference_value,
                    V_full=optimum, V_no_own_queries=no_queries,
                    query_access_value=max(0., optimum-no_queries),
                    best_query_value=best_query, best_nonquery_value=best_other,
                    delta_investigate=delta,
                    classification='strict_query_advantage' if delta>tolerance else
                        'tie' if delta>=-tolerance else 'query_inferior',
                    best_query_indices=[i for i in queries if q[i]>=best_query-tolerance],
                    best_nonquery_indices=[i for i in other if q[i]>=best_other-tolerance],
                    query_details=query_details,
                    reference_query_probability=float(posterior @ tree.policy[root][queries].sum(axis=0)),
                    maximum_root_Q_change_from_reoptimizing=float(np.max(np.abs(q-fq)))))
    return rows
