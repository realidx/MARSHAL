"""Dependency-free helpers for interpreting generated agent responses."""

import re
from typing import Tuple


def has_closed_answer(response: str) -> bool:
    """Return whether an agent response ends with a complete answer envelope."""
    return re.search(r"<answer>.*?</answer>\s*$", response, re.IGNORECASE | re.DOTALL) is not None


def generation_limit_status(
    response: str,
    token_length: int,
    generation_limit: int,
) -> Tuple[bool, bool]:
    """Return ``(hit_limit, capped_without_answer)`` for one response."""
    hit_limit = token_length >= generation_limit
    return hit_limit, hit_limit and not has_closed_answer(response)
