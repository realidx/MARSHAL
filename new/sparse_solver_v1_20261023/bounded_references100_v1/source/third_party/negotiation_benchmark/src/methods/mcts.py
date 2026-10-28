"""
mcts.py

Monte Carlo Tree Search (MCTS) for negotiation partner selection.

Implements two MCTS variants and a Dynamic Programming solver for choosing
which partner to negotiate with at each turn of a multi-player negotiation
game.

- ``mcts_vanilla_multi_ply``: MCTS with UCB selection and random rollouts.
- ``mcts_multi_ply``: MCTS with configurable selection (UCB or PUCT) and
  support for an externally supplied offer function.
- ``dp_multi_ply``: Exact k-step lookahead via Dynamic Programming.
"""

import numpy as np


class Node:
    """
    A node in the MCTS tree representing a negotiation decision point.

    Each node corresponds to a proposer choosing a partner to negotiate with.
    Visit counts and cumulative payoff vectors are accumulated during
    backpropagation and used by the selection policy to balance exploration
    and exploitation.
    """

    def __init__(self, proposer, proposee, state, parent=None):
        """
        Initialise an MCTS node.

        Args:
            proposer (int): Index of the player making the proposal at this
                node.
            proposee (int or None): Index of the player being proposed to,
                or None for the root node.
            state (NegotiationState): Game state at this node, used to
                determine the set of legal negotiation partners.
            parent (Node or None): Parent node. None for the root.
        """
        self.proposer = proposer
        self.proposee = proposee
        self.parent = parent

        self.children = {}  # key: partner id -> Node
        self.N = 0  # visit count
        self.W = None  # cumulative payoff vector

        if not state.is_terminal():
            legal = state.legal_negotiation_partners()

            self.untried_partners = legal
        else:
            self.untried_partners = []

    def is_fully_expanded(self):
        """Returns True if all legal moves from this node have been visited."""
        return len(self.untried_partners) == 0

    def __str__(self):
        return (
            f"Node({self.proposer}->{self.proposee}, "
            f"N={self.N}, Untried={len(self.untried_partners)})"
        )


def puct_value(child, parent_visits, proposer, prior_prob, c_puct):
    """
    Compute the AlphaZero-style PUCT score for a child node.

    The score balances exploitation (mean return for the acting player) and
    exploration (prior-weighted bonus that decays with child visit count).

    Args:
        child (Node): The child node being evaluated.
        parent_visits (int): Total visit count of the parent node.
        proposer (int): Index of the player acting at the parent node.
        prior_prob (float): Prior probability assigned to this child by the
            partner prior function.
        c_puct (float): Exploration constant scaling the exploration bonus.

    Returns:
        float: PUCT score for this child.

    Raises:
        ValueError: If the exploration term is zero despite a non-zero prior.
    """
    # exploitation: mean return for the acting player
    q = (child.W[proposer] / child.N) if child.N > 0 else 0.0

    # exploration: prior-weighted bonus (no log; classic PUCT form)
    u = c_puct * prior_prob * (np.sqrt(max(1, parent_visits)) / (1 + child.N))

    if u == 0.0:
        if prior_prob != 0.0:
            raise ValueError("PUCT exploration term is zero.")

    return q + u


def ucb_value(child, parent_visits, parent, G, c_ucb):
    """
    Compute the UCB1 score for a child node.

    Args:
        child (Node): The child node being evaluated.
        parent_visits (int): Total visit count of the parent node.
        parent (int): Index of the player acting at the parent node.
        G (np.ndarray): Goal valuation matrix, used as a normalisation
            reference for the average reward.
        c_ucb (float): Exploration constant scaling the UCB bonus.

    Returns:
        float: UCB1 score for this child.

    Raises:
        ValueError: If the child has never been visited.
    """
    if child.N == 0:
        raise ValueError("UCB called on unvisited child node.")

    average_reward = child.W[parent] / child.N
    exploration_bonus = c_ucb * np.sqrt(np.log(parent_visits) / child.N)

    return average_reward + exploration_bonus


def mcts_multi_ply(
    root_state, n_sims, c_ucb, get_best_offer_fn, n_players, max_iter, use_prior
):
    """
    Run MCTS with UCB selection to choose the best negotiation partner.

    Uses a standard four-phase MCTS loop (selection, expansion, rollout,
    backpropagation). The offer function is created internally using a greedy
    linear strategy with a fixed budget of 3 action flips per player.
    Rollouts play randomly until the game is terminal. The final decision
    uses the robust-child criterion: the partner with the highest visit count.

    Args:
        root_state (NegotiationState): Current game state at the root.
        n_sims (int): Number of MCTS simulations to run.
        c_ucb (float): Exploration constant for UCB selection.
        n_players (int): Total number of players in the game.
        max_iter (int): Maximum number of selection steps per simulation
            (safety cap to prevent infinite loops).

    Returns:
        tuple:
            - best_partner (int or None): Index of the recommended partner,
              or None if no simulations produced a valid move.
            - root (Node): The root node after all simulations, containing
              the full visit statistics.
    """
    # Initialize Root
    # We pass root_state so it can calculate its own untried_partners
    root = Node(root_state.proposer(), None, root_state, parent=None)

    for sim in range(n_sims):
        s = root_state.clone()
        node = root

        # ---------------------------------------------------------------------
        # 1. SELECTION
        # Travel down the tree using UCB/PUCT until we hit a node that
        # has untried moves (is not fully expanded) or is terminal.
        # ---------------------------------------------------------------------
        while node.is_fully_expanded() and not s.is_terminal():
            # If a node is fully expanded but has no children (e.g. no legal moves), break
            if not node.children:
                break

            p = s.proposer()

            # Choose best existing child using UCB or PUCT
            if use_prior:
                raise ValueError("Prior-based not used for now.")
                # Re-calculate priors here only for the weighting formula
                # (Optimization: You could store these in the node to save time)
                # priors = build_partner_prior_simple(s, max_changes=3)
                # partner = max(
                #     node.children,
                #     key=lambda x: puct_value(
                #         node.children[x],
                #         parent_visits=node.N,
                #         proposer=p,
                #         prior_prob=priors.get(x, 0.0),
                #         c_puct=c_ucb,
                #     ),
                # )
            else:
                partner = max(
                    node.children,
                    key=lambda x: ucb_value(
                        node.children[x],
                        parent_visits=node.N,
                        parent=p,
                        G=root_state.G,
                        c_ucb=c_ucb,
                    ),
                )

            # Apply the move to the simulation state 's'
            offer, _ = get_best_offer_fn(s, partner)
            if offer is None:
                s.reject_deal()
            else:
                s.play_deal(offer, partner)

            node = node.children[partner]

        # ---------------------------------------------------------------------
        # 2. EXPANSION
        # If we stopped because the node has untried moves, pick ONE and add it.
        # ---------------------------------------------------------------------
        if not s.is_terminal() and not node.is_fully_expanded():
            # Pop the BEST remaining partner (due to the sort in Node.__init__)
            partner = node.untried_partners.pop()

            # Apply the move to get the state for the new node
            offer, _ = get_best_offer_fn(s, partner)
            if offer is None:
                s.reject_deal()
            else:
                s.play_deal(offer, partner)

            # Create the new child node
            # We pass 's' (the state AFTER the move) so the new node
            # can calculate its own future untried partners.
            new_node = Node(s.proposer(), partner, s, parent=node)

            node.children[partner] = new_node
            node = new_node

        # ---------------------------------------------------------------------
        # 3. ROLLOUT (TRUNCATED)
        # ---------------------------------------------------------------------

        # Option B (Better): k-step Greedy Lookahead
        # rollout_steps = n_players
        # for _ in range(rollout_steps):
        #     if s.is_terminal():
        #         break
        #     legal = s.legal_negotiation_partners()
        #     if not legal:
        #         s.reject_deal()
        #         continue
        #     partner = random.choice(legal)  # or pick best by prior
        #     offer, _ = get_best_offer_fn(s, partner)
        #     if offer:
        #         s.play_deal(offer, partner)
        #     else:
        #         s.reject_deal()

        # Default: Zero-step lookahead (Value = Current Payoff)
        reward = s.get_payoff_vector()

        # tmp_state = s.clone()

        # solver = create_solver(tmp_state)
        # reward = solver(state_key(tmp_state))[0]

        # ---------------------------------------------------------------------
        # 4. BACKPROPAGATION
        # Walk back up the tree using parent pointers
        # ---------------------------------------------------------------------
        while node is not None:
            node.N += 1
            if node.W is None:
                node.W = np.zeros(n_players, dtype=float)
            node.W += reward
            node = node.parent

    # -------------------------------------------------------------------------
    # FINAL DECISION
    # Return the partner with the highest visit count (Robust Child)
    # -------------------------------------------------------------------------
    if not root.children:
        # Fallback if no simulations ran or no legal moves exist
        return None, root

    best_partner = max(root.children, key=lambda k: root.children[k].N)

    return best_partner, root
