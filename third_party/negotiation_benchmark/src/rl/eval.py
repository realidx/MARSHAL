"""
Evaluation utilities for learned and heuristic negotiation baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from core.equilibrium import check_equilibrium
from experiments.runner import run_single_game
from rl.env import NegotiationTurnEnv
from rl.model import StageAwareActorCritic


@dataclass
class EvaluationResult:
    """One method-game evaluation record."""

    method: str
    game_name: str
    n_players: int
    structure_type: str
    payoff_vector: list[float]
    sum_payoff: float
    is_equilibrium: bool
    num_rejects: int


def default_heuristic_method_configs() -> list[dict]:
    """Heuristic baselines to compare against the learned policy."""
    return [
        {
            "name": "reward",
            "how_fallback": "reward",
            "n_sims": 50,
            "c_ucb": 10.0,
            "use_prior": False,
            "max_changes": 2,
            "n_turns": 5,
            "dp_k": 0,
        },
    ]


def filter_heldout_games(
    heldout_bundle: dict,
    *,
    n_players: int | None = None,
    structure_type: str | None = None,
) -> dict:
    """Return a filtered held-out bundle without mutating the original."""
    games = heldout_bundle["games"]
    filtered = []

    for game in games:
        metadata = game["metadata"]
        if n_players is not None and metadata["n_players"] != n_players:
            continue
        if structure_type is not None and metadata["structure_type"] != structure_type:
            continue
        filtered.append(game)

    return {"games": filtered, "metadata": {"num_games": len(filtered)}}


class GreedyTorchPolicyAdapter:
    """Deterministic evaluation policy using argmax over masked logits."""

    def __init__(self, model: StageAwareActorCritic):
        self.model = model

    def act(self, observation: dict) -> dict:
        self.model.eval()
        with torch.no_grad():
            dist = self.model.action_distribution(observation)
            value = self.model.value(observation)
            action = torch.argmax(dist.logits).reshape(())
        return {
            "action": int(action.item()),
            "value": float(value.reshape(-1)[0].item()),
            "log_prob": float(dist.log_prob(action).item()),
        }


def build_model_from_checkpoint(checkpoint_path: str | Path, sample_observation: dict):
    """Load a trained model from checkpoint using one observation for shape inference."""
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    config = checkpoint["config"]
    model = StageAwareActorCritic(
        player_feature_dim=sample_observation["player_features"].shape[1],
        max_players=sample_observation["player_features"].shape[0],
        max_candidate_offers=sample_observation["offer_actions"].shape[0],
        offer_feature_dim=sample_observation["offer_actions"].shape[1],
        hidden_dim=config["hidden_dim"],
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def run_learned_policy_game(
    *,
    game_config: dict,
    sat_masks: dict,
    model: StageAwareActorCritic,
    seed: int,
    n_turns: int = 5,
    max_candidate_offers: int = 1024,
    max_changes: int = 2,
) -> dict:
    """Run one full game using the learned policy via the staged env."""
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
    policy = GreedyTorchPolicyAdapter(model)
    done = False
    num_rejects = 0

    while not done:
        stage = int(observation["stage"][0])
        step = policy.act(observation)
        if stage == 1 and step["action"] == 0:
            num_rejects += 1
        observation, _, terminated, truncated, _ = env.step(step["action"])
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


def evaluate_learned_model_on_heldout(
    *,
    heldout_bundle: dict,
    model: StageAwareActorCritic,
    filter_n_players: int | None = None,
    filter_structure_type: str | None = None,
    n_turns: int = 5,
    max_candidate_offers: int = 1024,
    max_changes: int = 2,
) -> pd.DataFrame:
    """Evaluate only the learned policy on a filtered held-out bundle."""
    heldout_bundle = filter_heldout_games(
        heldout_bundle,
        n_players=filter_n_players,
        structure_type=filter_structure_type,
    )
    games = heldout_bundle["games"]
    if not games:
        raise ValueError("No held-out games matched the requested filters.")

    rows = []
    for game_entry in games:
        game_config = game_entry["game_config"]
        sat_masks = game_entry["sat_masks"]
        seed = game_entry["seed"]
        metadata = game_entry["metadata"]

        learned_result = run_learned_policy_game(
            game_config=game_config,
            sat_masks=sat_masks,
            model=model,
            seed=seed,
            n_turns=n_turns,
            max_candidate_offers=max_candidate_offers,
            max_changes=max_changes,
        )
        rows.append(
            EvaluationResult(
                method="ppo_learned",
                game_name=game_entry["game_name"],
                n_players=metadata["n_players"],
                structure_type=metadata["structure_type"],
                payoff_vector=learned_result["payoff_vector"],
                sum_payoff=learned_result["sum_payoff"],
                is_equilibrium=learned_result["is_equilibrium"],
                num_rejects=learned_result["num_rejects"],
            ).__dict__
        )

    return pd.DataFrame(rows)


def evaluate_methods_on_heldout(
    *,
    heldout_bundle: dict,
    checkpoint_path: str | Path,
    heuristic_method_configs: list[dict] | None = None,
    filter_n_players: int | None = None,
    filter_structure_type: str | None = None,
    n_turns: int = 5,
    max_candidate_offers: int = 1024,
    max_changes: int = 2,
) -> pd.DataFrame:
    """Evaluate the learned policy and heuristic baselines on the held-out set."""
    heuristic_method_configs = (
        default_heuristic_method_configs()
        if heuristic_method_configs is None
        else heuristic_method_configs
    )
    heldout_bundle = filter_heldout_games(
        heldout_bundle,
        n_players=filter_n_players,
        structure_type=filter_structure_type,
    )
    games = heldout_bundle["games"]
    if not games:
        raise ValueError("No held-out games matched the requested filters.")
    first_game = games[0]
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    checkpoint_config = checkpoint["config"]
    sample_env = NegotiationTurnEnv(
        max_players=checkpoint_config["max_players_supported"],
        max_actions=checkpoint_config["max_actions_supported"],
        max_candidate_offers=checkpoint_config["max_candidate_offers"],
        max_changes=checkpoint_config["max_changes"],
        max_goal_slots=checkpoint_config["max_goal_slots"],
        allow_self_partner=False,
        game_config=first_game["game_config"],
        sat_masks=first_game["sat_masks"],
    )
    sample_observation, _ = sample_env.reset(
        seed=first_game["seed"],
        options={
            "game_config": first_game["game_config"],
            "sat_masks": first_game["sat_masks"],
            "n_turns": n_turns,
            "state_seed": first_game["seed"],
        },
    )
    model, _ = build_model_from_checkpoint(checkpoint_path, sample_observation)

    rows = []
    for game_entry in games:
        game_config = game_entry["game_config"]
        sat_masks = game_entry["sat_masks"]
        seed = game_entry["seed"]
        metadata = game_entry["metadata"]

        learned_result = run_learned_policy_game(
            game_config=game_config,
            sat_masks=sat_masks,
            model=model,
            seed=seed,
            n_turns=n_turns,
            max_candidate_offers=max_candidate_offers,
            max_changes=max_changes,
        )
        rows.append(
            EvaluationResult(
                method="ppo_learned",
                game_name=game_entry["game_name"],
                n_players=metadata["n_players"],
                structure_type=metadata["structure_type"],
                payoff_vector=learned_result["payoff_vector"],
                sum_payoff=learned_result["sum_payoff"],
                is_equilibrium=learned_result["is_equilibrium"],
                num_rejects=learned_result["num_rejects"],
            ).__dict__
        )

        for method_config in heuristic_method_configs:
            result, _ = run_single_game(
                game_config=game_config,
                sat_masks=sat_masks,
                method_config=method_config,
                seed=seed,
            )
            rows.append(
                EvaluationResult(
                    method=method_config["name"],
                    game_name=game_entry["game_name"],
                    n_players=metadata["n_players"],
                    structure_type=metadata["structure_type"],
                    payoff_vector=result["payoff_vector"],
                    sum_payoff=result["sum_payoff"],
                    is_equilibrium=result["is_equilibrium"],
                    num_rejects=result["num_rejects"],
                ).__dict__
            )

    return pd.DataFrame(rows)


def summarize_evaluation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate held-out evaluation results by method."""
    return (
        frame.groupby("method")
        .agg(
            mean_sum_payoff=("sum_payoff", "mean"),
            mean_num_rejects=("num_rejects", "mean"),
            equilibrium_rate=("is_equilibrium", "mean"),
        )
        .reset_index()
        .sort_values("mean_sum_payoff", ascending=False)
    )
