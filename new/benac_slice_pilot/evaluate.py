"""Exact policy evaluation on a solved two-player BENAC private-game tree.

The learner controls its first ``k`` decision opportunities on every branch.
After that, the same selected teacher policy continues to the native terminal.
The opponent always uses that selected policy.  Every expectation is over the
declared entrance belief, not a sampled true world or a recorded oracle path.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np


def expected_utility(
    episode,
    *,
    ego: int,
    root_index: int,
    root_weights,
    k: int,
    controlled_policy: str | Mapping[int, np.ndarray] = "oracle",
) -> float:
    """Evaluate a native policy with exact chance and opponent integration.

    ``controlled_policy`` may be ``oracle``, ``uniform``, ``first`` or a table
    mapping controlled ego node indices to action-by-world probability arrays.
    The latter permits an exact best-response policy from ``metrics.py``.
    """
    tree = episode.tree
    if tree.n != 2:
        raise ValueError("This pilot requires a two-player native game")
    if not 0 <= ego < tree.n or not 0 <= root_index < len(tree.entries):
        raise ValueError("Invalid ego or root")
    if tree.entries[root_index].actor != ego:
        raise ValueError("Slice must begin at an ego decision")
    if k < 1:
        raise ValueError("k must be positive")
    weights = np.asarray(root_weights, dtype=float)
    if weights.shape != (tree.w,) or np.any(weights < 0) or not np.isclose(weights.sum(), 1):
        raise ValueError("Entrance weights must be a normalized world distribution")

    def descend(index: int, ego_decisions: int) -> np.ndarray:
        entry = tree.entries[index]
        if entry.actor is None:
            return np.asarray(entry.payoff, dtype=float)[:, ego]

        n_actions = len(entry.actions)
        if entry.actor == ego and ego_decisions < k:
            if controlled_policy == "uniform":
                probs = np.full((n_actions, tree.w), 1 / n_actions)
            elif controlled_policy == "first":
                probs = np.zeros((n_actions, tree.w))
                probs[0] = 1
            elif controlled_policy == "oracle":
                probs = tree.policy[index]
            else:
                probs = controlled_policy[index]
        else:
            probs = tree.policy[index]
        probs = np.asarray(probs, dtype=float)
        if probs.shape != (n_actions, tree.w) or np.any(probs < -1e-10) or not np.allclose(probs.sum(axis=0), 1):
            raise ValueError(f"Invalid action probabilities at native node {index}")
        future = np.stack(
            [descend(child, ego_decisions + int(entry.actor == ego)) for child in entry.children]
        )
        return np.einsum("aw,aw->w", probs, future)

    return float(np.dot(weights, descend(root_index, 0)))


def uniform_probe_regrets(episode, *, ego: int, root_index: int, root_weights, max_k: int):
    """Model-independent length probe; these are not measured LLM D values."""
    reference = expected_utility(
        episode, ego=ego, root_index=root_index, root_weights=root_weights,
        k=1, controlled_policy="oracle",
    )
    regrets = []
    for k in range(1, max_k + 1):
        value = expected_utility(
            episode, ego=ego, root_index=root_index, root_weights=root_weights,
            k=k, controlled_policy="uniform",
        )
        regrets.append(reference - value)
    return dict(
        oracle_value=reference,
        uniform_regret=regrets,
        incremental_regret=[regrets[0]] + [right - left for left, right in zip(regrets, regrets[1:])],
    )
