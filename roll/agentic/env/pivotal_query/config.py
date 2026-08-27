"""Configuration for the Pivotal Query Game."""

from dataclasses import dataclass


@dataclass
class PivotalQueryConfig:
    seed: int = 42
    seed_offset: int = 0
    render_mode: str = "text"

    # The partner is a truthful deterministic environment oracle. Keeping it
    # built in makes EnvManager treat player 0 as the only learned policy.
    built_in_opponent: str = "oracle"
    opponent_player: int = 1
    include_opponent_turn: str = "full"
    response_token_limit: int = 256

    # One of: cycle, known_pivotal, ask_necessary, costly_query,
    # irrelevant_uncertainty, who_query, retry_after_unknown.
    condition: str = "cycle"
    query_cost: float = 0.25
    high_query_cost: float = 1.25
    randomize_labels: bool = True
    max_queries: int = 3
    # Keep the base evaluation neutral. This can be enabled as a prompt-side
    # intervention without changing any game instance or oracle label.
    decision_rule_hint: bool = False
