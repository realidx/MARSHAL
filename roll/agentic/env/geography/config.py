from dataclasses import dataclass
from typing import Optional


@dataclass
class GeographyConfig:
    seed: int = 42
    render_mode: str = "text"
    built_in_opponent: str = "none"
    opponent_player: int = 1
    starting_player: int = 0
    include_opponent_turn: str = "full"
    reward_mode: str = "counterfactual"
    game_step_discount: float = 1.0
    response_token_limit: int = 256
    # Evaluation-only mode: score the root move with its exact solved Q value
    # and end the episode without generating the optimal continuation.
    root_decision_only: bool = False

    num_nodes: int = 16
    min_depth: int = 4
    max_depth: int = 8
    min_branching: int = 1
    max_branching: int = 3
    transposition_rate: float = 0.25
    target_root_value: Optional[int] = None
    target_root_informative: Optional[bool] = None
    target_informative_fraction: Optional[float] = 0.5
    generator_candidates: int = 32

    # A nonzero offset makes fixed evaluation suites easy to keep disjoint
    # from training seeds without changing EnvManager's episode seeding.
    seed_offset: int = 0
    seed_namespace: int = 0
    fixed_graph_seed: Optional[int] = None
    relabel_seed_offset: int = 0
