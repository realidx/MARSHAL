"""
RL adapters for negotiation games.

This package layers gym-style interfaces and helper utilities on top of the
existing negotiation mechanics without changing the core simulator semantics.
"""

from rl.env import NegotiationTurnEnv
from rl.eval import (
    evaluate_learned_model_on_heldout,
    evaluate_methods_on_heldout,
    summarize_evaluation_frame,
)
from rl.game_factory import ScenarioGameFactory
from rl.heldout import (
    default_heldout_specs,
    generate_heldout_games,
    load_heldout_games,
    save_heldout_games,
)
from rl.metrics import summarize_iteration
from rl.model import StageAwareActorCritic, TorchPolicyAdapter
from rl.policies import RandomMaskedPolicy
from rl.rfe_eval import build_rfe_planner_from_checkpoint, run_rfe_policy_game
from rl.rfe_model import (
    GreedyQPolicy,
    RFEExplorationPolicy,
    StageAwareQEnsemble,
    StageAwareQNetwork,
)
from rl.rfe_train_loop import RFETrainConfig, run_rfe_training
from rl.rollout import RolloutCollector
from rl.trainer import PPOTrainer
from rl.train_loop import TrainConfig, run_training

__all__ = [
    "NegotiationTurnEnv",
    "evaluate_learned_model_on_heldout",
    "evaluate_methods_on_heldout",
    "summarize_evaluation_frame",
    "ScenarioGameFactory",
    "default_heldout_specs",
    "generate_heldout_games",
    "load_heldout_games",
    "save_heldout_games",
    "StageAwareActorCritic",
    "TorchPolicyAdapter",
    "RandomMaskedPolicy",
    "StageAwareQNetwork",
    "StageAwareQEnsemble",
    "RFEExplorationPolicy",
    "GreedyQPolicy",
    "RFETrainConfig",
    "run_rfe_training",
    "build_rfe_planner_from_checkpoint",
    "run_rfe_policy_game",
    "RolloutCollector",
    "PPOTrainer",
    "summarize_iteration",
    "TrainConfig",
    "run_training",
]
