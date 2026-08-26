"""Trajectory-level Hidden Choice failure-decomposition metrics."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def aggregate_hidden_choice_metrics(
    terminal_infos: Iterable[Mapping[str, float]],
) -> Dict[str, float]:
    infos = list(terminal_infos)
    keys = (
        "benchmark_success",
        "correct_abstention",
        "over_querying",
        "decision_error",
        "under_querying",
        "query_selection_failure",
        "query_selection_correct",
        "information_use_failure",
        "post_query_action_correct",
        "communication_success",
        "stopping_failure",
        "full_info_action_correct",
        "first_decision_optimal",
        "ask_act_correct",
        "final_action_optimal",
        "num_asks",
        "total_decision_regret",
    )
    metrics = {key: _mean(info.get(key, 0.0) for info in infos) for key in keys}
    metrics["episodes"] = float(len(infos))
    return metrics
