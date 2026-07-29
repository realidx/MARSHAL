"""Exact depth-sensitive minimax values for Tic-Tac-Toe.

The evaluator is intentionally independent of OpenSpiel so that the value
table and its invariants can be tested without constructing an environment.
Boards are tuples of length nine containing 0 (empty), 1 (X/player 0), or
-1 (O/player 1).
"""

from __future__ import annotations

from functools import lru_cache
from math import inf
from typing import Dict, Iterable, Tuple


Board = Tuple[int, ...]

EMPTY_BOARD: Board = (0,) * 9
WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def board_from_string(board: str) -> Board:
    """Convert OpenSpiel's three-line board representation to a tuple."""
    cells = "".join(board.strip().splitlines()).lower()
    if len(cells) != 9:
        raise ValueError(f"Expected a 3x3 Tic-Tac-Toe board, got {board!r}")
    mapping = {".": 0, "_": 0, "x": 1, "o": -1}
    try:
        return tuple(mapping[cell] for cell in cells)
    except KeyError as exc:
        raise ValueError(f"Unknown Tic-Tac-Toe board symbol: {exc.args[0]!r}") from exc


def winner(board: Board) -> int | None:
    """Return player 0/1 for a win, or None when there is no winner."""
    for a, b, c in WINNING_LINES:
        line = board[a] + board[b] + board[c]
        if line == 3:
            return 0
        if line == -3:
            return 1
    return None


def is_terminal(board: Board) -> bool:
    return winner(board) is not None or 0 not in board


def current_player(board: Board) -> int:
    if is_terminal(board):
        raise ValueError("Terminal boards do not have a current player")
    x_count = board.count(1)
    o_count = board.count(-1)
    if x_count == o_count:
        return 0
    if x_count == o_count + 1:
        return 1
    raise ValueError(f"Board has invalid mark counts: X={x_count}, O={o_count}")


def legal_actions(board: Board) -> Tuple[int, ...]:
    if is_terminal(board):
        return ()
    return tuple(index for index, mark in enumerate(board) if mark == 0)


def apply_action(board: Board, action: int) -> Board:
    if action not in legal_actions(board):
        raise ValueError(f"Illegal action {action} for board {board}")
    marks = list(board)
    marks[action] = 1 if current_player(board) == 0 else -1
    return tuple(marks)


def terminal_utility(board: Board, perspective: int) -> float:
    if not is_terminal(board):
        return 0.0
    winning_player = winner(board)
    if winning_player is None:
        return 0.0
    return 1.0 if winning_player == perspective else -1.0


class ExactTicTacToeEvaluator:
    """Alpha-beta evaluator using a fixed player perspective."""

    def __init__(self, discount: float = 0.9):
        if not 0 < discount <= 1:
            raise ValueError(f"discount must be in (0, 1], got {discount}")
        self.discount = float(discount)
        self._value_cache: Dict[Tuple[Board, int], float] = {}

    def value(self, board: Board, perspective: int) -> float:
        """Return V_i^*(s), with terminal-state potential fixed to zero."""
        if perspective not in (0, 1):
            raise ValueError(f"perspective must be 0 or 1, got {perspective}")
        if is_terminal(board):
            return 0.0
        key = (board, perspective)
        if key not in self._value_cache:
            # A root alpha-beta call with an open window returns an exact value,
            # even if bounds were sufficient to prune descendants.
            self._value_cache[key] = self._search(board, perspective, -inf, inf)[0]
        return self._value_cache[key]

    def action_value(self, board: Board, action: int, perspective: int) -> float:
        """Return Q_i^*(s, a) under optimal continuation."""
        next_board = apply_action(board, action)
        reward = terminal_utility(next_board, perspective) if is_terminal(next_board) else 0.0
        return reward + self.discount * self.value(next_board, perspective)

    def action_values(self, board: Board, perspective: int) -> Dict[int, float]:
        return {action: self.action_value(board, action, perspective) for action in legal_actions(board)}

    def precompute(self, initial_board: Board = EMPTY_BOARD) -> None:
        """Populate exact values for every state reachable from ``initial_board``."""
        visited = set()

        def visit(board: Board) -> None:
            if board in visited:
                return
            visited.add(board)
            if is_terminal(board):
                return
            self.value(board, 0)
            self.value(board, 1)
            for action in legal_actions(board):
                visit(apply_action(board, action))

        visit(initial_board)

    def reachable_boards(self, initial_board: Board = EMPTY_BOARD) -> Iterable[Board]:
        visited = set()
        stack = [initial_board]
        while stack:
            board = stack.pop()
            if board in visited:
                continue
            visited.add(board)
            yield board
            stack.extend(apply_action(board, action) for action in legal_actions(board))

    def _search(self, board: Board, perspective: int, alpha: float, beta: float) -> Tuple[float, bool]:
        key = (board, perspective)
        if key in self._value_cache:
            return self._value_cache[key], True
        if is_terminal(board):
            return 0.0, True

        maximizing = current_player(board) == perspective
        best = -inf if maximizing else inf
        exact = True

        for action in legal_actions(board):
            q_value, child_exact = self.action_value_with_window(board, action, perspective, alpha, beta)
            exact = exact and child_exact
            if maximizing:
                best = max(best, q_value)
                alpha = max(alpha, best)
            else:
                best = min(best, q_value)
                beta = min(beta, best)
            if beta <= alpha:
                exact = False
                break

        # A cutoff yields a bound, not necessarily an exact value. Do not cache it.
        if exact:
            self._value_cache[key] = best
        return best, exact

    def action_value_with_window(
        self,
        board: Board,
        action: int,
        perspective: int,
        alpha: float,
        beta: float,
    ) -> Tuple[float, bool]:
        next_board = apply_action(board, action)
        if is_terminal(next_board):
            return terminal_utility(next_board, perspective), True

        # Transform the alpha-beta window through Q = discount * V. Intermediate
        # rewards are zero in canonical Tic-Tac-Toe.
        child_alpha = alpha / self.discount
        child_beta = beta / self.discount
        child_value, child_exact = self._search(next_board, perspective, child_alpha, child_beta)
        return self.discount * child_value, child_exact


@lru_cache(maxsize=None)
def precomputed_evaluator(discount: float) -> ExactTicTacToeEvaluator:
    """Return a process-wide read-mostly evaluator for a given discount."""
    evaluator = ExactTicTacToeEvaluator(discount)
    evaluator.precompute(EMPTY_BOARD)
    return evaluator
