"""
game_state.py

Game state management for negotiation simulations.

Contains the NegotiationState class, which tracks the current policy matrix,
turn order, terminal conditions, and payoff computation for a multi-player
bilateral negotiation game.
"""

import random
from copy import deepcopy

import numpy as np
from core.game_logic import apply_action, get_payoff_per_country


class NegotiationState:
    """
    Represents the complete state of a negotiation game.

    Manages the policy matrix, the round-robin turn order, convergence
    tracking, and payoff computation. Each turn, the current proposer
    may negotiate a bilateral deal with any other player.
    """

    def __init__(
        self,
        n_players,
        n_actions,
        n_turns,
        G,
        sat_masks,
        country_idx2num_actions,
        seed,
        binary_goals=None,
        forbidden_actions=None,
        allowed_actions=None,
        model=None,
        round_robin=None,
    ):
        """
        Initialise a negotiation game state.

        Args:
            n_players (int): Number of players in the game.
            n_actions (int): Maximum number of actions any player can take.
            n_turns (int): Number of complete rounds to simulate.
            G (np.ndarray): Goal valuation matrix of shape
                (N_GOALS, N_PLAYERS).
            sat_masks (dict): Maps each goal index to a binary satisfaction
                mask of shape (N_PLAYERS, N_ACTIONS).
            country_idx2num_actions (dict): Maps each player index to their
                number of available actions.
            seed (int): Random seed used to shuffle the initial turn order.
            binary_goals (list or None): Goal indices treated as binary
                (all-or-nothing). Defaults to an empty set.
            forbidden_actions (np.ndarray or None): Binary mask of shape
                (N_PLAYERS, N_ACTIONS) for actions that may never be played.
        """
        self.n_players = n_players
        self.n_actions = n_actions
        self.n_turns = n_turns
        self.G = G
        self.sat_masks = sat_masks
        self.country_idx2num_actions = country_idx2num_actions

        self.binary_goals = set(binary_goals) if binary_goals else set()
        self.forbidden_actions = forbidden_actions
        self.allowed_actions = allowed_actions
        self.model = model

        # Initialize policy matrix (all zeros)
        self.P = np.zeros((n_players, n_actions), dtype=np.uint8)
        self.seed = seed

        self._validate_dimensions()

        # Create round robin order
        if round_robin is not None:
            self.round_robin = list(round_robin)
        else:
            self.round_robin = [i for i in range(n_players)]
            random.seed(seed)
            random.shuffle(self.round_robin)
        self.round_robin = self.round_robin * (n_turns)
        if any(player < 0 or player >= self.n_players for player in self.round_robin):
            raise ValueError("round_robin contains an out-of-range player id.")

        # Game state tracking
        self.idx = 0

    def _validate_dimensions(self):
        """Validate that the supplied game tensors agree on core dimensions."""
        expected_shape = (self.n_players, self.n_actions)

        if self.G.ndim != 2 or self.G.shape[1] != self.n_players:
            actual_players = self.G.shape[1] if self.G.ndim == 2 else None
            raise ValueError(
                "Goal valuation matrix G has incompatible shape: "
                f"expected (*, {self.n_players}), got {self.G.shape}; "
                f"player dimension was {actual_players}."
            )

        for player_id, num_actions in self.country_idx2num_actions.items():
            if player_id < 0 or player_id >= self.n_players:
                raise ValueError(
                    "country_idx2num_actions contains an out-of-range player id: "
                    f"{player_id} for n_players={self.n_players}."
                )
            if num_actions < 0 or num_actions > self.n_actions:
                raise ValueError(
                    "country_idx2num_actions contains an invalid action count: "
                    f"player {player_id} has {num_actions}, n_actions={self.n_actions}."
                )

        for goal_id, mask in self.sat_masks.items():
            if mask.shape != expected_shape:
                raise ValueError(
                    "Satisfaction mask shape does not match the negotiation state. "
                    f"Goal {goal_id} has mask shape {mask.shape}, expected {expected_shape}. "
                    "This usually means `config` and `sat_masks` came from different game generations."
                )

        for name, action_mask in (
            ("allowed_actions", self.allowed_actions),
            ("forbidden_actions", self.forbidden_actions),
        ):
            if action_mask is not None and action_mask.shape != expected_shape:
                raise ValueError(
                    f"{name} has shape {action_mask.shape}, expected {expected_shape}."
                )

    def clone(self):
        """Create a deep copy of this state."""
        return deepcopy(self)

    def is_terminal(self):
        """Check if the game has ended."""
        return self.idx >= len(self.round_robin)

    def proposer(self):
        """Get the current proposer player index."""
        if self.idx >= len(self.round_robin):
            return self.round_robin[-1]
        return self.round_robin[self.idx]

    def next_proposer(self):
        """Get the next proposer player index, or None if terminal."""
        if self.idx + 1 >= len(self.round_robin):
            return None
        else:
            return self.round_robin[self.idx + 1]

    def legal_negotiation_partners(self):
        """Get list of valid negotiation partners ."""

        return [partner for partner in range(self.n_players) if partner != self.proposer()]

    def play_deal(self, offer, partner):
        """
        Execute a successful deal between proposer and partner.

        Args:
            offer (tuple): Joint action (concatenated actions for both players)
            partner (int): Partner player index
        """

        p = self.proposer()
        self.P = apply_action(self.P, offer, p, partner, self.country_idx2num_actions)
        self.idx += 1

    def reject_deal(self):
        """Reject the current deal and move to next turn."""
        self.idx += 1

    def get_payoff_vector(self):
        """
        Calculate current payoffs for all players.

        Returns:
            np.ndarray: Payoff vector (n_players,)
        """
        return get_payoff_per_country(self.P, self.G, self.sat_masks, self.binary_goals)

    def get_turn_proximity(self):
        """Return how soon each player acts again in the remaining schedule."""
        remaining_schedule = self.round_robin[self.idx :]
        proximity = []

        for player_id in range(self.n_players):
            if player_id in remaining_schedule:
                wait = remaining_schedule.index(player_id)
                proximity.append(1.0 / (1.0 + wait))
            else:
                proximity.append(0.0)

        return np.asarray(proximity, dtype=float).reshape(self.n_players, 1)

    def get_gnn_features(self):
        """Build stage-aware per-player features for value models.

        The feature layout is ``9 * n_goals + 2`` columns: preferences,
        progress, influence, binary-goal flags, satisfaction, solo-finish
        indicators, three preference interaction blocks, turn proximity, and
        normalized remaining rounds.
        """
        n_players = self.n_players
        n_goals = len(self.sat_masks)

        preferences = self.G.astype(float)
        max_abs = float(np.abs(preferences).max()) if preferences.size else 0.0
        if max_abs > 0:
            preferences = preferences / max_abs
        preferences = preferences.T

        progress_vec = np.zeros(n_goals, dtype=float)
        satisfaction_vec = np.zeros(n_goals, dtype=float)
        binary_vec = np.zeros(n_goals, dtype=float)
        influence = np.zeros((n_players, n_goals), dtype=float)
        can_finish_alone = np.zeros((n_players, n_goals), dtype=float)

        for goal_id, sat_mask in self.sat_masks.items():
            required = np.argwhere(sat_mask == 1)
            goal_size = len(required)
            if goal_size == 0:
                continue

            met = sum(int(self.P[player_id, action_id]) for player_id, action_id in required)
            progress = met / goal_size
            progress_vec[goal_id] = progress
            is_binary = goal_id in self.binary_goals
            binary_vec[goal_id] = float(is_binary)
            satisfaction_vec[goal_id] = 1.0 if is_binary and met == goal_size else (
                0.0 if is_binary else progress
            )

            unmet_players = []
            for player_id, action_id in required:
                if self.P[player_id, action_id] == 0:
                    influence[player_id, goal_id] += 1.0 / goal_size
                    unmet_players.append(int(player_id))

            if unmet_players and len(set(unmet_players)) == 1:
                can_finish_alone[unmet_players[0], goal_id] = 1.0

        progress_levels = np.tile(progress_vec, (n_players, 1))
        satisfaction_levels = np.tile(satisfaction_vec, (n_players, 1))
        binary_levels = np.tile(binary_vec, (n_players, 1))

        rounds_left = len(self.round_robin[self.idx :])
        total_rounds = len(self.round_robin)
        remaining_rounds = np.full(
            (n_players, 1),
            rounds_left / total_rounds if total_rounds else 0.0,
            dtype=float,
        )

        return np.hstack(
            (
                preferences,
                progress_levels,
                influence,
                binary_levels,
                satisfaction_levels,
                can_finish_alone,
                preferences * progress_levels,
                preferences * satisfaction_levels,
                preferences * binary_levels * (1.0 - progress_levels),
                self.get_turn_proximity(),
                remaining_rounds,
            )
        )

    def estimate_gnn_payoff_vector(self, model=None):
        """Estimate player payoffs with an optional GNN value model."""
        from methods.gnn import estimate_state_payoffs_with_gnn

        active_model = model if model is not None else self.model
        return estimate_state_payoffs_with_gnn(self, active_model)
