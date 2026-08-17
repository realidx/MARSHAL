"""Decision- and prompt-group-level metrics for agentic game rollouts."""

import math
from collections import defaultdict
from typing import Dict, Iterable, Mapping, Optional, Sequence


def _wilson_interval(successes: float, trials: int, z: float = 1.96):
    """Return a bounded Wilson score interval for a rollout-level rate."""
    if trials <= 0:
        return 0.0, 0.0
    proportion = float(successes) / trials
    denominator = 1.0 + z**2 / trials
    center = (proportion + z**2 / (2.0 * trials)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z**2 / (4.0 * trials**2)
        )
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def aggregate_prompt_group_metrics(
    group_ids: Sequence[str],
    combined_rewards: Sequence[float],
    game_rewards: Sequence[float],
    valid_actions: Sequence[bool],
    records_by_rollout: Sequence[Iterable[Mapping]],
    namespace: str = "group",
) -> Dict[str, float]:
    """Measure whether prompt-local policy groups contain learning signal.

    GRPO produces zero reward advantage when every sample in a prompt group
    receives the same combined reward. These metrics expose that failure mode
    separately from strategic reward diversity and action diversity.
    """
    lengths = {
        len(group_ids),
        len(combined_rewards),
        len(game_rewards),
        len(valid_actions),
        len(records_by_rollout),
    }
    if len(lengths) != 1:
        raise ValueError("All prompt-group metric inputs must have the same length")

    grouped = defaultdict(list)
    for index, group_id in enumerate(group_ids):
        grouped[str(group_id)].append(index)

    def has_variance(values: Sequence[float]) -> bool:
        if len(values) < 2:
            return False
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return math.isfinite(variance) and variance > 1e-12

    group_sizes = []
    combined_informative = 0
    game_informative = 0
    all_invalid = 0
    unique_valid_action_counts = []
    multiple_valid_actions = 0
    for indices in grouped.values():
        group_sizes.append(len(indices))
        combined_informative += int(
            has_variance([float(combined_rewards[index]) for index in indices])
        )
        game_informative += int(
            has_variance([float(game_rewards[index]) for index in indices])
        )
        all_invalid += int(not any(bool(valid_actions[index]) for index in indices))

        actions = set()
        for index in indices:
            for record in records_by_rollout[index]:
                if float(record.get("valid", 0.0)) > 0 and record.get("action"):
                    actions.add(str(record["action"]))
        unique_valid_action_counts.append(len(actions))
        multiple_valid_actions += int(len(actions) > 1)

    group_count = len(grouped)
    if group_count == 0:
        return {
            f"{namespace}/count": 0.0,
            f"{namespace}/combined_reward_nonzero_std_rate": 0.0,
            f"{namespace}/game_reward_nonzero_std_rate": 0.0,
            f"{namespace}/all_invalid_rate": 0.0,
            f"{namespace}/unique_valid_actions_mean": 0.0,
            f"{namespace}/multiple_valid_actions_rate": 0.0,
        }

    return {
        f"{namespace}/count": float(group_count),
        f"{namespace}/size_min": float(min(group_sizes)),
        f"{namespace}/size_mean": float(sum(group_sizes) / group_count),
        f"{namespace}/size_max": float(max(group_sizes)),
        f"{namespace}/combined_reward_nonzero_std_rate": combined_informative
        / group_count,
        f"{namespace}/game_reward_nonzero_std_rate": game_informative / group_count,
        f"{namespace}/all_invalid_rate": all_invalid / group_count,
        f"{namespace}/unique_valid_actions_mean": sum(unique_valid_action_counts)
        / group_count,
        f"{namespace}/multiple_valid_actions_rate": multiple_valid_actions
        / group_count,
    }


def aggregate_counterfactual_decision_metrics(
    records_by_rollout: Sequence[Iterable[Mapping]],
    tags: Optional[Sequence[str]] = None,
    namespace: str = "counterfactual",
) -> Dict[str, float]:
    """Aggregate exact counterfactual diagnostics with decision denominators.

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
        prefix = f"env/{tag}/{namespace}"
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
        valid_ci = _wilson_interval(valid_count, decision_count)
        optimal_ci = _wilson_interval(optimal_count, valid_count)
        end_to_end_ci = _wilson_interval(optimal_count, decision_count)

        metrics[f"{prefix}/decision_count"] = float(decision_count)
        metrics[f"{prefix}/valid_action_count"] = float(valid_count)
        metrics[f"{prefix}/invalid_action_count"] = float(invalid_count)
        metrics[f"{prefix}/valid_action_rate"] = (
            float(valid_count) / decision_count if decision_count else 0.0
        )
        metrics[f"{prefix}/valid_action_rate_wilson95_low"] = valid_ci[0]
        metrics[f"{prefix}/valid_action_rate_wilson95_high"] = valid_ci[1]
        metrics[f"{prefix}/format_valid_rate"] = format_valid_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/semantic_action_valid_rate"] = semantic_valid_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/action_recovered_rate"] = recovered_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/near_generation_limit_rate"] = near_limit_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/response_truncation_rate"] = truncated_count / decision_count if decision_count else 0.0
        metrics[f"{prefix}/optimal_action_count"] = float(optimal_count)
        metrics[f"{prefix}/optimal_action_rate"] = optimal_count / valid_count if valid_count else 0.0
        metrics[f"{prefix}/optimal_action_rate_wilson95_low"] = optimal_ci[0]
        metrics[f"{prefix}/optimal_action_rate_wilson95_high"] = optimal_ci[1]
        metrics[f"{prefix}/end_to_end_optimal_rate"] = (
            optimal_count / decision_count if decision_count else 0.0
        )
        metrics[f"{prefix}/end_to_end_optimal_rate_wilson95_low"] = (
            end_to_end_ci[0]
        )
        metrics[f"{prefix}/end_to_end_optimal_rate_wilson95_high"] = (
            end_to_end_ci[1]
        )
        metrics[f"{prefix}/normalized_regret_sum"] = regret_sum
        metrics[f"{prefix}/normalized_regret_mean"] = regret_sum / valid_count if valid_count else 0.0
        metrics[f"{prefix}/decision_spread_sum"] = spread_sum
        metrics[f"{prefix}/decision_spread_mean"] = spread_sum / valid_count if valid_count else 0.0

        graph_seeds = {
            str(record.get("graph_seed", ""))
            for record in records
            if str(record.get("graph_seed", ""))
        }
        metrics[f"{prefix}/unique_graph_count"] = float(len(graph_seeds))

        observed_distances = sorted(
            {
                int(record["remaining_optimal_distance"])
                for record in records
                if int(record.get("remaining_optimal_distance", -1)) >= 0
            }
        )
        for distance in observed_distances:
            distance_records = [
                record
                for record in records
                if int(record.get("remaining_optimal_distance", -1)) == distance
            ]
            distance_valid = [
                record
                for record in distance_records
                if float(record.get("valid", 0.0)) > 0
            ]
            distance_optimal = sum(
                float(record.get("optimal", 0.0)) for record in distance_valid
            )
            distance_valid_ci = _wilson_interval(
                len(distance_valid), len(distance_records)
            )
            distance_end_to_end_ci = _wilson_interval(
                distance_optimal, len(distance_records)
            )
            distance_prefix = f"{prefix}/distance_{distance}"
            metrics[f"{distance_prefix}/decision_count"] = float(
                len(distance_records)
            )
            metrics[f"{distance_prefix}/valid_action_rate"] = (
                len(distance_valid) / len(distance_records)
                if distance_records
                else 0.0
            )
            metrics[f"{distance_prefix}/valid_action_rate_wilson95_low"] = (
                distance_valid_ci[0]
            )
            metrics[f"{distance_prefix}/valid_action_rate_wilson95_high"] = (
                distance_valid_ci[1]
            )
            metrics[f"{distance_prefix}/optimal_action_rate"] = (
                distance_optimal / len(distance_valid) if distance_valid else 0.0
            )
            metrics[f"{distance_prefix}/end_to_end_optimal_rate"] = (
                distance_optimal / len(distance_records)
                if distance_records
                else 0.0
            )
            metrics[
                f"{distance_prefix}/end_to_end_optimal_rate_wilson95_low"
            ] = distance_end_to_end_ci[0]
            metrics[
                f"{distance_prefix}/end_to_end_optimal_rate_wilson95_high"
            ] = distance_end_to_end_ci[1]

    return metrics


def aggregate_minimax_decision_metrics(
    records_by_rollout: Sequence[Iterable[Mapping]],
    tags: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """Compatibility wrapper for existing dashboards and saved runs."""
    return aggregate_counterfactual_decision_metrics(
        records_by_rollout,
        tags=tags,
        namespace="minimax",
    )
