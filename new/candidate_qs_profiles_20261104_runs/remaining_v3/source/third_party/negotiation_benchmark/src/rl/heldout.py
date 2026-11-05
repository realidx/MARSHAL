"""
Held-out game-set generation and persistence for RL evaluation.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from config.game_configs import ScenarioProfile, create_sat_masks, generate_game_config


@dataclass(frozen=True)
class HeldOutGameSpec:
    """Specification for one held-out evaluation game."""

    game_name: str
    n_players: int
    n_actions_per_player: int
    n_goals: int
    k_factors: int
    structure_type: str
    binary_fraction: float
    complexity_zipf_a: float
    seed: int
    shift: str | None = "balanced"


def default_heldout_specs() -> list[HeldOutGameSpec]:
    """
    Build the fixed 12-game held-out set.

    Assumptions beyond the user's request:
    - 4 actions per player for every game
    - 2 cooperative and 2 adversarial games per player-count bucket
    - goal counts scale with player count: 8, 12, 16 for 3p, 5p, 7p
    - two binary fractions and two Zipf complexity settings for diversity
    """
    specs: list[HeldOutGameSpec] = []
    size_to_goals = {3: 8, 5: 12, 7: 16}
    size_to_k = {3: 3, 5: 4, 7: 5}
    scenario_grid = [
        ("cooperative", 0.15, 1.6),
        ("cooperative", 0.50, 3.0),
        ("adversarial", 0.15, 1.6),
        ("adversarial", 0.50, 3.0),
    ]

    for n_players in (3, 5, 7):
        for idx, (structure_type, binary_fraction, complexity_zipf_a) in enumerate(
            scenario_grid
        ):
            seed = (1000 * n_players) + idx
            specs.append(
                HeldOutGameSpec(
                    game_name=(
                        f"heldout_{n_players}p_{structure_type}"
                        f"_bf_{binary_fraction:.2f}_zipf_{complexity_zipf_a:.1f}"
                    ),
                    n_players=n_players,
                    n_actions_per_player=4,
                    n_goals=size_to_goals[n_players],
                    k_factors=size_to_k[n_players],
                    structure_type=structure_type,
                    binary_fraction=binary_fraction,
                    complexity_zipf_a=complexity_zipf_a,
                    seed=seed,
                    shift="balanced",
                )
            )

    return specs


def generate_heldout_games(specs: list[HeldOutGameSpec] | None = None) -> dict:
    """Generate the held-out game bundle."""
    specs = default_heldout_specs() if specs is None else specs
    games = []

    for spec in specs:
        profile = ScenarioProfile(
            structure_type=spec.structure_type,
            binary_fraction=spec.binary_fraction,
            complexity_zipf_a=spec.complexity_zipf_a,
        )
        game_config = generate_game_config(
            n_players=spec.n_players,
            country_idx2num_actions={
                i: spec.n_actions_per_player for i in range(spec.n_players)
            },
            n_goals=spec.n_goals,
            k_factors=spec.k_factors,
            seed=spec.seed,
            profile=profile,
            shift=spec.shift,
        )
        sat_masks = create_sat_masks(game_config)
        games.append(
            {
                "game_name": spec.game_name,
                "seed": spec.seed,
                "game_config": game_config,
                "sat_masks": sat_masks,
                "metadata": spec.__dict__.copy(),
            }
        )

    return {"games": games, "metadata": {"num_games": len(games)}}


def save_heldout_games(bundle: dict, path: str | Path) -> Path:
    """Persist the held-out set to a pickle file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle)
    return path


def load_heldout_games(path: str | Path) -> dict:
    """Load a previously saved held-out set."""
    with Path(path).open("rb") as handle:
        return pickle.load(handle)
