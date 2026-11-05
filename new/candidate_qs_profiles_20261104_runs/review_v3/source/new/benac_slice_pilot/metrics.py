"""Exact fixed-partner values for a bounded ego-controlled game slice.

The native PrivateWindow is a complete terminal tree.  This module freezes its
selected policy for the other player (and for ego after ``k`` ego decisions),
then computes an exact contingent best response for ego's controlled decisions.
``masked_slot`` removes just one private query answer from ego's information
partition; the public tree, physical query, other private answers, chance
revelations, and the partner's policy are identical in both comparisons.

Values are relative to the selected oracle profile, not to every equilibrium.
The masking comparison starts *before* the selected answer is observed.  With
``k`` shorter than the remaining game, frozen oracle ego continuation can still
use that answer after the controlled window; S therefore measures the value of
the answer within the controlled window, given that continuation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

import numpy as np

from training.b_sft.social_private_teacher import observed_slots


_NUMERIC_TOL = 1e-9


def _tree(episode):
    tree = episode.tree if hasattr(episode, "tree") else episode
    if not tree.certificate or not tree.certificate.get("verified"):
        raise ValueError("A solved and certified PrivateWindow is required")
    if not hasattr(tree, "information_groups") or not hasattr(tree, "worlds"):
        raise TypeError("Expected a solved PrivateEpisode or PrivateWindow")
    return tree


def _slot(tree, ego: int, slot: tuple[int, int] | None) -> None:
    if slot is None:
        return
    if (
        not isinstance(slot, tuple)
        or len(slot) != 2
        or any(type(x) is not int for x in slot)
        or not (0 <= slot[0] < tree.n)
        or slot[0] == ego
        or not (0 <= slot[1] < len(tree.rules.spec.goals))
    ):
        raise ValueError("masked_slot must be a valid (other_player, goal) query")


def _groups(tree, node_index: int, ego: int, masked_slot: tuple[int, int] | None):
    """Information cells at one public history; that history includes own acts."""
    slots = observed_slots(tree.entries[node_index].node, ego)
    if masked_slot is not None:
        slots = tuple(slot for slot in slots if slot != masked_slot)
    groups = defaultdict(list)
    for wi, world in enumerate(tree.worlds):
        key = (world[ego], tuple(world[player][goal] for player, goal in slots))
        groups[key].append(wi)
    return tuple(np.asarray(ids, dtype=int) for ids in groups.values())


def _root_weights(tree, root_index: int, weights: Sequence[float]) -> np.ndarray:
    result = np.asarray(weights, dtype=float)
    if (
        result.shape != (len(tree.worlds),)
        or not np.all(np.isfinite(result))
        or np.any(result < 0)
        or result.sum() <= 0
    ):
        raise ValueError("root_weights must be nonnegative finite world masses")
    possible = set(tree.entries[root_index].node.worlds)
    if any(weight > 0 and world not in possible for weight, world in zip(result, tree.worlds)):
        raise ValueError("root_weights include a world ruled out by public history")
    return result / result.sum()


def _subtree(tree, root_index: int, ego: int):
    """Return descendants and the number of previous ego acts since root."""
    counts = {root_index: 0}
    order = []
    pending = [root_index]
    while pending:
        index = pending.pop()
        order.append(index)
        entry = tree.entries[index]
        for child in entry.children:
            if child in counts:
                raise ValueError("Expected a tree, not a shared-node graph")
            counts[child] = counts[index] + int(entry.actor == ego)
            pending.append(child)
    return order, counts


def optimal_value(
    episode,
    *,
    ego: int,
    root_index: int,
    root_weights: Sequence[float],
    k: int,
    masked_slot: tuple[int, int] | None = None,
) -> dict:
    """Optimize ego's next ``k`` decisions against the frozen partner policy.

    ``root_weights`` must describe one ego information cell: condition the
    public prior on ego's own type and already known private results, but not
    on future private answers.  All public and chance branches remain in the
    calculation.  The returned policy maps each controlled ego node index to
    an ``(actions, worlds)`` probability array.  ``root_action_values`` forces
    each root action and uses the optimized policy at later ego decisions;
    this is the one-decision C vector when ``k == 1``.

    Root action values are in ego's terminal-utility units.  Unreachable
    information cells choose action 0 by convention; their choice cannot
    change the returned value.  No LM or realized-world truth enters.
    """
    tree = _tree(episode)
    if type(ego) is not int or not (0 <= ego < tree.n):
        raise ValueError("ego must be a player index")
    if type(root_index) is not int or not (0 <= root_index < len(tree.entries)):
        raise ValueError("Invalid root_index")
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive ego-decision horizon")
    _slot(tree, ego, masked_slot)
    root = tree.entries[root_index]
    if root.actor != ego:
        raise ValueError("Slice root must be an ego decision")
    weights = _root_weights(tree, root_index, root_weights)
    active_root_cells = sum(bool(weights[ids].sum()) for ids in _groups(tree, root_index, ego, masked_slot))
    if active_root_cells != 1:
        raise ValueError("root_weights must condition on one ego information cell")

    order, previous_ego_acts = _subtree(tree, root_index, ego)
    reach = {root_index: weights}
    for index in order:
        entry = tree.entries[index]
        if entry.actor is None:
            continue
        controlled = entry.actor == ego and previous_ego_acts[index] < k
        frozen = None if controlled else np.asarray(tree.policy[index], dtype=float)
        for ai, child in enumerate(entry.children):
            # Ignore ego's own controlled action in counterfactual reach.  This
            # is required for a best response at every subsequent information
            # cell, including cells reached after a non-reference first act.
            reach[child] = reach[index].copy() if controlled else reach[index] * frozen[ai]

    world_values = {}
    policy = {}
    for index in reversed(order):
        entry = tree.entries[index]
        if entry.actor is None:
            world_values[index] = np.asarray(entry.payoff, dtype=float).copy()
            continue
        action_values = np.stack([world_values[child] for child in entry.children])
        controlled = entry.actor == ego and previous_ego_acts[index] < k
        if controlled:
            probs = np.zeros((len(entry.actions), len(tree.worlds)), dtype=float)
            for ids in _groups(tree, index, ego, masked_slot):
                masses = reach[index][ids]
                if masses.sum() > 0:
                    own_values = np.einsum(
                        "aw,w->a", action_values[:, ids, ego], masses / masses.sum()
                    )
                    chosen = int(np.argmax(own_values))
                else:
                    chosen = 0
                probs[chosen, ids] = 1.0
            policy[index] = probs
        else:
            probs = np.asarray(tree.policy[index], dtype=float)
        world_values[index] = np.einsum("aw,awp->wp", probs, action_values)

    q = [float(np.dot(weights, world_values[child][:, ego])) for child in root.children]
    value = float(np.dot(weights, world_values[root_index][:, ego]))
    best_q = max(q)
    if not np.isclose(value, best_q, atol=_NUMERIC_TOL, rtol=0):
        raise AssertionError("Root best response does not match its action values")
    return dict(
        value=value,
        root_action_values=q,
        root_action_regrets=[
            0.0 if best_q - q_a <= _NUMERIC_TOL else best_q - q_a for q_a in q
        ],
        root_actions=[action.to_dict() for action in root.actions],
        policy=policy,
        controlled_nodes=len(policy),
        root_index=root_index,
        k=k,
        masked_slot=masked_slot,
        policy_sha256=tree.certificate.get("policy_sha256"),
    )


def masked_answer_value(
    episode,
    *,
    ego: int,
    root_index: int,
    root_weights: Sequence[float],
    query_slot: tuple[int, int],
    k: int,
) -> dict:
    """Ex ante value of allowing ego to use one future private query answer.

    Reject a root after ego has already seen this answer.  The input world
    distribution must be the pre-answer belief; the function cannot recover
    that belief from a realized answer.  ``S >= 0`` follows because the masked
    strategy class is contained in the full-information strategy class while
    the partner policy and continuation are held fixed.
    """
    tree = _tree(episode)
    _slot(tree, ego, query_slot)
    if query_slot in observed_slots(tree.entries[root_index].node, ego):
        raise ValueError("Start before the selected private answer is observed")
    full = optimal_value(
        tree, ego=ego, root_index=root_index, root_weights=root_weights, k=k
    )
    masked = optimal_value(
        tree, ego=ego, root_index=root_index, root_weights=root_weights,
        k=k, masked_slot=query_slot
    )
    delta = full["value"] - masked["value"]
    if delta < -_NUMERIC_TOL:
        raise AssertionError("Masking increased value under a fixed partner")
    return dict(
        V_full=full["value"],
        V_mask=masked["value"],
        S=max(0.0, delta),
        full=full,
        masked=masked,
        query_slot=query_slot,
        k=k,
    )
