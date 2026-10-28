"""
Minimal iterative training loop for staged negotiation PPO.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.game_configs import ScenarioProfile
from rl.env import NegotiationTurnEnv
from rl.eval import evaluate_learned_model_on_heldout
from rl.game_factory import ScenarioGameFactory
from rl.heldout import generate_heldout_games, load_heldout_games
from rl.metrics import summarize_iteration
from rl.model import StageAwareActorCritic, TorchPolicyAdapter
from rl.rollout import RolloutCollector
from rl.trainer import PPOTrainer


@dataclass
class TrainConfig:
    """Training-loop configuration."""

    episodes_per_iteration: int = 8
    ppo_epochs: int = 4
    minibatch_size: int = 64
    learning_rate: float = 3e-4
    hidden_dim: int = 128
    max_players_supported: int = 7
    max_actions_supported: int = 4
    max_goal_slots: int = 16
    max_candidate_offers: int = 1024
    max_changes: int = 2
    checkpoint_every: int = 1
    output_dir: str = "artifacts/rl_runs/staged_ppo"
    seed: int = 7
    n_players: int = 4
    num_iterations: int = 20
    actions_per_player: int = 4
    n_goals: int = 16
    k_factors: int = 5
    n_turns: int | None = None
    structure_type: str = "adversarial"
    binary_fraction: float = 0.3
    complexity_zipf_a: float = 1.6
    shift: str | None = "balanced"
    inject_pp: bool = False
    device: str = "auto"
    eval_every_k_iterations: int = 0
    heldout_bundle_path: str = "games/heldout_eval_set.pkl"
    heldout_eval_n_players: int = 5

    def __post_init__(self):
        if self.n_turns is None:
            self.n_turns = self.n_players * 2


def build_factory(config: TrainConfig) -> ScenarioGameFactory:
    """Create the scenario-sampling helper."""
    profile = ScenarioProfile(
        structure_type=config.structure_type,
        binary_fraction=config.binary_fraction,
        complexity_zipf_a=config.complexity_zipf_a,
    )
    return ScenarioGameFactory(
        n_players=config.n_players,
        country_idx2num_actions={i: config.actions_per_player for i in range(config.n_players)},
        n_goals=config.n_goals,
        k_factors=config.k_factors,
        profile=profile,
        shift=config.shift,
        inject_pp=config.inject_pp,
    )


def build_env_from_sample(
    *,
    game_config: dict,
    sat_masks: dict,
    config: TrainConfig,
) -> NegotiationTurnEnv:
    """Instantiate the staged env around one sampled game."""
    return NegotiationTurnEnv(
        max_players=config.max_players_supported,
        max_actions=config.max_actions_supported,
        max_candidate_offers=config.max_candidate_offers,
        max_changes=config.max_changes,
        max_goal_slots=config.max_goal_slots,
        allow_self_partner=False,
        game_config=game_config,
        sat_masks=sat_masks,
    )


def make_reset_options_fn(factory: ScenarioGameFactory, config: TrainConfig, iteration: int):
    """Return a reset-options callback that resamples a fresh game per episode."""

    def reset_options_fn(episode_idx: int) -> dict:
        game_seed = config.seed + (iteration * 10_000) + episode_idx
        game_config, sat_masks = factory.sample(seed=game_seed)
        return {
            "game_config": game_config,
            "sat_masks": sat_masks,
            "n_turns": config.n_turns,
            "state_seed": game_seed,
        }

    return reset_options_fn


def save_checkpoint(
    *,
    output_dir: Path,
    iteration: int,
    model,
    optimizer,
    history: list[dict],
    config: TrainConfig,
):
    """Persist model, optimizer, config, and metric history."""
    checkpoint = {
        "iteration": iteration,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "history": history,
        "config": config.__dict__,
    }
    checkpoint_path = output_dir / f"checkpoint_iter_{iteration:04d}.pt"
    torch.save(checkpoint, checkpoint_path)
    latest_path = output_dir / "checkpoint_latest.pt"
    torch.save(checkpoint, latest_path)


def resolve_device(device: str) -> torch.device:
    """Resolve a training device from config."""
    if device == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device)


def run_training(config: TrainConfig) -> dict:
    """Run the iterative training loop and return the main artifacts."""
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)

    device = resolve_device(config.device)

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    factory = build_factory(config)
    init_game_config, init_sat_masks = factory.sample(seed=config.seed)
    env = build_env_from_sample(
        game_config=init_game_config,
        sat_masks=init_sat_masks,
        config=config,
    )

    initial_observation, _ = env.reset(
        seed=config.seed,
        options={
            "game_config": init_game_config,
            "sat_masks": init_sat_masks,
            "n_turns": config.n_turns,
            "state_seed": config.seed,
        },
    )

    model = StageAwareActorCritic(
        player_feature_dim=initial_observation["player_features"].shape[1],
        max_players=env.max_players,
        max_candidate_offers=env.max_candidate_offers,
        offer_feature_dim=initial_observation["offer_actions"].shape[1],
        hidden_dim=config.hidden_dim,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    policy = TorchPolicyAdapter(model)
    collector = RolloutCollector(env, policy)
    trainer = PPOTrainer(model, optimizer, device=device)

    heldout_bundle = None
    if config.eval_every_k_iterations > 0:
        heldout_path = Path(config.heldout_bundle_path)
        heldout_bundle = (
            load_heldout_games(heldout_path)
            if heldout_path.exists()
            else generate_heldout_games()
        )

    history: list[dict] = []

    for iteration in range(config.num_iterations):
        reset_options_fn = make_reset_options_fn(factory, config, iteration)
        episodes = collector.collect_episodes(
            config.episodes_per_iteration,
            seed_fn=lambda episode_idx: config.seed + (iteration * 1_000) + episode_idx,
            reset_options_fn=reset_options_fn,
        )
        transitions = collector.flatten_episodes(episodes)
        train_stats = trainer.update(
            transitions,
            ppo_epochs=config.ppo_epochs,
            minibatch_size=config.minibatch_size,
        )
        metrics = summarize_iteration(iteration, episodes, train_stats)
        metrics_dict = metrics.to_dict()

        if config.eval_every_k_iterations > 0 and iteration % config.eval_every_k_iterations == 0:
            heldout_frame = evaluate_learned_model_on_heldout(
                heldout_bundle=heldout_bundle,
                model=model,
                filter_n_players=config.heldout_eval_n_players,
                n_turns=config.n_turns,
                max_candidate_offers=config.max_candidate_offers,
                max_changes=config.max_changes,
            )
            metrics_dict["heldout_mean_sum_payoff"] = float(
                heldout_frame["sum_payoff"].mean()
            )
        else:
            metrics_dict["heldout_mean_sum_payoff"] = None

        history.append(metrics_dict)

        heldout_suffix = ""
        if metrics_dict["heldout_mean_sum_payoff"] is not None:
            heldout_suffix = (
                f" heldout_welfare={metrics_dict['heldout_mean_sum_payoff']:.4f}"
            )
        print(
            f"[iter {iteration:03d}] "
            f"episodes={metrics.num_episodes} "
            f"transitions={metrics.num_transitions} "
            f"mean_raw_welfare={metrics.mean_raw_social_welfare:.4f} "
            f"mean_norm_welfare={metrics.mean_normalized_social_welfare:.4f} "
            f"value_loss={metrics.ppo_mean_value_loss:.4f} "
            f"entropy={metrics.ppo_mean_entropy:.4f}"
            f"{heldout_suffix}"
        )

        if (iteration + 1) % config.checkpoint_every == 0:
            save_checkpoint(
                output_dir=output_dir,
                iteration=iteration,
                model=model,
                optimizer=optimizer,
                history=history,
                config=config,
            )

        history_path = output_dir / "history.json"
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    summary_path = output_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "config": config.__dict__,
                "history_path": str((output_dir / "history.json").resolve()),
                "latest_checkpoint": str((output_dir / "checkpoint_latest.pt").resolve()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Training artifacts written to: {output_dir.resolve()}")
    return {
        "config": config,
        "history": history,
        "output_dir": output_dir,
        "model": model,
        "optimizer": optimizer,
        "device": str(device),
    }


def main():
    config = TrainConfig()
    run_training(config)


if __name__ == "__main__":
    main()
