from roll.agentic.metrics import aggregate_minimax_decision_metrics


def test_minimax_metrics_use_decisions_not_episode_sums():
    records = [
        [
            {"valid": 1.0, "optimal": 1.0, "regret": 0.0, "spread": 0.5},
            {"valid": 1.0, "optimal": 0.0, "regret": 0.75, "spread": 1.5},
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
    assert metrics[f"{prefix}/optimal_action_count"] == 2
    assert metrics[f"{prefix}/optimal_action_rate"] == 2 / 3
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
