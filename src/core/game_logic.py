"""
game_logic.py

Core game logic for negotiation simulations.

Provides the fundamental mechanics for computing goal satisfaction, player
payoffs, feasible actions, and offer generation.
"""

import itertools

import numpy as np


def get_goal_satisfaction(P, sat_masks, binary_goals=None):
    """
    Compute the satisfaction level for each goal given a policy matrix.

    For continuous goals, satisfaction is the fraction of required actions that
    are active. For binary goals, satisfaction is 1.0 only if all required
    actions are active, and 0.0 otherwise.

    Args:
        P (np.ndarray): Policy matrix of shape (N_PLAYERS, N_ACTIONS) with
            binary entries.
        sat_masks (dict): Maps each goal index to a binary mask of the same
            shape as P, indicating which actions contribute to that goal.
        binary_goals (set, optional): Set of goal indices treated as binary
            (all-or-nothing). Defaults to an empty set.

    Returns:
        np.ndarray: Goal satisfaction vector of shape (N_GOALS,) with values
            in [0, 1].

    Raises:
        ValueError: If any goal's mask has no active requirements (sum == 0).
    """

    if binary_goals is None:
        binary_goals = set()

    n_goals = len(sat_masks)
    s = np.empty(n_goals, dtype=float)

    for j in range(n_goals):
        mask = sat_masks[j]
        denom = int(mask.sum())
        num = int(np.count_nonzero(P & mask))  # count cells where both are 1

        if denom == 0:
            raise ValueError(f"Goal {j} has no requirements for satisfaction")

        if j in binary_goals:
            s[j] = 1.0 if num == denom else 0.0
        else:
            s[j] = num / denom

    return s


def get_payoff_per_country(P, G, sat_masks, binary_goals=None):
    """
    Compute the payoff for each player given a policy matrix.

    Payoffs are calculated as the dot product of the goal satisfaction vector
    and the goal valuation matrix G.

    Args:
        P (np.ndarray): Policy matrix of shape (N_PLAYERS, N_ACTIONS).
        G (np.ndarray): Goal valuation matrix of shape (N_GOALS, N_PLAYERS),
            where G[j, i] is player i's valuation of goal j.
        sat_masks (dict): Maps each goal index to a binary satisfaction mask.
        binary_goals (set, optional): Goal indices treated as binary. Defaults
            to an empty set.

    Returns:
        np.ndarray: Payoff vector of shape (N_PLAYERS,).
    """
    goal_satisfaction = get_goal_satisfaction(P, sat_masks, binary_goals)

    return goal_satisfaction @ G


def deltas_for_target_reward(G, sat_masks, target_idx):
    """
    Compute the per-action payoff delta for a target player under the reward
    objective.

    Each entry (i, a) in the returned matrix represents how much player
    target_idx's payoff increases if action a of player i is flipped from 0
    to 1, assuming all goals are continuous.

    Args:
        G (np.ndarray): Goal valuation matrix of shape (N_GOALS, N_PLAYERS).
        sat_masks (dict): Maps each goal index to a binary satisfaction mask.
        target_idx (int): Index of the player whose payoff delta is computed.

    Returns:
        np.ndarray: Delta matrix of shape (N_PLAYERS, N_ACTIONS).
    """
    N = G.shape[1]
    A = next(iter(sat_masks.values())).shape[1]
    delta = np.zeros((N, A), dtype=float)
    for j, M in sat_masks.items():
        denom = float(M.sum())
        if denom > 0:
            delta += (G[j, target_idx] / denom) * M
    return delta


def deltas_for_target_linear(G, sat_masks, target_idx, how: str):
    """
    Compute per-action payoff deltas for a target player using a specified
    objective type.

    Currently supports only the "reward" objective. Additional objective types
    may be added by extending this function.

    Args:
        G (np.ndarray): Goal valuation matrix of shape (N_GOALS, N_PLAYERS).
        sat_masks (dict): Maps each goal index to a binary satisfaction mask.
        target_idx (int): Index of the player whose payoff delta is computed.
        how (str): Objective type. Currently only "reward" is supported.

    Returns:
        np.ndarray: Delta matrix of shape (N_PLAYERS, N_ACTIONS).

    Raises:
        ValueError: If an unsupported objective type is specified.
    """
    if how == "reward":
        return deltas_for_target_reward(G, sat_masks, target_idx)

    raise ValueError(f"Unknown 'how': {how}")


def best_offer_linear_greedy(
    state,
    partner,
    max_changes,
    how="reward",
    allowed_actions=None,
    forbidden_actions=None,
    eps=1e-12,
):
    """
    Find the best bilateral offer using a greedy linear heuristic.

    The proposer selects actions that maximise their own payoff gain while
    satisfying the partner's acceptance constraint (non-negative utility
    change). Actions are binding: bits can only go from 0 to 1.

    The algorithm first greedily selects the top payoff-improving actions for
    each side, then iteratively adds "sweeteners" or removes harmful actions
    to cover any acceptance deficit, using a cost-per-relief ratio to guide
    each step.

    Args:
        state (NegotiationState): Current game state.
        partner (int): Index of the partner player.
        max_changes (int): Maximum number of actions each player may flip.
        how (str): Objective type passed to the delta computation. Defaults
            to "reward".
        allowed_actions (np.ndarray, optional): Binary mask of shape
            (N_PLAYERS, N_ACTIONS) indicating permitted actions.
        forbidden_actions (np.ndarray, optional): Binary mask of shape
            (N_PLAYERS, N_ACTIONS) indicating forbidden actions.
        eps (float): Tolerance for the acceptance deficit loop. Defaults to
            1e-12.

    Returns:
        tuple:
            - offer (tuple or None): Joint action as a concatenated integer
              tuple, or None if no acceptable offer exists.
            - v_gain (float): Proposer's expected payoff gain from the offer,
              or 0.0 if no offer is found.
    """

    p, q = state.proposer(), partner
    m_p, m_q = state.country_idx2num_actions[p], state.country_idx2num_actions[q]
    base_p, base_q = state.P[p, :m_p].copy(), state.P[q, :m_q].copy()

    ok_p = base_p == 0
    ok_q = base_q == 0
    if allowed_actions is not None:
        ok_p &= allowed_actions[p, :m_p] == 1
        ok_q &= allowed_actions[q, :m_q] == 1
    if forbidden_actions is not None:
        ok_p &= forbidden_actions[p, :m_p] == 0
        ok_q &= forbidden_actions[q, :m_q] == 0

    if p == q:
        # Self-negotiation: Force the 'partner' side to be empty.
        # This prevents double-counting the proposer's budget and score.
        ok_q[:] = False

    idxP, idxQ = np.flatnonzero(ok_p), np.flatnonzero(ok_q)
    if idxP.size == 0 and idxQ.size == 0:
        return None, 0.0

    # per-bit deltas: proposer objective v (target = p), proposee acceptance u (target = q)
    delta_p, delta_q = (
        deltas_for_target_linear(state.G, state.sat_masks, p, how),
        deltas_for_target_linear(state.G, state.sat_masks, q, how),
    )
    vP, uP = delta_p[p, idxP], delta_q[p, idxP]
    vQ, uQ = delta_p[q, idxQ], delta_q[q, idxQ]

    # 1) take top positive-Δv up to k per side
    selP = list(np.argsort(-vP[vP > 0.0])[:max_changes])
    mapP = np.flatnonzero(vP > 0.0)
    selP = list(mapP[selP]) if selP else []
    selQ = list(np.argsort(-vQ[vQ > 0.0])[:max_changes])
    mapQ = np.flatnonzero(vQ > 0.0)
    selQ = list(mapQ[selQ]) if selQ else []

    def u_sum():
        return (uP[selP].sum() if selP else 0.0) + (uQ[selQ].sum() if selQ else 0.0)

    def v_sum():
        return (vP[selP].sum() if selP else 0.0) + (vQ[selQ].sum() if selQ else 0.0)

    if u_sum() >= 0.0:  # acceptance met
        a_p, a_q = base_p.copy(), base_q.copy()
        if selP:
            a_p[idxP[selP]] = 1
        if selQ:
            a_q[idxQ[selQ]] = 1
        return tuple(map(int, a_p.tolist() + a_q.tolist())), float(v_sum())

    # 2) cover acceptance deficit by cheapest moves (add sweeteners / remove harmful)
    # candidates to ADD: not chosen & u>0 ; ratio ρ = -Δv/Δu
    poolP_add = [i for i in range(len(vP)) if (i not in selP) and (uP[i] > 0)]
    poolQ_add = [i for i in range(len(vQ)) if (i not in selQ) and (uQ[i] > 0)]
    poolP_add.sort(key=lambda i: (-vP[i]) / uP[i])
    poolQ_add.sort(key=lambda i: (-vQ[i]) / uQ[i])

    # candidates to REMOVE: chosen & u<0 ; ratio ρ =  Δv/(-Δu)
    poolP_rem = [i for i in selP if uP[i] < 0]
    poolP_rem.sort(key=lambda i: vP[i] / (-uP[i]))
    poolQ_rem = [i for i in selQ if uQ[i] < 0]
    poolQ_rem.sort(key=lambda i: vQ[i] / (-uQ[i]))

    deficit = -u_sum()
    while deficit > eps:
        moved = False
        # try adding sweetener on side with capacity; pick smaller ρ
        cand = []
        if len(selP) < max_changes and poolP_add:
            i = poolP_add[0]
            cand.append(((-vP[i]) / uP[i], "addP", i))
        if len(selQ) < max_changes and poolQ_add:
            i = poolQ_add[0]
            cand.append(((-vQ[i]) / uQ[i], "addQ", i))
        cand.sort()
        if cand:
            _, which, i = cand[0]
            if which == "addP":
                selP.append(poolP_add.pop(0))
                deficit -= uP[i]
            else:
                selQ.append(poolQ_add.pop(0))
                deficit -= uQ[i]
            moved = True
        else:
            # remove a harmful chosen bit with smallest cost-per-relief
            cand = []
            if poolP_rem:
                cand.append((vP[poolP_rem[0]] / (-uP[poolP_rem[0]]), "remP"))
            if poolQ_rem:
                cand.append((vQ[poolQ_rem[0]] / (-uQ[poolQ_rem[0]]), "remQ"))
            cand.sort()
            if cand:
                which = cand[0][1]
                if which == "remP":
                    i = poolP_rem.pop(0)
                    selP.remove(i)
                    deficit -= -uP[i]
                else:
                    i = poolQ_rem.pop(0)
                    selQ.remove(i)
                    deficit -= -uQ[i]
                moved = True
        if not moved:  # cannot satisfy acceptance
            return None, 0.0

    a_p, a_q = base_p.copy(), base_q.copy()
    if selP:
        a_p[idxP[selP]] = 1
    if selQ:
        a_q[idxQ[selQ]] = 1
    return tuple(map(int, a_p.tolist() + a_q.tolist())), float(v_sum())


def actions_with_max_changes(base_action, max_changes, allowed_mask, forbidden_mask):
    """
    Generate all valid actions reachable within a given number of bit flips.

    Actions are binding: bits can only transition from 0 to 1, never from
    1 to 0. The base action (no change) is always included in the result.

    Args:
        base_action (array-like): Current binary action vector.
        max_changes (int): Maximum number of 0→1 flips allowed.
        allowed_mask (array-like or None): Binary mask of permitted flip
            positions. If None, all zero positions are eligible.
        forbidden_mask (array-like or None): Binary mask of forbidden flip
            positions. If None, no positions are excluded.

    Returns:
        list: Sorted list of action tuples, each of the same length as
            base_action.
    """
    base = tuple(int(x) for x in base_action)
    L = len(base)
    results = {base}  # include 0-change (no-op)

    # print(f"base_action: {base}, max_changes: {max_changes}")

    # Find positions where bits are currently 0 (can be flipped to 1)
    zero_positions = [i for i in range(L) if base[i] == 0]

    # print(f"zero_positions: {zero_positions}")
    # print(f"allowed_mask: {allowed_mask}")

    if allowed_mask is not None:
        zero_positions = [i for i in zero_positions if allowed_mask[i] == 1]

    if forbidden_mask is not None:
        zero_positions = [i for i in zero_positions if forbidden_mask[i] == 0]

    # print(f"zero_positions after applying allowed_mask: {zero_positions}")

    # Can only change as many bits as there are zeros
    max_k = min(max_changes, len(zero_positions))

    for k in range(1, max_k + 1):
        for flip_positions in itertools.combinations(zero_positions, k):
            a = list(base)
            # print(f"flipping positions: {flip_positions}")
            for j in flip_positions:
                a[j] = 1  # flip 0→1 only
            results.add(tuple(a))

    # print(f"results: {results}")

    return sorted(results)


def get_all_joint_actions(
    P, p1, p2, country_idx2num_actions, max_changes, allowed_actions, forbidden_actions
):
    """
    Generate all joint actions for two players within the max_changes budget.

    Actions are binding: bits can only go from 0 to 1. When p1 == p2
    (self-negotiation), the second player's contribution is fixed at all
    zeros to avoid double-counting.

    Args:
        P (np.ndarray): Current policy matrix of shape (N_PLAYERS, N_ACTIONS).
        p1 (int): Index of the first player (proposer).
        p2 (int): Index of the second player (partner).
        country_idx2num_actions (dict): Maps each player index to their number
            of available actions.
        max_changes (int): Maximum number of 0→1 flips allowed per player.
        allowed_actions (np.ndarray or None): Binary mask of shape
            (N_PLAYERS, N_ACTIONS) for permitted actions.
        forbidden_actions (np.ndarray or None): Binary mask of shape
            (N_PLAYERS, N_ACTIONS) for forbidden actions.

    Returns:
        list: List of joint action tuples formed by concatenating each player's
            individual action tuple.

    Raises:
        ValueError: If the initial policy is all zeros and any player's action
            exceeds the max_changes budget.
    """

    m1 = country_idx2num_actions[p1]
    m2 = country_idx2num_actions[p2]

    # Current (base) actions for each player
    base1 = P[p1, :m1]
    base2 = P[p2, :m2]

    allowed_mask1 = allowed_actions[p1, :m1] if allowed_actions is not None else None
    allowed_mask2 = allowed_actions[p2, :m2] if allowed_actions is not None else None

    forbidden_mask1 = (
        forbidden_actions[p1, :m1] if forbidden_actions is not None else None
    )
    forbidden_mask2 = (
        forbidden_actions[p2, :m2] if forbidden_actions is not None else None
    )

    player1_actions = actions_with_max_changes(
        base1, max_changes, allowed_mask1, forbidden_mask1
    )

    if p1 == p2:
        zero_action = tuple([0] * m1)
        joint_actions = []
        for a1 in player1_actions:
            joint_actions.append(a1 + zero_action)
        return joint_actions

    player2_actions = actions_with_max_changes(
        base2, max_changes, allowed_mask2, forbidden_mask2
    )

    joint_actions = []
    for a1 in player1_actions:
        for a2 in player2_actions:
            if np.all(P == 0):
                if sum(a1) > max_changes or sum(a2) > max_changes:
                    raise ValueError(
                        "Initial action cannot have more than max_changes bits set to 1."
                    )
            joint_actions.append(a1 + a2)  # concatenate tuples

    return joint_actions


def apply_action(P, joint_action, p1, p2, country_idx2num_actions):
    """
    Apply a joint action to the policy matrix in-place.

    Actions are binding: existing 1s are preserved and only 0→1 transitions
    are permitted. The operation is equivalent to a bitwise OR of the current
    row and the proposed action for each player.

    Args:
        P (np.ndarray): Policy matrix of shape (N_PLAYERS, N_ACTIONS) to
            modify in-place.
        joint_action (tuple or None): Concatenated binary action for p1
            followed by p2. If None, P is returned unchanged.
        p1 (int): Index of the first player.
        p2 (int): Index of the second player.
        country_idx2num_actions (dict): Maps each player index to their number
            of available actions.

    Returns:
        np.ndarray: The modified policy matrix (same object as the input P).

    Raises:
        ValueError: If the joint action length does not match the expected
            number of actions for each player.
    """

    if joint_action is None:
        return P

    m1 = country_idx2num_actions[p1]
    m2 = country_idx2num_actions[p2]

    p1_action = joint_action[:m1]
    p2_action = joint_action[m1:]

    if len(p1_action) != m1 or len(p2_action) != m2:
        raise ValueError(
            f"Joint action length does not match number of actions per player, p1_action: {p1_action}, p2_action:"
            f"{p2_action}, len(p1_action): {len(p1_action)}, len(p2_action): {len(p2_action)}, m1: {m1}, m2: {m2}"
            f"Proposer: {p1}, Proposee: {p2}"
            f"Joint action: {joint_action}"
        )

    # Apply binding constraint: keep existing 1s, only allow 0->1
    P[p1, :m1] = np.maximum(P[p1, :m1], p1_action)
    P[p2, :m2] = np.maximum(P[p2, :m2], p2_action)

    return P
