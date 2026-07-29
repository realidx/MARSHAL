"""
Adapted from the nicely written code from openspiel
"""

from .env import TicTacToe
from .config import TicTacToeConfig
from .minimax import ExactTicTacToeEvaluator, precomputed_evaluator

__all__ = ["TicTacToe", "TicTacToeConfig", "ExactTicTacToeEvaluator", "precomputed_evaluator"]
