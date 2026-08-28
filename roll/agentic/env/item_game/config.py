"""Configuration for the ego-centric Item Coalition Game."""

from dataclasses import dataclass, field


@dataclass
class ItemGameConfig:
    """Stable runtime knobs shared by all item-game generators."""

    seed: int = 42
    seed_offset: int = 0
    render_mode: str = "text"

    built_in_opponent: str = "oracle"
    opponent_player: int = 1
    include_opponent_turn: str = "full"
    response_token_limit: int = 256

    # ``pure_collaboration``, ``mixed_incentive`` or ``resource_conflict``.
    generator: str = "pure_collaboration"
    # ``exchange``, ``give_first``, ``request_surplus``,
    # ``request_surplus_reroute``, ``respond_to_give_request``, ``cannot_help`` or
    # ``refuse_harmful_request``.  The default is selected from generator.
    subtype: str | None = None

    max_ego_steps: int = 8
    communication_budget: int = 6
    item_vocabulary: tuple[str, ...] = field(
        default_factory=lambda: (
            "item_K", "item_Q", "item_M", "item_V",
            "item_T", "item_Z", "item_F", "item_L",
        )
    )
    randomize_items: bool = True
