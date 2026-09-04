"""
runner.py

Experiment runner for comparing negotiation methods across game configurations.

Orchestrates multi-trial experiments in which different negotiation methods
(greedy, MCTS, DP, LLM) are evaluated across one or more game configurations.
Aggregates per-trial results into summary statistics and provides a console
table for quick comparison.
"""

import numpy as np
from core.equilibrium import check_equilibrium
from core.game_state import NegotiationState
from methods.baselines import get_llm_decision
from methods.mcts import mcts_multi_ply

# --- in experiments/runner.py ---
from methods.negotiation import (
    # calculate_satisfaction_features,¬
    # calculate_value_features,  # <— add this import
    create_negotiation_functions,
)


def run_single_game(
    game_config, sat_masks, method_config, seed, collect_data=False, collect_for=None
):
    """
    Run a single negotiation game and return the outcome.

    Simulates a full round-robin negotiation game using the method specified
    in ``method_config``. At each turn the current proposer selects a partner
    and proposes a joint action; the deal is executed if an offer is found,
    otherwise the turn is rejected.

    Supported method types (determined by ``method_config["how_fallback"]``):
    - ``"LLM_full"``: LLM-based decision via ``get_llm_decision``.
    - ``"<method>_random"``: Random partner selection with a heuristic offer.
    - Any other value: MCTS partner selection via ``mcts_multi_ply`` with a
      heuristic offer.

    Args:
        game_config (dict): Game configuration containing at minimum:
            ``"N_PLAYERS"``, ``"N_ACTIONS"``, ``"G"``,
            ``"country_idx2num_actions"``, and optionally ``"binary_goals"``,
            ``"model"``, ``"allowed_actions"``, ``"forbidden_actions"``.
        sat_masks (dict): Satisfaction masks for the game.
        method_config (dict): Method configuration containing:
            - ``"how_fallback"`` (str): Offer method / dispatch key.
            - ``"n_sims"`` (int): Number of MCTS simulations.
            - ``"c_ucb"`` (float): UCB exploration constant.
            - ``"use_prior"`` (bool): Whether to use a prior in MCTS.
            - ``"max_changes"`` (int): Action budget per player per turn.
            - ``"n_turns"`` (int, optional): Number of game rounds (capped
              at 10).
            - ``"k"`` (int, optional): Lookahead depth for offer estimation.
            - ``"max_iter_mcts"`` (int, optional): MCTS step cap per sim.
        seed (int): Random seed for the round-robin turn order.
        collect_data (bool): If True, collect training data during the game.
            Defaults to False.
        collect_for (str or None): Required when ``collect_data`` is True.
            Must be ``"goal_prob"`` or ``"value_model"``.

    Returns:
        tuple:
            - results_dict (dict): Game outcome containing payoff vector,
              sum and product payoffs, equilibrium status, per-player regret,
              final policy matrix, turn order, reject count, and per-turn
              trace.
            - data (list or None): Collected training data if
              ``collect_data`` is True, otherwise None.

    Raises:
        AssertionError: If ``collect_data`` is True but ``collect_for`` is
            not a valid value.
        ValueError: If a DP offer has an unexpected length.
    """
    if collect_data:
        assert collect_for in [
            "goal_prob",
            "value_model",
        ], "collect_for must be 'goal_prob' or 'value_model' when collect_data is True"

    # Extract configurations
    n_players = game_config["N_PLAYERS"]
    n_actions = game_config["N_ACTIONS"]
    G = game_config["G"]
    country_idx2num_actions = game_config["country_idx2num_actions"]

    how = method_config["how_fallback"]
    is_random_variant = False
    n_sims = method_config["n_sims"]
    c_ucb = method_config["c_ucb"]
    n_turns = min(method_config.get("n_turns", n_players - 1), 10)
    k = method_config.get("k", 1)
    use_prior = method_config["use_prior"]

    max_iter_mcts = method_config.get("max_iter_mcts", float("inf"))

    max_changes = method_config["max_changes"]

    model = game_config.get("model", None)
    allowed_actions = game_config.get("allowed_actions", None)
    forbidden_actions = game_config.get("forbidden_actions", None)

    method_config_for_factory = method_config.copy()

    if how.endswith("_random"):
        is_random_variant = True
        base_how = how.replace("_random", "")  # e.g. "reward_random" -> "reward"
        method_config_for_factory["how_fallback"] = base_how

    # Create negotiation functions with method-specific parameters
    get_best_offer_fn = create_negotiation_functions(
        how=method_config_for_factory["how_fallback"],
        max_changes=max_changes,
        model=model,
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
        k=k,
    )

    # Initialize game state
    game = NegotiationState(
        n_players=n_players,
        n_actions=n_actions,
        n_turns=n_turns,
        G=G,
        sat_masks=sat_masks,
        country_idx2num_actions=country_idx2num_actions,
        seed=seed,
        binary_goals=game_config.get("binary_goals", []),
    )

    num_rejects = 0

    data_points_to_label = []
    value_features_buffer = []

    trace = []

    # Main game loop
    while not game.is_terminal():
        if how == "LLM_full":
            (
                best_partner_id,
                offer,
            ) = get_llm_decision(state=game)

        elif is_random_variant:
            # 1. Random Partner Selection [0, N-1]
            best_partner_id = np.random.randint(0, n_players)

            # 2. Use the standard heuristic (reward/lower/upper) for the Offer
            offer, _ = get_best_offer_fn(game, best_partner_id)

        else:
            # # Use MCTS to select best partner
            best_partner_id, tree = mcts_multi_ply(
                root_state=game,
                n_sims=n_sims,
                c_ucb=c_ucb,
                get_best_offer_fn=get_best_offer_fn,
                n_players=n_players,
                max_iter=max_iter_mcts,
                use_prior=use_prior,
            )

            # Find best offer
            offer, _ = get_best_offer_fn(game, best_partner_id)

        # if not game.is_terminal():
        #     if game.idx % 100 == 0 or game.idx == len(game.round_robin) - 1:
        #         # pass
        #         print(
        #             f" Turn {game.idx}/{len(game.round_robin)}: Proposer {game.proposer()} offered to {best_partner_id} - {'Accepted' if offer else 'Rejected'}"
        #         )
        #         print(f"Best partner id: {best_partner_id}")
        #         print(f"Offer: {offer}")
        # print(f"System prompt: {system_prompt}")
        # print(f"User prompt: {user_prompt}")
        # break

        trace.append(
            {
                "t": int(game.idx),
                "proposer": int(game.proposer()),
                "partner": int(best_partner_id)
                if best_partner_id is not None
                else None,
                "P_t": game.P.copy(),
                "accepted": bool(offer is not None),
                "action proposer": offer[
                    : game.country_idx2num_actions[game.proposer()]
                ]
                if offer
                else None,
                "action partner": offer[game.country_idx2num_actions[game.proposer()] :]
                if offer
                else None,
                # Optional: record current payoffs for later analysis
                "payoff_t": game.get_payoff_vector().copy().tolist(),
            }
        )

        # Execute or reject deal
        if offer:
            game.play_deal(offer, best_partner_id)
        else:
            game.reject_deal()
            num_rejects += 1

    # Collect results
    final_payoff = game.get_payoff_vector()

    final_payoff_zeroed = np.maximum(final_payoff, 0)
    product_payoff = np.prod(final_payoff_zeroed)
    product_payoff_log = np.log(final_payoff_zeroed + 1e-10).sum()

    # Check equilibrium
    is_equilibrium, regret_per_player = check_equilibrium(
        P=game.P,
        country_idx2num_actions=country_idx2num_actions,
        G=G,
        sat_masks=sat_masks,
    )

    results_dict = {
        "payoff_vector": final_payoff.tolist(),
        "sum_payoff": float(final_payoff.sum()),
        "product_payoff": float(product_payoff),
        "product_payoff(log)": float(product_payoff_log),
        "is_equilibrium": is_equilibrium,
        "regret_per_player": regret_per_player.tolist(),
        "sum_regret_per_player": float(regret_per_player.sum()),
        "final_P": game.P.tolist(),
        "game_round_robin": game.round_robin,
        "num_rejects": num_rejects,
        # "trace": trace,
    }

    if collect_data and collect_for == "value_model":
        return results_dict, value_features_buffer
    else:
        if collect_data:
            return results_dict, data_points_to_label
        else:
            return results_dict, None
