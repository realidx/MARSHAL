"""Dependency-free helpers for interpreting generated agent responses."""

import re
from typing import Tuple


def generation_limit_status(
    response: str,
    token_length: int,
    generation_limit: int,
    answer_reserve: int = 16,
) -> Tuple[bool, bool]:
    """Return ``(near_limit, truncated)`` for one generated response."""
    near_limit = token_length >= max(generation_limit - answer_reserve, 1)
    answer_is_closed = re.search(r"</answer>\s*$", response, re.IGNORECASE) is not None
    return near_limit, near_limit and not answer_is_closed
