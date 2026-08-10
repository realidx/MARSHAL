from roll.agentic.preflight import (
    summarize_agentic_preflight,
    summarize_tictactoe_preflight,
)
from math import comb


def test_preflight_deduplicates_player_rollouts_into_games():
    records = [
        [{"turn_index": 0, "player_id": 0, "token_length": 20, "valid_action": True,
          "has_closing_answer_tag": True, "hit_token_limit": False}],
        [{"turn_index": 0, "player_id": 1, "token_length": 30, "valid_action": True,
          "has_closing_answer_tag": True, "hit_token_limit": False}],
    ]
    summary, flat_records = summarize_tictactoe_preflight(
        records_by_rollout=records,
        trajectory_ids=["3_1_100_p0", "3_1_100_p1"],
        terminal_infos=[{"success": True}, {"success": True}],
    )
    assert summary["game_count"] == 1
    assert summary["observed_game_count"] == 1
    assert summary["partial_game_count"] == 0
    assert summary["turn_count"] == 2
    assert summary["completed_legal_game_rate"] == 1.0
    assert summary["valid_action_rate"] == 1.0
    assert summary["closing_answer_tag_rate"] == 1.0
    assert summary["response_length"]["median"] == 25
    assert summary["response_length"]["p99"] == 29.9
    assert len(flat_records) == 2


def test_preflight_gate_fails_on_invalid_or_truncated_turns():
    record = {"turn_index": 0, "player_id": 0, "token_length": 600, "valid_action": False,
              "has_closing_answer_tag": False, "hit_token_limit": True}
    summary, _ = summarize_tictactoe_preflight(
        records_by_rollout=[[record]],
        trajectory_ids=["3_1_100_p0"],
        terminal_infos=[{"success": False}],
    )
    assert summary["passed"] is False
    assert summary["game_count"] == 0
    assert summary["observed_game_count"] == 1
    assert summary["partial_game_count"] == 1
    assert summary["valid_action_rate"] == 0.0
    assert summary["token_limit_hit_rate"] == 1.0


def test_preflight_reports_missing_answer_at_the_hard_cap():
    record = {
        "turn_index": 0,
        "player_id": 0,
        "token_length": 600,
        "valid_action": False,
        "has_closing_answer_tag": False,
        "hit_token_limit": True,
        "parsed_action": "",
    }
    summary, _ = summarize_tictactoe_preflight(
        records_by_rollout=[[record]],
        trajectory_ids=["3_1_100_p0"],
        terminal_infos=[{"success": False}],
    )

    assert summary["missing_answer_rate"] == 1.0
    assert summary["capped_without_answer_rate"] == 1.0
    assert summary["token_limit_hit_rate"] == 1.0


def test_preflight_passes_balanced_diverse_outputs():
    actions = ["X(0,0)", "O(1,1)", "X(0,2)", "O(2,0)", "X(2,2)", "O(0,1)"]
    records = []
    trajectory_ids = []
    terminal_infos = []
    for index, action in enumerate(actions):
        player_id = index % 2
        records.append([{
            "turn_index": 0,
            "player_id": player_id,
            "token_length": 40,
            "valid_action": True,
            "has_closing_answer_tag": True,
            "hit_token_limit": False,
            "parsed_action": action,
            "minimax_optimal_action": True,
        }])
        trajectory_ids.append(f"game-{index // 2}_p{player_id}")
        terminal_infos.append({"success": True})

    summary, _ = summarize_tictactoe_preflight(records, trajectory_ids, terminal_infos)

    assert summary["passed"] is True
    assert summary["role_validity_asymmetry"] == 0.0
    assert summary["action_diversity"]["unique_action_count"] == 6
    assert summary["minimax_optimality_rate"] == 1.0
    assert summary["role_minimax_optimality_gap"] == 0.0


def test_preflight_reports_retry_recovery_and_token_overhead():
    records = [
        [
            {"turn_index": 0, "decision_index": 0, "retry_attempt_index": 0,
             "player_id": 0, "token_length": 600, "valid_action": False,
             "has_closing_answer_tag": False, "hit_token_limit": True,
             "parsed_action": ""},
            {"turn_index": 1, "decision_index": 0, "retry_attempt_index": 1,
             "player_id": 0, "token_length": 30, "valid_action": True,
             "has_closing_answer_tag": True, "hit_token_limit": False,
             "parsed_action": "X(1,1)"},
        ],
        [
            {"turn_index": 0, "decision_index": 1, "retry_attempt_index": 0,
             "player_id": 1, "token_length": 25, "valid_action": True,
             "has_closing_answer_tag": True, "hit_token_limit": False,
             "parsed_action": "O(0,0)"},
        ],
    ]
    summary, _ = summarize_tictactoe_preflight(
        records,
        ["retry-game_p0", "retry-game_p1"],
        [{"success": True}, {"success": True}],
    )

    assert summary["decision_count"] == 2
    assert summary["first_attempt_validity_rate"] == 0.5
    assert summary["eventual_validity_rate"] == 1.0
    assert summary["retry_attempt_count"] == 1
    assert summary["retry_success_rate"] == 1.0
    assert summary["additional_retry_tokens"] == 30
    assert summary["by_player"]["0"]["retry_attempt_count"] == 1
    assert summary["final_episode_truncation_rate"] == 0.0


def test_generic_preflight_stratifies_informative_decisions_by_depth():
    records = [[
        {
            "turn_index": 0,
            "player_id": 0,
            "token_length": 20,
            "valid_action": True,
            "has_closing_answer_tag": True,
            "hit_token_limit": False,
            "parsed_action": "N4",
            "counterfactual_optimal_action": True,
            "counterfactual_decision_spread": 2.0,
            "counterfactual_regret": 0.0,
            "remaining_optimal_distance": 4,
        },
        {
            "turn_index": 1,
            "player_id": 0,
            "token_length": 20,
            "valid_action": True,
            "has_closing_answer_tag": True,
            "hit_token_limit": False,
            "parsed_action": "N7",
            "counterfactual_optimal_action": False,
            "counterfactual_decision_spread": 2.0,
            "counterfactual_regret": 1.0,
            "remaining_optimal_distance": 4,
        },
    ]]
    summary, _ = summarize_agentic_preflight(
        records, ["geography_p0"], [{"success": True}]
    )
    bucket = summary["informative_decisions_by_remaining_optimal_distance"]["4"]
    assert bucket["decision_count"] == 2
    assert bucket["optimal_action_rate"] == 0.5
    assert bucket["normalized_regret_mean"] == 0.5


def test_preflight_reports_root_move_pass_at_k_by_graph_group():
    records = []
    trajectory_ids = []
    terminal_infos = []
    tags = []
    for sample_index in range(32):
        valid = sample_index < 31
        records.append([{
            "turn_index": 0,
            "decision_index": 0,
            "retry_attempt_index": 0,
            "player_id": 0,
            "token_length": 50,
            "valid_action": valid,
            "has_closing_answer_tag": valid,
            "hit_token_limit": not valid,
            "counterfactual_optimal_action": sample_index < 4,
            # Invalid attempts have no transition and therefore no graph_id.
            "graph_id": "held-out-easy-0" if valid else "",
        }])
        trajectory_ids.append("7_0_700000_p0_a0")
        terminal_infos.append({"success": True})
        tags.append("Geography-Rollout-Easy")

    summary, flat_records = summarize_agentic_preflight(
        records, trajectory_ids, terminal_infos, tags=tags
    )
    group = summary["root_move_pass_at_k"]["Geography-Rollout-Easy"]

    assert group["graph_count"] == 1
    assert group["sample_count"] == 32
    assert group["valid_action_rate"] == 31 / 32
    assert group["token_limit_hit_rate"] == 1 / 32
    assert group["pass@1"] == 4 / 32
    assert group["pass@8"] == 1 - comb(28, 8) / comb(32, 8)
    assert group["pass@32"] == 1.0
    assert group["graphs_with_pass@32"] == 1
    assert summary["decision_count"] == 32
    assert summary["eventual_validity_rate"] == 31 / 32
    assert {record["tag"] for record in flat_records} == {
        "Geography-Rollout-Easy"
    }
