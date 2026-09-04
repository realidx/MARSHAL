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

        # Initialize policy matrix (all zeros)
        self.P = np.zeros((n_players, n_actions), dtype=np.uint8)
        self.seed = seed

        # Create round robin order
        self.round_robin = [i for i in range(n_players)]
        random.seed(seed)
        random.shuffle(self.round_robin)
        self.round_robin = self.round_robin * (n_turns)

        # Game state tracking
        self.idx = 0

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

        return [partner for partner in range(self.n_players)]

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
