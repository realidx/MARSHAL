"""Behavioral diagnostics for Item Coalition Game v0.3 rollouts."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


DIAGNOSTIC_KEYS = (
    "goal_satisfied", "agreement_formed", "agreement_fulfilled",
    "agreement_followed_through", "coalition_valid", "correct_join_commit",
    "harmful_transfer_avoided", "harmful_give_avoided", "useful_give_request",
    "useful_exchange_proposed", "mandatory_request_answered",
    "asked_goal", "asked_holdings", "disclosed_own_state", "proposed_join",
    "successful_joint_commit", "identified_complementary_exchange", "executed_exchange",
    "coalition_commit_exact", "coalition_members_committed",
    "asked_give", "refused_critical_item", "accepted_cannot", "rerouted_after_cannot",
    "success", "terminal_success", "unfulfilled_agreements",
    "rerouted_after_unavailability",
    "proposal_accepted", "proposal_rejected", "coalition_formed", "commit_valid",
    "ego_commit_item_count", "p1_commit_item_count", "redundant_commit_count",
    "communication_efficiency_bonus",
    "reroute_blocker_inferable", "reroute_blocker_hidden_unwilling",
    "reroute_first_partner_is_helper", "reroute_first_partner_is_blocker",
    "reroute_first_proposal_rejected", "rerouted_after_rejection",
    "reroute_helper_reached", "reroute_unnecessary_exploration_after_success",
    "reroute_proposal_count", "reroute_rejection_count", "reroute_proposal_partner_count",
    "respond_request_safe", "respond_request_harmful",
    "respond_partner_p1", "respond_partner_p2", "respond_partner_p3",
    "respond_accept", "respond_reject", "respond_give_fulfilled",
    "respond_exact_give", "respond_safe_correct", "respond_harmful_correct",
    "respond_harmful_transfer",
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
