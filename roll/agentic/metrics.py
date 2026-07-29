"""Decision-level metrics for agentic game rollouts."""

from collections import defaultdict
from typing import Dict, Iterable, Mapping, Optional, Sequence


def aggregate_minimax_decision_metrics(
    records_by_rollout: Sequence[Iterable[Mapping]],
    tags: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """Aggregate exact minimax diagnostics with decision-level denominators.

    Individual records remain in ``minimax_decision_records`` on the rollout
    batch for arbitrary spread-conditioned analysis. This function only emits
    stable scalar summaries for online logging.
    """
    if tags is None:
        tags = ["all"] * len(records_by_rollout)
    if len(records_by_rollout) != len(tags):
        raise ValueError("records_by_rollout and tags must have the same length")

    grouped = defaultdict(list)
    for rollout_records, tag in zip(records_by_rollout, tags):
        grouped[str(tag)].extend(list(rollout_records))

    metrics = {}
    for tag, records in grouped.items():
        prefix = f"env/{tag}/minimax"
        decision_count = len(records)
        valid_records = [record for record in records if float(record.get("valid", 0.0)) > 0]
        valid_count = len(valid_records)
        invalid_count = decision_count - valid_count
        format_valid_count = sum(float(record.get("format_valid", 1.0)) for record in records)
        semantic_valid_count = sum(
            float(record.get("semantic_action_valid", record.get("valid", 0.0)))
            for record in records
        )
        recovered_count = sum(float(record.get("action_recovered", 0.0)) for record in records)
        near_limit_count = sum(float(record.get("near_generation_limit", 0.0)) for record in records)
        truncated_count = sum(float(record.get("response_truncated", 0.0)) for record in records)
        optimal_count = sum(float(record["optimal"]) for record in valid_records)
        regret_sum = sum(float(record["regret"]) for record in valid_records)
        spread_sum = sum(float(record["spread"]) for record in valid_records)

        metrics[f"{prefix}/decision_count"] = float(decision_count)
        metrics[f"{prefix}/valid_action_count"] = float(valid_count)
        metrics[f"{prefix}/invalid_action_count"] = float(invalid_count)
        metrics[f"{prefix}/valid_action_rate"] = float(valid_count) / decision_count if decision_count else 0.0
        metrics[f"{prefix}/format_valid_rate"] = format_valid_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/semantic_action_valid_rate"] = semantic_valid_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/action_recovered_rate"] = recovered_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/near_generation_limit_rate"] = near_limit_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/response_truncation_rate"] = truncated_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/optimal_action_count"] = float(optimal_count)
        metrics[f"{prefix}/optimal_action_rate"] = optimal_count / valid_count if valid_count else 0.0
        metrics[f"{prefix}/normalized_regret_sum"] = regret_sum
        metrics[f"{prefix}/normalized_regret_mean"] = regret_sum / valid_count if valid_count else 0.0
        metrics[f"{prefix}/decision_spread_sum"] = spread_sum
        metrics[f"{prefix}/decision_spread_mean"] = spread_sum / valid_count if valid_count else 0.0

    return metrics
