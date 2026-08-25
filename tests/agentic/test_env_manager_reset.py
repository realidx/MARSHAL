from threading import Lock

from roll.agentic.rollout.env_manager import EnvManager, _is_numeric_metric_value


class _SecondRoleEnv:
    built_in_opponent = "mcts"
    opponent_player = 0
    current_player = 1

    def reset(self, seed):
        initial_observation = {
            "observation": "empty board",
            "legal_actions": {0: "X(0,0)"},
        }
        execute_results = [
            {
                "current_player": 0,
                "action": "X(0,0)",
                "rewards": [0.0, 0.0],
                "done": False,
                "info": {},
                "next_player": 1,
                "observation": "board after MCTS move",
                "legal_actions": {1: "O(0,1)"},
            }
        ]
        return initial_observation, execute_results


def test_reset_seeds_history_for_built_in_opponent_that_moves_first():
    manager = EnvManager.__new__(EnvManager)
    manager.env_entry = {
        "env": _SecondRoleEnv(),
        "env_id": 0,
        "group_id": 0,
        "tag": "second_role",
        "max_actions_per_traj": 9,
    }
    manager.internal_lock = Lock()
    manager.thread_lock = Lock()
    manager.group_seed = 0
    manager.episode_id = 0

    cache = manager.reset()

    assert cache["current_player"] == 1
    assert [turn["player"] for turn in cache["history"]] == [0, 1]
    assert cache["history"][0]["actions"] == "X(0,0)"
    assert len(cache["player_0_history"]) == 1
    assert cache["player_0_history"][0]["actions"] == "X(0,0)"
    assert len(cache["player_1_history"]) == 1
    assert cache["player_1_history"][0]["state"] == "board after MCTS move"


def test_optional_environment_diagnostics_are_not_numeric_metrics():
    assert _is_numeric_metric_value(None) is False
    assert _is_numeric_metric_value("metadata") is False
    assert _is_numeric_metric_value(0.0) is True
    assert _is_numeric_metric_value(False) is True
