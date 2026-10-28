"""Value of private answers already available at an oracle-reachable entrance.

This is a collective, one-decision information contrast, not the value of
buying an investigation. Public history, own type, all other private answers,
and the terminal continuation profile are held fixed. The hidden-answer agent
chooses one action for the conditional mixture; the informed agent may choose
an action for each answer. No posterior is invented or reset.
"""
from collections import defaultdict
from itertools import combinations

import numpy as np

from training.b_sft.social_private_teacher import observed_slots
from .common import digest, stable
from .oracle_consistent import oracle_reach


def action_information_value(q, probabilities, epsilon=.1):
    """Enumerate a shared action menu; downstream behavior is already in Q."""
    q = np.asarray(q, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if (q.ndim != 2 or min(q.shape) < 1 or p.shape != (len(q),)
            or not np.isfinite(q).all() or not np.isfinite(p).all()
            or (p <= 0).any() or abs(p.sum()-1) > 1e-9 or epsilon < 0):
        raise ValueError('Expected finite action values and normalized positive masses')
    best = q.max(axis=1)
    accepted = [np.flatnonzero(best[i]-row <= epsilon+1e-9).tolist()
                for i, row in enumerate(q)]
    must_change = [[a, b] for a, b in combinations(range(len(q)), 2)
                   if set(accepted[a]).isdisjoint(accepted[b])]
    full = float(p @ best)
    blind = float((p @ q).max())
    return dict(V_full=full, V_masked=blind, S=max(0., full-blind),
                acceptable_indices=accepted, must_change_pairs=must_change,
                epsilon=epsilon, masked_optimal_indices=np.flatnonzero(
                    blind-p @ q <= 1e-9).tolist())


def measure_entry_answers(tree, parent_id, epsilon=.1):
    """Exhaust all reachable 1--3-proposal entrances, without the 24-entry cap.

    One group is one public node / own type / other-answer cell. Its members
    differ only in the selected answer. Conditional masses come from the saved
    initial oracle's reach. k=1 freezes *all* decisions after the chosen action,
    so the same per-world terminal payoff table applies to every member.
    """
    reach, histories = oracle_reach(tree)
    terminal_values = tree.evaluate()
    groups = []
    total = len(tree.rules.spec.round_robin)
    for root, masses in reach.items():
        entry = tree.entries[root]
        ego = entry.actor
        remaining = total-entry.node.state.turn_index
        if ego is None or not 1 <= remaining <= 3:
            continue
        slots = sorted(set(observed_slots(entry.node, ego)))
        if not slots:
            continue
        payoffs = np.stack([terminal_values[ch][:, ego] for ch in entry.children])
        for slot in slots:
            cells = defaultdict(lambda: defaultdict(list))
            for wi in np.flatnonzero(masses > 0):
                world = tree.worlds[wi]
                key = stable((world[ego], [(p, g, world[p][g]) for p, g in slots if (p, g) != slot]))
                cells[key][world[slot[0]][slot[1]]].append(int(wi))
            for key, answers in sorted(cells.items()):
                if len(answers) < 2:
                    continue
                group_mass = float(sum(masses[ids].sum() for ids in answers.values()))
                if group_mass <= 1e-10:
                    continue
                members = []
                for answer, ids in sorted(answers.items()):
                    joint = np.zeros(tree.w)
                    joint[ids] = masses[ids]
                    mass = float(joint.sum())
                    posterior = joint/mass
                    world = tree.worlds[ids[0]]
                    private = [(p, g, world[p][g]) for p, g in slots]
                    eid = digest((parent_id, root, ego, list(world[ego]), private))[:24]
                    q = payoffs @ posterior
                    members.append(dict(entrance_id=eid, candidate_id=digest((eid, 1))[:24],
                        answer=int(answer), root_index=root, history=histories[root],
                        own=list(world[ego]), private_results=private,
                        world_weights=posterior.tolist(),
                        joint_world_masses=(joint/group_mass).tolist(),
                        probability=mass/group_mass, oracle_information_set_mass=mass,
                        root_Q=q.tolist(), V_star=float(q.max()), V_min=float(q.min()),
                        C_span=float(q.max()-q.min()), remaining_proposals=remaining))
                metric = action_information_value([m['root_Q'] for m in members],
                                                   [m['probability'] for m in members], epsilon)
                gid = digest((parent_id, root, slot, key, 'entry-private-answer-k1-v1'))[:24]
                groups.append(dict(id=gid, parent_id=parent_id, root_index=root, ego=ego, k=1,
                    query_slot=list(slot), channel='entry_private_answer',
                    group_reach_probability=group_mass, members=members,
                    actions=[a.to_dict() for a in entry.actions],
                    decision_kind='response' if entry.node.pending is not None else 'proposal',
                    fixed_continuation_payoffs_match=True, **metric))
    return groups
