"""Generate reproducible BENAC-P v0 sample bundles and diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.policies import RandomPolicy
from benac_p.runner import GameRunner
from benac_p.schema import GameSpec


def _random_policies(spec: GameSpec, seed: int, *, pass_probability: float, accept_probability: float):
    return {
        player_id: RandomPolicy(
            seed=seed * 10_000 + player_id,
            pass_probability=pass_probability,
            accept_probability=accept_probability,
        )
        for player_id in range(spec.n_players)
    }


def generate_sample_bundle(
    n_games: int = 100,
    *,
    start_seed: int = 0,
    config: GeneratorConfig | None = None,
    pass_probability: float = 0.2,
    accept_probability: float = 0.5,
) -> dict[str, Any]:
    """Generate games, random self-play outcomes, and aggregate diagnostics."""

    if n_games < 1:
        raise ValueError("n_games must be positive.")
    config = config or GeneratorConfig()
    games: list[dict[str, Any]] = []
    want_counts: list[list[int]] = []
    goal_arities: dict[str, int] = {}
    action_coverage = [
        [0 for _ in range(config.actions_per_player)] for _ in range(config.n_players)
    ]
    connected_games = 0
    pass_count = accept_count = reject_count = 0
    episodes_without_valid_offer = 0
    payoff_rows: list[list[int]] = []

    for offset in range(n_games):
        seed = start_seed + offset
        spec = generate_game(seed=seed, config=config)
        policies = _random_policies(
            spec,
            seed,
            pass_probability=pass_probability,
            accept_probability=accept_probability,
        )
        result = GameRunner(spec, policies).run()
        games.append({"spec": spec.to_dict(include_private=True), "episode": result.to_dict()})

        want_counts.append([int((spec.private_preferences[player_id] == 1).sum()) for player_id in range(spec.n_players)])
        connected_games += int(bool(spec.metadata.get("connected", False)))
        for goal in spec.goals:
            arity = len({action.player_id for action in goal.required_actions})
            goal_arities[str(arity)] = goal_arities.get(str(arity), 0) + 1
            for action in goal.required_actions:
                action_coverage[action.player_id][action.action_id] += 1
        for event in result.transcript:
            if event.action == "PASS":
                pass_count += 1
            elif event.response == "ACCEPT":
                accept_count += 1
            elif event.response == "REJECT":
                reject_count += 1
        if not any(event.action == "OFFER" and not event.invalid_action for event in result.transcript):
            episodes_without_valid_offer += 1
        payoff_rows.append(list(result.terminal_rewards))

    total_turns = sum(len(game["episode"]["transcript"]) for game in games)
    total_responses = accept_count + reject_count
    summary = {
        "n_games": n_games,
        "seed_range": [start_seed, start_seed + n_games - 1],
        "connected_games": connected_games,
        "connected_fraction": connected_games / n_games,
        "want_counts_per_player": want_counts,
        "goal_arity_counts": goal_arities,
        "action_coverage": action_coverage,
        "turn_count": total_turns,
        "pass_count": pass_count,
        "accept_count": accept_count,
        "reject_count": reject_count,
        "pass_rate": pass_count / total_turns if total_turns else 0.0,
        "accept_rate_among_offers": accept_count / total_responses if total_responses else 0.0,
        "reject_rate_among_offers": reject_count / total_responses if total_responses else 0.0,
        "episodes_without_valid_offer": episodes_without_valid_offer,
        "episodes_without_valid_offer_fraction": episodes_without_valid_offer / n_games,
        "terminal_rewards": payoff_rows,
    }
    return {
        "schema_version": "benac_p.v0.sample_bundle.1",
        "policy": {
            "name": "random",
            "pass_probability": pass_probability,
            "accept_probability": accept_probability,
        },
        "generator_config": asdict(config),
        "summary": summary,
        "games": games,
    }


def save_sample_bundle(bundle: dict[str, Any], path: str | Path) -> Path:
    """Write a JSON sample bundle and return its resolved path."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
    return output_path
