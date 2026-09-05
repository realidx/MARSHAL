"""
Helpers for building negotiation games for RL experiments.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.game_configs import ScenarioProfile, create_sat_masks, generate_game_config


@dataclass
class ScenarioGameFactory:
    """Small helper for repeatedly sampling configs from one scenario family."""

    n_players: int
    country_idx2num_actions: dict
    n_goals: int
    k_factors: int
    profile: ScenarioProfile
    shift: str | None = None
    inject_pp: bool = False

    def sample(self, seed: int) -> tuple[dict, dict]:
        """Generate ``(game_config, sat_masks)`` for one seed."""
        game_config = generate_game_config(
            n_players=self.n_players,
            country_idx2num_actions=self.country_idx2num_actions,
            n_goals=self.n_goals,
            k_factors=self.k_factors,
            seed=seed,
            profile=self.profile,
            shift=self.shift,
            inject_pp=self.inject_pp,
        )
        sat_masks = create_sat_masks(game_config)
        return game_config, sat_masks
