from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict


@dataclass
class TicTacToeConfig:
    seed: int = 42
    render_mode: str = "text"
    built_in_opponent: str = "mcts"
    opponent_player: int = 1
    include_opponent_turn: str = "full"
    reward_mode: str = "environment"
    minimax_discount: float = 0.9
    precompute_minimax: bool = False
    minimax_diagnostics: bool = False
    response_token_limit: int = 600
    
    # mcts config
    uct_c: float = 2.0                   
    max_simulations: int = 100
    rollout_count: int = 10
