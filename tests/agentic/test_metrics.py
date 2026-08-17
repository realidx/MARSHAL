from roll.agentic.metrics import (
    aggregate_counterfactual_decision_metrics,
    aggregate_minimax_decision_metrics,
    aggregate_prompt_group_metrics,
)


def test_minimax_metrics_use_decisions_not_episode_sums():
    records = [
        [
            {"valid": 1.0, "optimal": 1.0, "regret": 0.0, "spread": 0.5},
            {
                "valid": 1.0,
                "optimal": 0.0,
                "regret": 0.75,
                "spread": 1.5,
                "format_valid": 0.0,
                "semantic_action_valid": 1.0,
                "action_recovered": 1.0,
            },
        ],
        [
            {"valid": 1.0, "optimal": 1.0, "regret": 0.25, "spread": 1.0},
            {"valid": 0.0},
        ],
    ]

    metrics = aggregate_minimax_decision_metrics(records, tags=["TicTacToe", "TicTacToe"])
    prefix = "env/TicTacToe/minimax"

    assert metrics[f"{prefix}/decision_count"] == 4
    assert metrics[f"{prefix}/valid_action_count"] == 3
    assert metrics[f"{prefix}/valid_action_rate"] == 0.75
    assert metrics[f"{prefix}/format_valid_rate"] == 0.75
    assert metrics[f"{prefix}/semantic_action_valid_rate"] == 0.75
    assert metrics[f"{prefix}/action_recovered_rate"] == 0.25
    assert metrics[f"{prefix}/near_generation_limit_rate"] == 0.0
    assert metrics[f"{prefix}/response_truncation_rate"] == 0.0
    assert metrics[f"{prefix}/optimal_action_count"] == 2
    assert metrics[f"{prefix}/optimal_action_rate"] == 2 / 3
    assert metrics[f"{prefix}/end_to_end_optimal_rate"] == 0.5
    assert (
        metrics[f"{prefix}/valid_action_rate_wilson95_low"]
        < metrics[f"{prefix}/valid_action_rate"]
        < metrics[f"{prefix}/valid_action_rate_wilson95_high"]
    )
    assert (
        metrics[f"{prefix}/end_to_end_optimal_rate_wilson95_low"]
        < metrics[f"{prefix}/end_to_end_optimal_rate"]
        < metrics[f"{prefix}/end_to_end_optimal_rate_wilson95_high"]
    )
    assert metrics[f"{prefix}/normalized_regret_mean"] == 1 / 3
    assert metrics[f"{prefix}/decision_spread_mean"] == 1.0


def test_minimax_metrics_are_separated_by_environment_tag():
    records = [
        [{"valid": 1.0, "optimal": 1.0, "regret": 0.0, "spread": 0.5}],
        [{"valid": 1.0, "optimal": 0.0, "regret": 1.0, "spread": 1.5}],
    ]

    metrics = aggregate_minimax_decision_metrics(records, tags=["easy", "hard"])

    assert metrics["env/easy/minimax/optimal_action_rate"] == 1.0
    assert metrics["env/hard/minimax/optimal_action_rate"] == 0.0


def test_generic_counterfactual_metrics_use_generic_namespace():
    records = [[{"valid": 1.0, "optimal": 1.0, "regret": 0.0, "spread": 2.0}]]
    metrics = aggregate_counterfactual_decision_metrics(records, tags=["Geography"])
    assert metrics["env/Geography/counterfactual/decision_count"] == 1.0
    assert metrics["env/Geography/counterfactual/optimal_action_rate"] == 1.0


def test_counterfactual_metrics_report_graph_coverage_and_distance_buckets():
    records = [
        [
            {
                "valid": 1.0,
                "optimal": 1.0,
                "regret": 0.0,
                "spread": 2.0,
                "graph_seed": "101",
                "remaining_optimal_distance": 3,
            },
            {
                "valid": 0.0,
                "graph_seed": "101",
                "remaining_optimal_distance": 1,
            },
        ],
        [
            {
                "valid": 1.0,
                "optimal": 0.0,
                "regret": 1.0,
                "spread": 2.0,
                "graph_seed": "102",
                "remaining_optimal_distance": 3,
            }
        ],
    ]
    metrics = aggregate_counterfactual_decision_metrics(
        records, tags=["Geography", "Geography"]
    )
    prefix = "env/Geography/counterfactual"

    assert metrics[f"{prefix}/unique_graph_count"] == 2.0
    assert metrics[f"{prefix}/distance_1/decision_count"] == 1.0
    assert metrics[f"{prefix}/distance_1/valid_action_rate"] == 0.0
    assert metrics[f"{prefix}/distance_3/decision_count"] == 2.0
    assert metrics[f"{prefix}/distance_3/valid_action_rate"] == 1.0
    assert metrics[f"{prefix}/distance_3/optimal_action_rate"] == 0.5
    assert metrics[f"{prefix}/distance_3/end_to_end_optimal_rate"] == 0.5


def test_prompt_group_metrics_expose_zero_signal_and_action_diversity():
    metrics = aggregate_prompt_group_metrics(
        group_ids=["a", "a", "a", "a", "b", "b", "b", "b"],
        combined_rewards=[1.0, -1.0, 1.0, -1.0, -1.5, -1.5, -1.5, -1.5],
        game_rewards=[1.0, -1.0, 1.0, -1.0, 0.0, 0.0, 0.0, 0.0],
        valid_actions=[True, True, True, True, False, False, False, False],
        records_by_rollout=[
            [{"valid": 1.0, "action": "N1"}],
            [{"valid": 1.0, "action": "N2"}],
            [{"valid": 1.0, "action": "N1"}],
            [{"valid": 1.0, "action": "N2"}],
            [{"valid": 0.0}],
            [{"valid": 0.0}],
            [{"valid": 0.0}],
            [{"valid": 0.0}],
        ],
    )

    assert metrics["group/count"] == 2.0
    assert metrics["group/size_mean"] == 4.0
    assert metrics["group/combined_reward_nonzero_std_rate"] == 0.5
    assert metrics["group/game_reward_nonzero_std_rate"] == 0.5
    assert metrics["group/all_invalid_rate"] == 0.5
    assert metrics["group/unique_valid_actions_mean"] == 1.0
    assert metrics["group/multiple_valid_actions_rate"] == 0.5


def test_prompt_group_metrics_reject_misaligned_inputs():
    import pytest

    with pytest.raises(ValueError, match="same length"):
        aggregate_prompt_group_metrics(
            group_ids=["a"],
            combined_rewards=[],
            game_rewards=[1.0],
            valid_actions=[True],
            records_by_rollout=[[{"valid": 1.0, "action": "N1"}]],
        )
