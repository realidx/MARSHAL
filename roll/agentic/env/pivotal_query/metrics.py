"""Aggregation of symbolic ASK diagnostics from terminal episode records."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def aggregate_pivotal_query_metrics(
    terminal_infos: Iterable[Mapping[str, float]],
) -> Dict[str, float]:
    infos = list(terminal_infos)
    necessary = [info for info in infos if info.get("initial_should_ask") == 1.0]
    unnecessary = [info for info in infos if info.get("initial_should_ask") == 0.0]
    necessary_asked = [
        info for info in infos if info.get("initial_should_ask") == 1.0 and info.get("first_action_ask") == 1.0
    ]
    return {
        "necessary_ask_recall": _mean(info["necessary_ask_hit"] for info in necessary),
        "unnecessary_ask_rate": _mean(info["unnecessary_ask"] for info in unnecessary),
        "targeted_first_query_rate": _mean(info["first_query_targeted"] for info in necessary_asked),
        "relevant_fact_first_query_rate": _mean(info["first_query_fact_relevant"] for info in necessary_asked),
        "capable_source_first_query_rate": _mean(info["first_query_source_capable"] for info in necessary_asked),
        "optimal_route_first_query_rate": _mean(info["first_query_route_optimal"] for info in necessary_asked),
        "mean_query_regret": _mean(info["total_query_regret"] for info in infos),
        "post_sufficiency_excess_communication": _mean(
            info["post_sufficiency_excess_communication"] for info in infos
        ),
        "first_decision_optimal_rate": _mean(info["first_decision_optimal"] for info in infos),
        "mean_num_asks": _mean(info["num_asks"] for info in infos),
        "mean_unproductive_queries": _mean(info["unproductive_queries"] for info in infos),
        "retry_rate": _mean(info.get("retry_rate", 0.0) for info in infos),
        "correct_retry_source_rate": _mean(
            info.get("correct_retry_source_rate", 0.0) for info in infos
        ),
        "premature_act_rate": _mean(info.get("premature_act_rate", 0.0) for info in infos),
        "repeat_failed_query_rate": _mean(
            info.get("repeat_failed_query_rate", 0.0) for info in infos
        ),
        "illegal_ask_after_budget_rate": _mean(
            info.get("illegal_ask_after_budget", 0.0) for info in infos
        ),
        "policy_failure_rate": _mean(info.get("policy_failure", 0.0) for info in infos),
        "episodes": float(len(infos)),
    }
