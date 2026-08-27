"""
base agentic codes reference: https://github.com/RAGEN-AI/RAGEN
"""

from .tictactoe.config import TicTacToeConfig
from .tictactoe.env import TicTacToe
from .hanabi.config import HanabiConfig
from .hanabi.env import Hanabi
from .connect_four.config import ConnectFourConfig
from .connect_four.env import ConnectFour
from .kuhn_poker.config import KuhnPokerConfig
from .kuhn_poker.env import KuhnPoker
from .leduc_poker.config import LeducPokerConfig
from .leduc_poker.env import LeducPoker
from .geography.config import GeographyConfig
from .geography.env import GeographyEnv
from .pivotal_query.config import PivotalQueryConfig
from .pivotal_query.env import PivotalQueryEnv
from .hidden_choice.config import HiddenChoiceConfig
from .hidden_choice.env import HiddenChoiceEnv
from .item_game.config import ItemGameConfig
from .item_game.env import ItemGameEnv

REGISTERED_ENVS = {
    "tictactoe": TicTacToe,
    "hanabi": Hanabi,
    "connect_four": ConnectFour,
    "kuhn_poker": KuhnPoker,
    "leduc_poker": LeducPoker,
    "geography": GeographyEnv,
    "pivotal_query": PivotalQueryEnv,
    "hidden_choice": HiddenChoiceEnv,
    "item_game": ItemGameEnv,
}

REGISTERED_ENV_CONFIGS = {
    "tictactoe": TicTacToeConfig,
    "hanabi": HanabiConfig,
    "connect_four": ConnectFourConfig,
    "kuhn_poker": KuhnPokerConfig,
    "leduc_poker": LeducPokerConfig,
    "geography": GeographyConfig,
    "pivotal_query": PivotalQueryConfig,
    "hidden_choice": HiddenChoiceConfig,
    "item_game": ItemGameConfig,
}
