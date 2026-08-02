"""Pure helpers for the Tic-Tac-Toe text action protocol."""

import re
from typing import Dict, Optional


def action_to_string(player_id: int, action: int) -> str:
    mark = "X" if player_id == 0 else "O"
    row = action // 3
    column = action % 3
    return f"{mark}({row},{column})"


def string_to_action(action_str: str) -> int:
    match = re.fullmatch(r"\s*<?\s*[XO]\s*\(\s*([0-2])\s*,\s*([0-2])\s*\)\s*>?\s*", action_str)
    if match is None:
        raise ValueError(f"Invalid Tic-Tac-Toe action: {action_str!r}")
    row = int(match.group(1))
    column = int(match.group(2))
    return row * 3 + column


def recover_action(response: str, legal_actions: Dict[int, str]) -> Optional[str]:
    """Recover one unambiguous legal move while preserving format invalidity."""
    answer_match = re.search(r"<answer>(.*?)</answer>", response, re.DOTALL | re.IGNORECASE)
    if answer_match is None:
        return None
    candidate_text = answer_match.group(1)

    matches = re.findall(
        r"<?\s*([XO])\s*\(\s*([0-2])\s*,\s*([0-2])\s*\)\s*>?",
        candidate_text,
        re.IGNORECASE,
    )
    candidates = {
        f"{mark.upper()}({int(row)},{int(column)})"
        for mark, row, column in matches
    }
    legal_candidates = candidates & set(legal_actions.values())
    if len(candidates) == 1 and len(legal_candidates) == 1:
        return legal_candidates.pop()
    return None
