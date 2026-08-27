"""Behavioral diagnostics for item-game rollouts."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


DIAGNOSTIC_KEYS = (
    "asked_goal", "asked_holdings", "disclosed_own_state", "proposed_join",
    "successful_joint_commit", "identified_complementary_exchange", "executed_exchange",
    "coalition_commit_exact", "coalition_members_committed",
    "asked_give", "refused_critical_item", "accepted_cannot", "rerouted_after_cannot", "success",
)


def aggregate_item_game_metrics(rows: Iterable[Mapping[str, object]]) -> dict[str, float]:
    rows = list(rows)
    if not rows:
        return {key: 0.0 for key in DIAGNOSTIC_KEYS}
    result = {}
    for key in DIAGNOSTIC_KEYS:
        result[key] = sum(float(row.get(key, 0.0)) for row in rows) / len(rows)
    return result


def metrics_by_subtype(rows: Iterable[Mapping[str, object]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("subtype", "unknown"))].append(row)
    return {subtype: aggregate_item_game_metrics(items) for subtype, items in grouped.items()}
