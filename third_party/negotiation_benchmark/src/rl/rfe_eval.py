"""
Evaluation helpers for reward-free exploration baselines.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from core.equilibrium import check_equilibrium
from rl.env import NegotiationTurnEnv
from rl.rfe_model import GreedyQPolicy, StageAwareQNetwork


def build_rfe_planner_from_checkpoint(checkpoint_path: str | Path):
    """Load the offline-planned Q policy from an RFE checkpoint."""
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    model_config = checkpoint["planner_model_config"]
    model = StageAwareQNetwork(**model_config)
    model.load_state_dict(checkpoint["planner_state_dict"])
    model.eval()
    return model, checkpoint


def run_rfe_policy_game(
    *,
    game_config: dict,
    sat_masks: dict,
    model: StageAwareQNetwork,
    seed: int,
    n_turns: int = 5,
    max_candidate_offers: int = 1024,
    max_changes: int = 2,
) -> dict:
    """Run one full game using a greedily planned RFE Q policy."""
    max_actions_supported = (model.offer_feature_dim - 1) // 2
    max_goal_slots = (model.player_feature_dim - 2) // 9
    env = NegotiationTurnEnv(
        max_players=model.max_players,
        max_actions=max_actions_supported,
        max_candidate_offers=max_candidate_offers,
        max_changes=max_changes,
        max_goal_slots=max_goal_slots,
        allow_self_partner=False,
        game_config=game_config,
        sat_masks=sat_masks,
    )
    observation, _ = env.reset(
        seed=seed,
        options={
            "game_config": game_config,
            "sat_masks": sat_masks,
            "n_turns": n_turns,
            "state_seed": seed,
        },
    )
    policy = GreedyQPolicy(model)
    done = False
    num_rejects = 0

    while not done:
        stage = int(observation["stage"][0])
        step = policy.act(observation)
        if stage == 1 and step.action == 0:
            num_rejects += 1
        observation, _, terminated, truncated, _ = env.step(step.action)
        done = bool(terminated or truncated)

    final_payoff = env.game.get_payoff_vector()
    is_equilibrium, regret_per_player = check_equilibrium(
        P=env.game.P,
        country_idx2num_actions=env.game.country_idx2num_actions,
        G=env.game.G,
        sat_masks=env.game.sat_masks,
    )
    return {
        "payoff_vector": final_payoff.tolist(),
        "sum_payoff": float(final_payoff.sum()),
        "product_payoff": float(np.prod(np.maximum(final_payoff, 0))),
        "product_payoff(log)": float(np.log(np.maximum(final_payoff, 0) + 1e-10).sum()),
        "is_equilibrium": bool(is_equilibrium),
        "regret_per_player": regret_per_player.tolist(),
        "sum_regret_per_player": float(regret_per_player.sum()),
        "final_P": env.game.P.tolist(),
        "game_round_robin": env.game.round_robin,
        "num_rejects": num_rejects,
    }
