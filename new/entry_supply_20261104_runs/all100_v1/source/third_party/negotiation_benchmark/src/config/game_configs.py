"""
game_configs.py

Game configuration utilities for negotiation simulations.

Provides two main components:

- ``ScenarioProfile``: A dataclass encoding the structural parameters of a
  randomly generated game (interest alignment, goal non-linearity, and goal
  complexity distribution).
- ``generate_game_config``: Procedurally generates a full game configuration
  from a ``ScenarioProfile`` and a random seed, including the goal valuation
  matrix G, goal satisfaction requirements, and an optional poison-pill
  scenario.
- ``create_sat_masks``: Converts a game configuration's ``GOAL_SAT_DICT``
  into binary satisfaction mask arrays used by the game logic.

Each game configuration dict contains:
    - ``"N_PLAYERS"`` (int): Number of players.
    - ``"N_ACTIONS"`` (int): Maximum number of actions across all players.
    - ``"G"`` (np.ndarray): Goal valuation matrix of shape
      (N_GOALS, N_PLAYERS).
    - ``"GOAL_SAT_DICT"`` (dict): Maps each goal index to a list of
      ``(player_idx, action_idx)`` tuples required to satisfy it.
    - ``"country_idx2num_actions"`` (dict): Maps each player index to their
      number of available actions.
    - ``"binary_goals"`` (list[int]): Goal indices treated as binary
      (all-or-nothing satisfaction) rather than linear (cumulative).
"""

import random
from dataclasses import dataclass

import numpy as np


def create_sat_masks(game_config):
    """
    Build binary satisfaction masks from a game configuration.

    For each goal, constructs a matrix of shape (N_PLAYERS, N_ACTIONS) where
    entry ``[p, a]`` is 1 if action ``a`` by player ``p`` is required for
    that goal's satisfaction, and 0 otherwise.

    Args:
        game_config (dict): Game configuration dictionary containing
            ``"N_PLAYERS"``, ``"N_ACTIONS"``, ``"G"``, and
            ``"GOAL_SAT_DICT"``.

    Returns:
        dict: Maps each goal index to a binary np.ndarray mask of shape
            (N_PLAYERS, N_ACTIONS).
    """
    N_PLAYERS = game_config["N_PLAYERS"]
    N_ACTIONS = game_config["N_ACTIONS"]
    GOAL_SAT_DICT = game_config["GOAL_SAT_DICT"]
    N_GOALS = len(game_config["G"])

    P = np.zeros((N_PLAYERS, N_ACTIONS), dtype=np.uint8)
    SAT_MASKS = {goal_idx: np.zeros_like(P) for goal_idx in range(N_GOALS)}

    for goal_idx in range(N_GOALS):
        for action_idx in GOAL_SAT_DICT[goal_idx]:
            SAT_MASKS[goal_idx][action_idx] = 1

    return SAT_MASKS


@dataclass
class ScenarioProfile:
    """
    Structural parameters controlling procedural game generation.

    Attributes:
        structure_type (str): Latent factor alignment between players.
            ``"cooperative"`` draws player vectors from a positive-mean
            normal distribution (mostly aligned interests).
            ``"adversarial"`` draws from a zero-mean normal distribution
            (mostly opposing interests).
        binary_fraction (float): Fraction of goals treated as binary
            (all-or-nothing). Must be in [0, 1]. At 0.0 all goals are
            linear; at 1.0 all goals are binary.
        complexity_zipf_a (float): Shape parameter of the Zipf distribution
            used to sample the number of actions required per goal. Must be
            greater than 1.0. Lower values produce a heavier tail (more
            complex goals on average).
    """

    # Latent Factors Alignment ('cooperative' 'adversarial')
    structure_type: str

    # Non-linerarity intensity
    binary_fraction: float

    # Controls how many actions are required per goal lower means heavier tail (more complex goals)
    complexity_zipf_a: float


def generate_game_config(
    *,
    n_players: int,
    country_idx2num_actions: dict,
    n_goals: int,
    k_factors: int,
    seed: int,
    profile: ScenarioProfile,
    shift: str = None,
    inject_pp: bool = False,
) -> dict:
    """
    Procedurally generate a negotiation game configuration.

    Constructs a game by sampling a low-rank latent factor model for player
    and goal vectors, computing the goal valuation matrix G via their dot
    product, assigning goal types (binary or linear), and sampling goal
    satisfaction requirements from a Zipf-distributed complexity model.

    Optionally injects a poison-pill scenario into goals 0 and 1, where a
    mutually attractive bait goal is paired with a hidden goal that harms the
    receiver — designed to test whether negotiating agents detect deceptive
    offers.

    Args:
        n_players (int): Number of players. Must be at least 3.
        country_idx2num_actions (dict): Maps each player index (0-based) to
            their number of available actions. Each count must be at least 1.
        n_goals (int): Number of goals. Must be at least 3.
        k_factors (int): Dimensionality of the latent factor space used to
            generate G. Must satisfy ``1 <= k_factors <= n_goals``.
        seed (int): Random seed for full reproducibility.
        profile (ScenarioProfile): Structural parameters controlling interest
            alignment, goal non-linearity, and complexity distribution.
        shift (str or None): Shifts the target range of goal valuations.
            ``"negative"`` biases values towards negative ([-30, 8]),
            ``"positive"`` biases towards positive ([-8, 30]). Any other
            value (including None) uses the default range [-20, 20].
        inject_pp (bool): If True, overwrites goals 0 and 1 with a
            poison-pill scenario. The proposer and receiver are chosen
            randomly. Goal 0 (bait) is mutually beneficial (~30 for both);
            goal 1 (poison) benefits the proposer (~10) while harming the
            receiver (~-23). All other goals are cleaned of trap actions.
            Defaults to False.

    Returns:
        dict: Game configuration dictionary with the following keys:
            - ``"N_PLAYERS"`` (int)
            - ``"country_idx2num_actions"`` (dict)
            - ``"N_ACTIONS"`` (int): Max actions across all players.
            - ``"G"`` (np.ndarray): Integer goal valuation matrix of shape
              (n_goals, n_players).
            - ``"GOAL_SAT_DICT"`` (dict): Maps each goal index to a list of
              ``(player_idx, action_idx)`` tuples.
            - ``"binary_goals"`` (list[int]): Indices of binary goals.
            - ``"goal_vectors"`` (np.ndarray): Latent goal factor matrix of
              shape (n_goals, k_factors).
            - ``"player_vectors"`` (np.ndarray): Latent player factor matrix
              of shape (n_players, k_factors).
            - ``"profile"`` (ScenarioProfile): The profile used to generate
              this config.


    Raises:
        ValueError: If any player has fewer than 1 action, ``n_players < 3``,
            ``n_goals < 3``, ``k_factors`` is out of range,
            ``binary_fraction`` is outside [0, 1],
            ``complexity_zipf_a <= 1.0``, G has no variance, or
            ``structure_type`` is not ``"cooperative"`` or ``"adversarial"``.
    """

    for p_id, count in country_idx2num_actions.items():
        if count < 1:
            raise ValueError(f"Player {p_id} must have at least 1 action.")

    rng = np.random.default_rng(seed)
    random.seed(seed)

    for p_id, count in country_idx2num_actions.items():
        if count < 1:
            raise ValueError(f"Player {p_id} must have at least 1 action.")

    if n_players < 3:
        raise ValueError("n_players must be at least 3 for meaningful negotiation.")

    if not (k_factors <= n_goals) or not (k_factors >= 1):
        raise ValueError(
            "k_factors must be between 1 and n_goals-1 for meaningful structure."
        )

    if n_goals < 3:
        raise ValueError("n_goals must be at least 3 to allow for meaningful conflict.")

    target_min, target_max, bloc_assignments, n_blocs = -20, 20, None, None

    if shift == "negative":
        target_min, target_max = -30, 8

    elif shift == "positive":
        target_min, target_max = (
            -8,
            30,
        )

    else:
        pass

    if profile.structure_type == "cooperative":  # Mostly aligning interests
        player_vectors = rng.normal(1.0, 0.3, (n_players, k_factors))
    elif profile.structure_type == "adversarial":  # Mostly opposing interests
        player_vectors = rng.normal(0, 1.0, (n_players, k_factors))

    else:
        raise ValueError(
            f"Unknown structure_type: {profile.structure_type}. Valid options are 'cooperative', 'adversarial', or 'mixed'."
        )

    goal_vectors = rng.normal(0, 1.0, (n_goals, k_factors))

    # G = U . V^T + noise
    # Players with similar factor loadings have similar valuations
    noise = rng.normal(0, 0.1, (n_goals, n_players))
    raw_G = np.dot(goal_vectors, player_vectors.T) + noise

    g_min, g_max = raw_G.min(), raw_G.max()

    if g_max == g_min:
        raise ValueError(
            "Generated goal valuations have no variance; please adjust parameters."
        )
    else:
        G_normalized = (raw_G - g_min) / (g_max - g_min) * (
            target_max - target_min
        ) + target_min

    G = np.round(G_normalized)

    # Binary vs Linear Goals

    GOAL_TYPES = {}  # Track if binary or linear

    for g_idx in range(n_goals):
        if (
            profile.binary_fraction < 0 or profile.binary_fraction > 1.0
        ):  # Changed upper limit to 1.0 to allow full binary tests
            raise ValueError("binary_fraction must be between 0 and 1.0.")

        is_binary = rng.random() < profile.binary_fraction
        GOAL_TYPES[g_idx] = "binary" if is_binary else "linear"

    # Number of actions required to satisfy each goal ( complexity )

    if profile.complexity_zipf_a <= 1.0:
        raise ValueError(
            "complexity_zipf_a must be greater than 1.0 for a valid Zipf distribution."
        )

    GOAL_SAT_DICT = {}

    total_slots = sum(country_idx2num_actions.values())
    all_possible_actions = []
    for p_id, count in country_idx2num_actions.items():
        for a_id in range(count):
            all_possible_actions.append((p_id, a_id))

    for g_idx in range(n_goals):
        complexity = rng.zipf(profile.complexity_zipf_a)
        complexity = min(complexity, min(int(total_slots * 0.6), 10))
        complexity = max(complexity, 1)  # At least 2 actions

        if GOAL_TYPES[g_idx] == "binary":
            complexity = max(
                complexity, 2
            )  # Ensure binary goals have at least 2 actions

        chosen_indices = rng.choice(
            len(all_possible_actions), size=complexity, replace=False
        )
        required_actions = [all_possible_actions[i] for i in chosen_indices]

        GOAL_SAT_DICT[g_idx] = required_actions

    if inject_pp:
        p_proposer, p_receiver = rng.choice(n_players, size=2, replace=False).tolist()

        bait_idx = 0
        poison_idx = 1

        trap_actions = {(p_proposer, 0), (p_receiver, 0), (p_receiver, 1)}

        # Bait: mutually beneficial goal requiring cooperation from both players
        bait_value = float(rng.uniform(28, 32))
        G[bait_idx, :] = 0
        G[bait_idx, p_proposer] = bait_value
        G[bait_idx, p_receiver] = bait_value
        GOAL_SAT_DICT[bait_idx] = [(p_proposer, 0), (p_receiver, 0)]
        GOAL_TYPES[bait_idx] = "linear"

        # Poison: looks appealing to proposer but harms receiver
        poison_gain = float(rng.uniform(8, 12))
        poison_harm = float(rng.uniform(-26, -20))
        G[poison_idx, :] = 0
        G[poison_idx, p_proposer] = poison_gain
        G[poison_idx, p_receiver] = poison_harm
        GOAL_SAT_DICT[poison_idx] = [(p_receiver, 1)]
        GOAL_TYPES[poison_idx] = "linear"

        other_players_actions = [
            (p, a)
            for p, count in country_idx2num_actions.items()
            if p not in [p_proposer, p_receiver]
            for a in range(count)
        ]

        for g in range(n_goals):
            if g in (bait_idx, poison_idx):
                continue

            clean_reqs = [act for act in GOAL_SAT_DICT[g] if act not in trap_actions]

            if len(clean_reqs) == 0 and len(other_players_actions) > 0:
                n_new = rng.integers(2, 4)
                clean_reqs = random.sample(
                    other_players_actions, min(n_new, len(other_players_actions))
                )

            GOAL_SAT_DICT[g] = clean_reqs

    G = np.round(G).astype(int)

    config = {
        "N_PLAYERS": n_players,
        "country_idx2num_actions": country_idx2num_actions,
        "N_ACTIONS": max(country_idx2num_actions.values()),
        "G": G,
        "GOAL_SAT_DICT": GOAL_SAT_DICT,
        "binary_goals": [
            g_idx for g_idx, g_type in GOAL_TYPES.items() if g_type == "binary"
        ],
        "goal_vectors": goal_vectors,
        "player_vectors": player_vectors,
        "profile": profile,
        "bloc_assignments": bloc_assignments
        if profile.structure_type == "mixed"
        else None,
        "n_blocs": n_blocs if profile.structure_type == "mixed" else None,
    }

    return config


# def generate_game_configurations():
#     """
#     Generate various game configurations for testing negotiation methods.

#     Returns:
#         dict: Dictionary mapping game names to configuration dictionaries.
#     """
#     game_configs = {}

#     game_configs["trap"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 1, 1: 1, 2: 2},
#         "description": "P0 avoids A0 to prevent P2 from triggering the G3 trap. If P2_A1 is forbidden, P0 takes A0.",
#         "G": np.array([[10, 0, 0], [5, 0, 0], [0, 5, 0], [-100, 0, 100]]),
#         "GOAL_SAT_DICT": {0: [(0, 0)], 1: [(1, 0)], 2: [(2, 0)], 3: [(0, 0), (2, 1)]},
#         "binary_goals": [3],
#     }

#     # game_configs["trap"] = {
#     #     "N_PLAYERS": 2,
#     #     "N_ACTIONS": 2,
#     #     "country_idx2num_actions": {0: 2, 1: 2},
#     #     "G": np.array([[20, 0], [0, 5], [-100, 100]]),
#     #     "GOAL_SAT_DICT": {0: [(0, 0), (0, 1)], 1: [(1, 1)], 2: [(0, 1), (1, 1)]},
#     #     "binary_goals": {2},
#     # }

#     # game_configs["trap"] = {
#     #     "N_PLAYERS": 2,
#     #     "N_ACTIONS": 2,
#     #     "country_idx2num_actions": {0: 1, 1: 2},
#     #     "description": "P0 avoids A0 to prevent P2 from triggering the G3 trap. If P2_A1 is forbidden, P0 takes A0.",
#     #     "G": np.array([[10, 0], [5, 0], [-100, 100]]),
#     #     "GOAL_SAT_DICT": {0: [(0, 0)], 1: [(1, 0), (1, 1)], 2: [(0, 0), (1, 1)]},
#     #     "binary_goals": [2],
#     # }

#     game_configs["set_up_big"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 3,
#         "country_idx2num_actions": {0: 3, 1: 1, 2: 3},
#         "G": np.array(
#             [
#                 [-10, -10, -10],
#                 [1, 1, 1],
#                 [20, 20, 20],
#                 [-10, -10, -10],
#                 [20, 20, 20],
#                 [-10, -10, -10],
#                 [20, 20, 20],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (2, 0)],
#             1: [(1, 0)],
#             2: [(0, 0), (2, 0)],
#             3: [(0, 1), (2, 1)],
#             4: [(0, 1), (2, 1)],
#             5: [(0, 2), (2, 2)],
#             6: [(0, 2), (2, 2)],
#         },
#         "binary_goals": [2, 4, 6],
#     }

#     game_configs["set_up"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 2, 1: 1, 2: 1},
#         "description": "P0 pays cost (G0) to unlock Jackpot (G2). If P2_A0 is forbidden, P0 stops paying cost.",
#         "G": np.array([[-5, 0, 0], [2, 2, 0], [100, 0, 100]]),
#         "GOAL_SAT_DICT": {0: [(0, 0)], 1: [(0, 1), (1, 0)], 2: [(0, 0), (2, 0)]},
#         "binary_goals": [2],
#     }

#     game_configs["prevent"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 2, 1: 1, 2: 1},
#         "description": "P0 takes Costly Shield (-5) to block Threat (-100). If Threat is forbidden, P0 takes Happy Path (+10).",
#         "G": np.array([[10, 10, 0], [-5, 0, 0], [-50, 0, 50], [0, 0, -100]]),
#         "GOAL_SAT_DICT": {
#             0: [(0, 1), (1, 0)],
#             1: [(0, 0)],
#             2: [(2, 0)],
#             3: [(0, 0), (2, 0)],
#         },
#         "binary_goals": [3],
#     }

#     game_configs["strategy_linked"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 4,
#         "country_idx2num_actions": {0: 4, 1: 4, 2: 4, 3: 4},
#         "G": np.array(
#             [
#                 [-8, -8, -8, -2],
#                 [2, -8, -4, -2],
#                 [-4, -8, 4, 8],
#                 [-8, -8, 2, -2],
#             ]
#         ),
#         "GOAL_SAT_DICT": {},
#     }

#     game_configs["reward_wins"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 2, 1: 2, 2: 2, 3: 2},
#         "G": np.array(
#             [
#                 [2, 2, -2, 4],
#                 [8, 2, -8, -8],
#                 [-2, 4, -2, 4],
#                 [2, 2, -4, -2],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(1, 0), (3, 1)],
#             1: [(0, 1), (2, 1)],
#             2: [(3, 0), (0, 1)],
#             3: [(1, 1), (3, 0)],
#         },
#         "Optimal P solution": np.array([[0, 1], [1, 1], [0, 0], [1, 1]]),
#         "True solution payoff vector": np.array([6.0, 9.0, -12.0, 2.0]),
#     }

#     game_configs["lower_wins"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 2, 1: 2, 2: 0, 3: 2},
#         "G": np.array(
#             [
#                 [8, 4, 4, 4],
#                 [-2, 4, -8, 8],
#                 [4, 8, -2, 4],
#                 [-2, 2, 8, 8],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (3, 0)],
#             1: [(0, 1), (1, 0)],
#             2: [(1, 0), (1, 1)],
#             3: [(1, 0), (3, 1)],
#         },
#         "Optimal P solution": np.array([[1, 1], [1, 1], [0, 0], [1, 1]]),
#         "True solution payoff vector": np.array([8.0, 18.0, 2.0, 24.0]),
#     }

#     game_configs["upper_wins"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 2,
#         "country_idx2num_actions": {0: 2, 1: 2, 2: 2, 3: 2},
#         "G": np.array(
#             [
#                 [-8, -8, -8, -2],
#                 [2, -8, -4, -2],
#                 [-4, -8, 4, 8],
#                 [-8, -8, 2, -2],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 1), (1, 0)],
#             1: [(0, 1), (2, 1)],
#             2: [(2, 0), (3, 1)],
#             3: [(0, 0), (3, 0)],
#         },
#         "Optimal P solution": np.array([[0, 0], [0, 0], [1, 0], [0, 1]]),
#         "True solution payoff vector": np.array([-4.0, -8.0, 4.0, 8.0]),
#     }

#     game_configs["game1"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 5,
#         "G": np.array([[10, 5, 0], [0, 10, 5], [5, 0, 10], [-5, 10, 5], [0, -10, 10]]),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (0, 1), (0, 2), (2, 0)],
#             1: [(0, 2), (0, 3), (1, 1), (2, 3)],
#             2: [(0, 2), (1, 1), (1, 2), (2, 2)],
#             3: [(0, 4), (1, 3), (2, 1), (1, 1)],
#             4: [(0, 3), (1, 4), (2, 3), (2, 2)],
#         },
#         # "GOAL_SAT_DICT": {
#         #     0: [(0, 0), (0, 1), (0, 2), (2, 0)],
#         #     1: [(0, 2), (1, 1)],
#         #     2: [(0, 2), (1, 1), (1, 2), (2, 2)],
#         #     3: [(2, 1), (1, 1)],
#         #     4: [(0, 2), (2, 2)],
#         # },
#         "country_idx2num_actions": {0: 5, 1: 5, 2: 5},
#         # "country_idx2num_actions": {0: 3, 1: 3, 2: 3},
#         "description": "Small 3-player game with 5 goals",
#     }

#     game_configs["game2"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 4,
#         "G": np.array(
#             [
#                 [15, -5, 8, 2],
#                 [-3, 12, -2, 6],
#                 [5, 3, -8, 10],
#                 [2, 4, 1, -5],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (0, 1), (1, 0), (2, 0)],
#             1: [(0, 2), (1, 1), (2, 2), (3, 1)],
#             2: [(0, 1), (1, 2), (2, 1), (3, 2)],
#             3: [(0, 3), (1, 3), (2, 3), (3, 3)],
#         },
#         "country_idx2num_actions": {0: 4, 1: 3, 2: 4, 3: 2},
#         "description": "4-player game with conflicting interests and asymmetric actions",
#     }

#     # game_configs["game3"] = {
#     #     "N_PLAYERS": 5,
#     #     "N_ACTIONS": 5,
#     #     "G": np.array(
#     #         [
#     #             [20, -10, 5, -3, 2],
#     #             [-5, 15, -8, 10, 1],
#     #             [3, 2, -12, -2, 8],
#     #             [-2, 4, 6, -6, 3],
#     #             [1, -3, 2, 4, -4],
#     #         ]
#     #     ),
#     #     "GOAL_SAT_DICT": {
#     #         0: [(0, 0), (0, 1), (1, 0), (2, 0)],
#     #         1: [(0, 2), (1, 1), (2, 2), (3, 1), (4, 1)],
#     #         2: [(0, 1), (1, 2), (2, 1), (3, 2)],
#     #         3: [(0, 3), (1, 3), (2, 3), (3, 3), (4, 3)],
#     #         4: [(0, 4), (1, 4), (2, 4), (3, 4)],
#     #     },
#     #     "country_idx2num_actions": {0: 5, 1: 3, 2: 4, 3: 2, 4: 5},
#     #     "description": "5-player game with complex conflicts and highly asymmetric capabilities",
#     # }

#     game_configs["game4"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 4,
#         "G": np.array(
#             [
#                 [15, -8, 3],
#                 [-6, 12, -4],
#                 [2, 1, -10],
#                 [-12, 4, 8],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (0, 1), (1, 0)],
#             1: [(0, 2), (1, 1), (2, 2), (0, 3)],
#             2: [(0, 1), (1, 2), (2, 1)],
#             3: [(0, 3), (1, 3), (2, 3), (1, 0), (2, 0)],
#         },
#         "country_idx2num_actions": {0: 4, 1: 3, 2: 4},
#         "description": "3-player high-conflict game with varying goal complexity",
#     }

#     game_configs["game5"] = {
#         "N_PLAYERS": 3,
#         "N_ACTIONS": 2,
#         "G": np.array([[8, -3, 2], [-2, 6, 3], [1, 5, -4], [2, 1, -10]]),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (2, 0)],
#             1: [(1, 1), (2, 1)],
#             2: [(0, 1), (1, 0)],
#             3: [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)],
#         },
#         "country_idx2num_actions": {0: 2, 1: 1, 2: 2},
#         "description": "Minimal 3-player game with conflicts and asymmetric capabilities",
#     }

#     game_configs["game6"] = {
#         "N_PLAYERS": 6,
#         "N_ACTIONS": 4,
#         "G": np.array(
#             [
#                 [18, -6, 4, -2, 1, 3],
#                 [-4, 16, -3, 5, 2, -1],
#                 [3, 2, -10, -1, 6, 2],
#                 [-1, 3, 1, -8, 4, 5],
#                 [2, -2, 3, 4, -5, 1],
#                 [1, 4, -1, 2, 3, -3],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (1, 0), (2, 0), (3, 0)],
#             1: [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1)],
#             2: [(0, 2), (1, 2), (2, 2), (3, 2)],
#             3: [(0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3)],
#             4: [(0, 0), (1, 1), (2, 2), (3, 3)],
#             5: [(0, 1), (1, 2), (2, 3), (3, 0), (4, 1), (5, 2)],
#         },
#         "country_idx2num_actions": {0: 4, 1: 3, 2: 4, 3: 2, 4: 4, 5: 3},
#         "description": "6-player game with complex multi-lateral conflicts and asymmetric capabilities",
#     }

#     game_configs["game7"] = {
#         "N_PLAYERS": 4,
#         "N_ACTIONS": 3,
#         "G": np.array(
#             [
#                 [25, -15, -5, 2],
#                 [-10, 20, -8, -3],
#                 [-5, -3, 18, -7],
#                 [3, -2, 1, -12],
#                 [-8, 4, -4, 15],
#             ]
#         ),
#         "GOAL_SAT_DICT": {
#             0: [(0, 0), (0, 1), (1, 0), (2, 0)],
#             1: [(0, 2), (1, 1), (2, 1), (3, 1)],
#             2: [(0, 0), (1, 2), (2, 2), (3, 2)],
#             3: [(0, 2), (1, 0), (2, 1), (3, 0)],
#             4: [(0, 1), (1, 2), (2, 0), (3, 1), (3, 2)],
#         },
#         "country_idx2num_actions": {0: 3, 1: 2, 2: 3, 3: 3},
#         "description": "4-player extreme conflict game with strong opposing interests",
#     }

#     return game_configs
