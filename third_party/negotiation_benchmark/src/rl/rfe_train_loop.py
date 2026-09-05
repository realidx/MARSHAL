"""
Two-phase reward-free exploration baseline inspired by GFA-RFE.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.game_configs import ScenarioProfile
from rl.env import NegotiationTurnEnv
from rl.game_factory import ScenarioGameFactory
from rl.rfe_model import RFEExplorationPolicy, StageAwareQEnsemble, StageAwareQNetwork
from rl.rfe_replay import (
    RFEReplayBuffer,
    assign_terminal_planning_targets,
    make_rfe_transition,
)
from rl.rfe_trainer import OfflinePlanningTrainer, RFEExplorationTrainer
from rl.rollout import RolloutCollector
from rl.train_loop import resolve_device


@dataclass
class RFETrainConfig:
    """Configuration for reward-free exploration plus offline planning."""

    exploration_episodes: int = 32
    max_steps_per_episode: int | None = None
    replay_capacity: int = 50_000
    warmup_transitions: int = 128
    exploration_updates_per_step: int = 1
    exploration_batch_size: int = 128
    offline_planning_epochs: int = 25
    offline_minibatch_size: int = 128
    learning_rate: float = 1e-4
    planner_learning_rate: float = 3e-4
    gamma: float = 0.99
    beta: float = 1.0
    epsilon: float = 0.2
    target_tau: float = 0.01
    variance_floor: float = 1e-4
    max_weight: float = 100.0
    ensemble_size: int = 10
    hidden_dim: int = 128
    max_players_supported: int = 7
    max_actions_supported: int = 4
    max_goal_slots: int = 16
    max_candidate_offers: int = 1024
    max_changes: int = 2
    output_dir: str = "artifacts/rl_runs/gfa_rfe"
    seed: int = 7
    n_players: int = 4
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

    def __post_init__(self):
        if self.n_turns is None:
            self.n_turns = self.n_players * 2


def build_rfe_factory(config: RFETrainConfig) -> ScenarioGameFactory:
    """Create a scenario-sampling helper for RFE."""
    profile = ScenarioProfile(
        structure_type=config.structure_type,
        binary_fraction=config.binary_fraction,
        complexity_zipf_a=config.complexity_zipf_a,
    )
    return ScenarioGameFactory(
        n_players=config.n_players,
        country_idx2num_actions={
            i: config.actions_per_player for i in range(config.n_players)
        },
        n_goals=config.n_goals,
        k_factors=config.k_factors,
        profile=profile,
        shift=config.shift,
        inject_pp=config.inject_pp,
    )


def build_rfe_env_from_sample(
    *,
    game_config: dict,
    sat_masks: dict,
    config: RFETrainConfig,
) -> NegotiationTurnEnv:
    """Instantiate the staged env for one RFE sample."""
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


def _model_config_from_observation(observation: dict, env, config: RFETrainConfig) -> dict:
    """Infer staged Q-network dimensions from one env observation."""
    return {
        "player_feature_dim": observation["player_features"].shape[1],
        "max_players": env.max_players,
        "max_candidate_offers": env.max_candidate_offers,
        "offer_feature_dim": observation["offer_actions"].shape[1],
        "hidden_dim": config.hidden_dim,
    }


def _episode_reset_options(
    *,
    factory: ScenarioGameFactory,
    config: RFETrainConfig,
    episode_idx: int,
) -> tuple[int, dict]:
    """Sample a fresh game and return reset options."""
    game_seed = config.seed + (episode_idx * 10_000)
    game_config, sat_masks = factory.sample(seed=game_seed)
    return game_seed, {
        "game_config": game_config,
        "sat_masks": sat_masks,
        "n_turns": config.n_turns,
        "state_seed": game_seed,
    }


def collect_reward_free_episode(
    *,
    env: NegotiationTurnEnv,
    policy: RFEExplorationPolicy,
    replay: RFEReplayBuffer,
    trainer: RFEExplorationTrainer,
    config: RFETrainConfig,
    episode_idx: int,
    seed: int,
    reset_options: dict,
) -> dict:
    """Collect one episode and update the exploration ensemble from replay."""
    observation, _ = env.reset(seed=seed, options=reset_options)
    done = False
    timestep = 0
    episode_transitions = []
    update_stats = []
    random_actions = 0

    while not done:
        stage = int(observation["stage"][0])
        acting_player = int(observation["acting_player"][0])
        policy_step = policy.act(observation)
        next_observation, _, terminated, truncated, info = env.step(policy_step.action)
        done = bool(terminated or truncated)

        transition = make_rfe_transition(
            observation=observation,
            action=policy_step.action,
            next_observation=next_observation,
            done=done,
            stage=stage,
            acting_player=acting_player,
            episode_id=episode_idx,
            timestep=timestep,
            q_value=policy_step.q_value,
            uncertainty=policy_step.uncertainty,
            random_action=policy_step.random_action,
        )
        replay.add(transition)
        episode_transitions.append(transition)
        random_actions += int(policy_step.random_action)

        if len(replay) >= config.warmup_transitions:
            for _ in range(config.exploration_updates_per_step):
                update_stats.append(
                    trainer.update(replay, batch_size=config.exploration_batch_size)
                )

        observation = next_observation
        timestep += 1
        if config.max_steps_per_episode is not None and timestep >= config.max_steps_per_episode:
            break

    terminal_payoff_vector = info.get(
        "terminal_payoff_vector", env.game.get_payoff_vector()
    )
    normalization_scale = RolloutCollector._compute_payoff_normalization_scale(env.game)
    assign_terminal_planning_targets(
        episode_transitions,
        terminal_payoff_vector=terminal_payoff_vector,
        payoff_normalization_scale=normalization_scale,
    )

    mean_update_loss = None
    mean_uncertainty = None
    if update_stats:
        mean_update_loss = float(np.mean([stat.mean_loss for stat in update_stats]))
        mean_uncertainty = float(
            np.mean([stat.mean_uncertainty for stat in update_stats])
        )

    return {
        "episode": episode_idx,
        "num_steps": len(episode_transitions),
        "replay_size": len(replay),
        "terminal_sum_payoff": float(np.asarray(terminal_payoff_vector).sum()),
        "mean_transition_uncertainty": float(
            np.mean([transition.uncertainty for transition in episode_transitions])
        ),
        "random_action_rate": random_actions / max(1, len(episode_transitions)),
        "num_exploration_updates": len(update_stats),
        "mean_exploration_loss": mean_update_loss,
        "mean_update_uncertainty": mean_uncertainty,
    }


def save_rfe_checkpoint(
    *,
    output_dir: Path,
    config: RFETrainConfig,
    history: list[dict],
    ensemble: StageAwareQEnsemble,
    planner_model: StageAwareQNetwork,
    planner_stats,
    planner_model_config: dict,
):
    """Persist the RFE ensemble, planner, config, and history."""
    checkpoint = {
        "config": asdict(config),
        "history": history,
        "planner_stats": asdict(planner_stats),
        "ensemble_state_dict": ensemble.state_dict(),
        "planner_state_dict": planner_model.state_dict(),
        "planner_model_config": planner_model_config,
    }
    checkpoint_path = output_dir / "rfe_checkpoint_latest.pt"
    torch.save(checkpoint, checkpoint_path)

    summary_path = output_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "config": asdict(config),
                "history_path": str((output_dir / "history.json").resolve()),
                "latest_checkpoint": str(checkpoint_path.resolve()),
                "planner_mean_loss": float(planner_stats.mean_loss),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_rfe_training(config: RFETrainConfig) -> dict:
    """Run reward-free exploration first, then offline planning."""
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)

    device = resolve_device(config.device)
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    factory = build_rfe_factory(config)
    init_game_config, init_sat_masks = factory.sample(seed=config.seed)
    env = build_rfe_env_from_sample(
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
    model_config = _model_config_from_observation(initial_observation, env, config)

    ensemble = StageAwareQEnsemble(
        ensemble_size=config.ensemble_size,
        **model_config,
    ).to(device)
    replay = RFEReplayBuffer(
        config.replay_capacity, rng=np.random.default_rng(config.seed)
    )
    policy = RFEExplorationPolicy(
        ensemble,
        epsilon=config.epsilon,
        beta=config.beta,
        rng=np.random.default_rng(config.seed + 1),
    )
    exploration_trainer = RFEExplorationTrainer(
        ensemble,
        learning_rate=config.learning_rate,
        gamma=config.gamma,
        beta=config.beta,
        target_tau=config.target_tau,
        variance_floor=config.variance_floor,
        max_weight=config.max_weight,
        device=device,
    )

    history: list[dict] = []
    for episode_idx in range(config.exploration_episodes):
        seed, reset_options = _episode_reset_options(
            factory=factory,
            config=config,
            episode_idx=episode_idx,
        )
        metrics = collect_reward_free_episode(
            env=env,
            policy=policy,
            replay=replay,
            trainer=exploration_trainer,
            config=config,
            episode_idx=episode_idx,
            seed=seed,
            reset_options=reset_options,
        )
        history.append(metrics)
        print(
            f"[rfe explore {episode_idx:03d}] "
            f"steps={metrics['num_steps']} "
            f"replay={metrics['replay_size']} "
            f"sum_payoff={metrics['terminal_sum_payoff']:.4f} "
            f"mean_uncertainty={metrics['mean_transition_uncertainty']:.4f} "
            f"random_rate={metrics['random_action_rate']:.3f} "
            f"updates={metrics['num_exploration_updates']}"
        )

        history_path = output_dir / "history.json"
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    planner_model = StageAwareQNetwork(**model_config).to(device)
    planner_optimizer = torch.optim.Adam(
        planner_model.parameters(), lr=config.planner_learning_rate
    )
    planner_trainer = OfflinePlanningTrainer(
        planner_model, planner_optimizer, device=device
    )
    planner_stats = planner_trainer.update(
        replay.as_list(),
        epochs=config.offline_planning_epochs,
        minibatch_size=config.offline_minibatch_size,
    )
    print(
        "[rfe offline] "
        f"transitions={planner_stats.num_transitions} "
        f"minibatches={planner_stats.num_minibatches} "
        f"loss={planner_stats.mean_loss:.6f}"
    )

    save_rfe_checkpoint(
        output_dir=output_dir,
        config=config,
        history=history,
        ensemble=ensemble,
        planner_model=planner_model,
        planner_stats=planner_stats,
        planner_model_config=model_config,
    )
    print(f"RFE artifacts written to: {output_dir.resolve()}")

    return {
        "config": config,
        "history": history,
        "output_dir": output_dir,
        "ensemble": ensemble,
        "planner_model": planner_model,
        "planner_stats": planner_stats,
        "device": str(device),
    }


def main():
    config = RFETrainConfig()
    run_rfe_training(config)


if __name__ == "__main__":
    main()
