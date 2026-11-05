"""
Observation encoding for the RL negotiation wrapper.

Observations are stage-aware dictionaries with padded tensors so they can feed
standard deep-RL pipelines while still reflecting the underlying public state.
"""

from __future__ import annotations

import numpy as np

PARTNER_SELECTION_STAGE = 0
OFFER_SELECTION_STAGE = 1
RESPONSE_STAGE = 2


def pad_goal_features(player_features: np.ndarray, max_goal_slots: int | None) -> np.ndarray:
    """
    Pad the 9 goal-wise feature blocks to a fixed number of goal slots.

    ``get_gnn_features()`` returns features laid out as ``9 * n_goals + 2``.
    Padding block-by-block keeps semantics aligned across games with different
    numbers of goals.
    """
    if max_goal_slots is None:
        return player_features.astype(np.float32)

    raw_dim = player_features.shape[1]
    if (raw_dim - 2) % 9 != 0:
        raise ValueError(
            f"Unexpected player feature dimension {raw_dim}; cannot infer goal blocks."
        )

    n_goals = (raw_dim - 2) // 9
    if n_goals > max_goal_slots:
        raise ValueError(
            f"Game has {n_goals} goals but max_goal_slots={max_goal_slots}."
        )

    padded = np.zeros((player_features.shape[0], (9 * max_goal_slots) + 2), dtype=np.float32)
    for block_idx in range(9):
        src_start = block_idx * n_goals
        src_end = src_start + n_goals
        dst_start = block_idx * max_goal_slots
        dst_end = dst_start + n_goals
        padded[:, dst_start:dst_end] = player_features[:, src_start:src_end]

    padded[:, 9 * max_goal_slots :] = player_features[:, 9 * n_goals :]
    return padded


def encode_observation(
    *,
    state,
    stage: int,
    max_players: int,
    max_actions: int,
    max_candidate_offers: int,
    max_goal_slots: int | None,
    partner_mask: np.ndarray,
    offer_mask: np.ndarray,
    encoded_offer_actions: np.ndarray,
    selected_partner: int | None,
) -> dict:
    """Build a padded observation dictionary for the current decision stage."""
    player_features = pad_goal_features(state.get_gnn_features(), max_goal_slots)
    payoff_vector = state.get_payoff_vector()

    feature_dim = player_features.shape[1]
    padded_features = np.zeros((max_players, feature_dim), dtype=np.float32)
    padded_features[: state.n_players] = player_features.astype(np.float32)

    padded_policy = np.zeros((max_players, max_actions), dtype=np.int8)
    padded_policy[: state.n_players, : state.n_actions] = state.P.astype(np.int8)

    padded_payoffs = np.zeros(max_players, dtype=np.float32)
    padded_payoffs[: state.n_players] = payoff_vector.astype(np.float32)
    player_active_mask = np.zeros(max_players, dtype=np.int8)
    player_active_mask[: state.n_players] = 1

    turns_remaining = len(state.round_robin) - state.idx

    return {
        "player_features": padded_features,
        "policy_matrix": padded_policy,
        "payoff_vector": padded_payoffs,
        "player_active_mask": player_active_mask,
        "stage": np.array([stage], dtype=np.int64),
        "acting_player": np.array([state.proposer()], dtype=np.int64),
        "selected_partner": np.array(
            [-1 if selected_partner is None else selected_partner], dtype=np.int64
        ),
        "turn_index": np.array([state.idx], dtype=np.int64),
        "turns_remaining": np.array([turns_remaining], dtype=np.int64),
        "proposer_num_actions": np.array(
            [state.country_idx2num_actions[state.proposer()]], dtype=np.int64
        ),
        "partner_num_actions": np.array(
            [
                0
                if selected_partner is None
                else state.country_idx2num_actions[selected_partner]
            ],
            dtype=np.int64,
        ),
        "partner_mask": partner_mask.astype(np.int8),
        "offer_mask": offer_mask.astype(np.int8),
        "offer_actions": encoded_offer_actions.astype(np.int8).reshape(
            max_candidate_offers, -1
        ),
    }
