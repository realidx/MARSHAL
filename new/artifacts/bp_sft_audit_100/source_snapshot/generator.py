"""Deterministic random instance generation for BENAC-P v0."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from benac_p.schema import ActionRef, GameSpec, Goal


@dataclass(frozen=True)
class GeneratorConfig:
    """Configuration for the bounded-resampling game generator."""

    n_players: int = 3
    actions_per_player: int = 3
    n_goals: int = 8
    n_rounds: int = 4
    max_changes: int = 1
    goal_arities: tuple[int, ...] = (2, 3)
    goal_arity_probs: tuple[float, ...] | None = None
    # Probability order: WANT, NEUTRAL, AVOID.
    preference_probs: tuple[float, float, float] = (0.4, 0.2, 0.4)
    max_attempts: int = 1_000

    def __post_init__(self) -> None:
        if self.n_players == 2 and self.goal_arities == (2, 3) and self.goal_arity_probs is None:
            # The documented default is uniform over 2/3-player goals.  With
            # only two players, retain the same intent by using the only
            # feasible arity instead of making the common small-game config
            # fail validation.
            object.__setattr__(self, "goal_arities", (2,))
        if self.n_players < 2:
            raise ValueError("n_players must be at least two.")
        if self.actions_per_player < 1:
            raise ValueError("actions_per_player must be positive.")
        if self.n_goals < 1:
            raise ValueError("n_goals must be positive.")
        if self.n_rounds < 1:
            raise ValueError("n_rounds must be positive.")
        if self.max_changes < 1:
            raise ValueError("max_changes must be positive.")
        if not self.goal_arities:
            raise ValueError("goal_arities cannot be empty.")
        if any(arity < 2 or arity > self.n_players for arity in self.goal_arities):
            raise ValueError("Every goal arity must be between two and n_players.")
        if self.goal_arity_probs is not None:
            if len(self.goal_arity_probs) != len(self.goal_arities):
                raise ValueError("goal_arity_probs must align with goal_arities.")
            _validate_probabilities(self.goal_arity_probs, "goal_arity_probs")
        _validate_probabilities(self.preference_probs, "preference_probs")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive.")


def _validate_probabilities(values: Iterable[float], name: str) -> None:
    probabilities = np.asarray(tuple(values), dtype=float)
    if probabilities.ndim != 1 or len(probabilities) == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence.")
    if np.any(probabilities < 0) or not np.isclose(probabilities.sum(), 1.0):
        raise ValueError(f"{name} must be non-negative and sum to one.")


def _connected(n_players: int, goals: tuple[Goal, ...]) -> bool:
    """Return whether the player projection of the goal hypergraph is connected."""

    neighbors = [set() for _ in range(n_players)]
    for goal in goals:
        players = {action.player_id for action in goal.required_actions}
        for player in players:
            neighbors[player].update(players - {player})

    reached = {0}
    frontier = [0]
    while frontier:
        player = frontier.pop()
        for neighbor in neighbors[player]:
            if neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)
    return len(reached) == n_players


def _sample_goals(rng: np.random.Generator, config: GeneratorConfig) -> tuple[Goal, ...] | None:
    arity_probabilities = config.goal_arity_probs
    if arity_probabilities is None:
        arity_probabilities = tuple(1.0 / len(config.goal_arities) for _ in config.goal_arities)

    goals: list[Goal] = []
    seen_requirements: set[frozenset[ActionRef]] = set()
    for goal_id in range(config.n_goals):
        created = False
        for _ in range(config.max_attempts):
            arity = int(rng.choice(config.goal_arities, p=arity_probabilities))
            players = sorted(
                int(player)
                for player in rng.choice(config.n_players, size=arity, replace=False)
            )
            requirements = tuple(
                sorted(
                    ActionRef(player_id=player, action_id=int(rng.integers(config.actions_per_player)))
                    for player in players
                )
            )
            requirement_key = frozenset(requirements)
            if requirement_key in seen_requirements:
                continue
            seen_requirements.add(requirement_key)
            goals.append(Goal(goal_id=goal_id, required_actions=requirements))
            created = True
            break
        if not created:
            return None

    candidate = tuple(goals)
    if not _connected(config.n_players, candidate):
        return None
    participation = {player: 0 for player in range(config.n_players)}
    for goal in candidate:
        for action in goal.required_actions:
            participation[action.player_id] += 1
    if any(count == 0 for count in participation.values()):
        return None
    return candidate


def _sample_preferences(rng: np.random.Generator, config: GeneratorConfig) -> np.ndarray | None:
    # preference_probs follows the public order WANT, NEUTRAL, AVOID.
    values = np.asarray((1, 0, -1), dtype=np.int8)
    preferences = rng.choice(
        values,
        size=(config.n_players, config.n_goals),
        p=config.preference_probs,
    ).astype(np.int8)
    if np.any(np.all(preferences != 1, axis=1)):
        return None
    if np.any(np.all(preferences == 0, axis=0)):
        return None
    return preferences


def _config_dict(config: GeneratorConfig) -> dict[str, object]:
    values = asdict(config)
    values["goal_arities"] = list(config.goal_arities)
    if config.goal_arity_probs is not None:
        values["goal_arity_probs"] = list(config.goal_arity_probs)
    values["preference_probs"] = list(config.preference_probs)
    return values


def generate_game(seed: int = 0, config: GeneratorConfig | None = None) -> GameSpec:
    """Generate one valid game instance using a deterministic RNG seed.

    The generator resamples only the random objects that are constrained by
    the v0 validity rules.  It never silently relaxes a constraint; failure
    after ``max_attempts`` is reported with the configuration that caused it.
    """

    config = config or GeneratorConfig()
    rng = np.random.default_rng(seed)
    for _ in range(config.max_attempts):
        goals = _sample_goals(rng, config)
        if goals is None:
            continue
        preferences = _sample_preferences(rng, config)
        if preferences is None:
            continue

        schedule = tuple(
            int(player)
            for _round in range(config.n_rounds)
            for player in rng.permutation(config.n_players)
        )
        graph_edges = sorted(
            {
                tuple(sorted((left, right)))
                for goal in goals
                for left in {action.player_id for action in goal.required_actions}
                for right in {action.player_id for action in goal.required_actions}
                if left < right
            }
        )
        action_coverage = [0] * (config.n_players * config.actions_per_player)
        for goal in goals:
            for action in goal.required_actions:
                action_coverage[action.player_id * config.actions_per_player + action.action_id] += 1

        metadata = {
            "generator": "benac_p.v0",
            "connected": True,
            "goal_player_edges": [list(edge) for edge in graph_edges],
            "action_coverage": [
                action_coverage[player * config.actions_per_player : (player + 1) * config.actions_per_player]
                for player in range(config.n_players)
            ],
            "config": _config_dict(config),
        }
        return GameSpec(
            n_players=config.n_players,
            n_actions_per_player=(config.actions_per_player,) * config.n_players,
            goals=goals,
            private_preferences=preferences,
            round_robin=schedule,
            max_changes=config.max_changes,
            seed=int(seed),
            metadata=metadata,
        )

    raise RuntimeError(
        "Could not generate a valid BENAC-P game within max_attempts="
        f"{config.max_attempts}; configuration={_config_dict(config)!r}."
    )
