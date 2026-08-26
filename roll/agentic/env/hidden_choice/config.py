"""Configuration for the one-query Hidden Choice benchmark."""

from dataclasses import dataclass


@dataclass
class HiddenChoiceConfig:
    seed: int = 42
    seed_offset: int = 0
    render_mode: str = "text"

    built_in_opponent: str = "oracle"
    opponent_player: int = 1
    include_opponent_turn: str = "full"
    response_token_limit: int = 128

    # One of: cycle, no_query, necessary_query,
    # irrelevant_uncertainty, selective_query.
    condition: str = "cycle"
    communication_cost: float = 0.25
    # If set, construct a symmetric diagnostic margin pair: no-query and
    # irrelevant states have Delta=-m, while necessary and selective states
    # have Delta=+m. This overrides communication_cost with m.
    margin_magnitude: float | None = None
    target_positive_margin: float = 0.25
    randomize_labels: bool = True
    shuffle_action_order: bool = True
    decision_rule_hint: bool = False
    full_information: bool = False
