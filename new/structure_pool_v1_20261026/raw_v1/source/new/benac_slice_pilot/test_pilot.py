"""Native checks for exact regret, information value, and branch execution."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from new.benac_slice_pilot.evaluate import expected_utility, uniform_probe_regrets
from new.benac_slice_pilot.metrics import masked_answer_value, optimal_value
from new.benac_slice_pilot.model_probe import rollout as model_rollout
from training.b_sft.organize_p4 import SOURCE as P4_SOURCE, blind_query_result, fixture, read
from training.b_sft.social_private_teacher import PrivateEpisode
from training.social_mixed.short_interaction import ShortInteraction


SOURCE = Path("examples/social_mixed/interaction_bank_v1/tasks.jsonl")
FRESH = Path("new/benac_slice_pilot/pilot_data_fresh")
IDS = (
    "0149f59d9032e5adc95b-O",
    "04029cadb035db2d4346-O",
    "4df928df170049488f2b-O",
    "00bf2cbba65a880234f0-O",
)


def first_legal_tool(_args, request):
    for tool in request["tools"]:
        fn = tool["function"]
        legal_args = fn["parameters"].get("enum", [])
        if legal_args:
            return dict(status="ok", completion=dict(
                finish_reason="tool_calls",
                raw_message=dict(tool_calls=[dict(function=dict(
                    name=fn["name"], arguments=json.dumps(legal_args[0])
                ))]),
            ))
    raise AssertionError("Expected at least one enumerated legal tool call")


class TwoPlayerSlicePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {
            task["id"]: task
            for task in map(json.loads, SOURCE.read_text().splitlines())
            if task["id"] in IDS
        }

    def window(self, task_id):
        return ShortInteraction(
            self.tasks[task_id], seconds=10, max_nodes=30000, max_sweeps=128,
        )

    def test_one_decision_c_and_extra_controllable_decision(self):
        env = self.window(IDS[0])
        result = optimal_value(
            env.episode, ego=env.ego, root_index=env.root,
            root_weights=env.weights, k=1,
        )
        self.assertEqual(result["root_action_values"], [1.0, 0.5])
        self.assertEqual(result["root_action_regrets"], [0.0, 0.5])
        probe = uniform_probe_regrets(
            env.episode, ego=env.ego, root_index=env.root,
            root_weights=env.weights, max_k=2,
        )
        self.assertGreater(probe["incremental_regret"][1], 0.6)
        self.assertAlmostEqual(
            expected_utility(
                env.episode, ego=env.ego, root_index=env.root,
                root_weights=env.weights, k=1, controlled_policy=result["policy"],
            ), result["value"],
        )

    def test_first_action_changes_the_next_actual_input(self):
        env = self.window(IDS[0])
        world_index = next(i for i, weight in enumerate(env.weights) if weight > 0)

        def rollout(first_action):
            count = 0

            def agent(inp):
                nonlocal count
                action = inp["legal_actions"][first_action if count == 0 else 0]
                count += 1
                return action

            return env.rollout(agent, seed=0, world_index=world_index)

        left, right = rollout(0), rollout(1)
        self.assertEqual((left["ego_decisions"], right["ego_decisions"]), (2, 2))
        self.assertNotEqual(
            left["decisions"][1]["input"]["current_state"]["commitments"],
            right["decisions"][1]["input"]["current_state"]["commitments"],
        )

    def test_flat_root_can_have_consequential_continuation(self):
        env = self.window(IDS[3])
        first = optimal_value(
            env.episode, ego=env.ego, root_index=env.root,
            root_weights=env.weights, k=1,
        )
        probe = uniform_probe_regrets(
            env.episode, ego=env.ego, root_index=env.root,
            root_weights=env.weights, max_k=2,
        )
        self.assertEqual(first["root_action_values"], [1.0, 1.0])
        self.assertEqual(first["root_action_regrets"], [0.0, 0.0])
        self.assertAlmostEqual(probe["uniform_regret"][0], 0)
        self.assertGreater(probe["incremental_regret"][1], 0.8)

    def test_positive_and_zero_private_answer_value(self):
        positive = self.window(IDS[1])
        zero = self.window(IDS[2])
        for env, expected in ((positive, .25), (zero, 0.0)):
            result = masked_answer_value(
                env.episode, ego=env.ego, root_index=env.root,
                root_weights=env.weights, query_slot=(1, 0), k=2,
            )
            self.assertAlmostEqual(result["S"], expected)
            self.assertGreaterEqual(result["S"], 0)
            first = masked_answer_value(
                env.episode, ego=env.ego, root_index=env.root,
                root_weights=env.weights, query_slot=(1, 0), k=1,
            )
            self.assertAlmostEqual(first["S"], 0)

    def test_information_ablation_matches_independent_native_audit(self):
        bank = {task["id"]: task for task in read(P4_SOURCE)}
        raw, _, setup, _ = fixture(bank, "acquisition", "binary")
        episode = PrivateEpisode(raw, setup, seconds=30, max_nodes=60000)
        query = dict(action="INVESTIGATE", player=1, goal=0)
        independent = blind_query_result(episode, query)
        weights = episode._weights(0, raw["own_preferences"], [])
        measured = masked_answer_value(
            episode, ego=0, root_index=episode.index,
            root_weights=weights, query_slot=(1, 0), k=10,
        )
        index = measured["full"]["root_actions"].index(query)
        forced_value = (
            measured["full"]["root_action_values"][index]
            - measured["masked"]["root_action_values"][index]
        )
        self.assertAlmostEqual(forced_value, independent["own_answer_use_gain"])
        self.assertAlmostEqual(forced_value, 1 / 3)

    def test_forced_query_model_arms_share_game_and_mask_only_model_answer(self):
        task_id = IDS[1]
        env = self.window(task_id)
        data = Path("new/benac_slice_pilot/pilot_data")
        selected = next(row for row in map(json.loads, (data / "selected.jsonl").read_text().splitlines())
                        if row["id"] == task_id)
        candidate = next(row for row in map(json.loads, (data / "candidates.jsonl").read_text().splitlines())
                         if row["id"] == task_id)

        args = SimpleNamespace(seed=42, max_tokens=128)
        job = dict(id=task_id, k=selected["continuous_slice"]["k"],
                   replica=0, rollout_seed=9324)
        full, full_calls = model_rollout(env, selected, candidate,
                                         dict(job, arm="information_full"), args,
                                         complete_fn=first_legal_tool)
        masked, masked_calls = model_rollout(env, selected, candidate,
                                             dict(job, arm="information_masked"), args,
                                             complete_fn=first_legal_tool)
        self.assertEqual((full["status"], masked["status"]), ("terminal", "terminal"))
        self.assertEqual(full["world_index"], masked["world_index"])
        self.assertEqual(full["root_action"]["action"], "INVESTIGATE")
        self.assertEqual(full["terminal_utility"], masked["terminal_utility"])
        self.assertEqual((full["model_decisions"], masked["model_decisions"]), (1, 1))
        self.assertEqual(len(full_calls), len(masked_calls))
        full_prompt = full_calls[0]["request"]["messages"][1]["content"]
        masked_prompt = masked_calls[0]["request"]["messages"][1]["content"]
        self.assertNotIn("unavailable to you for this decision", full_prompt)
        self.assertIn("unavailable to you for this decision", masked_prompt)
        self.assertAlmostEqual(
            masked["sampled_terminal_regret"] - masked["sampled_gap_to_masked_oracle"],
            selected["S_given_query"],
        )

    def test_fresh_flat_root_is_model_ready_at_all_three_lengths(self):
        task = json.loads((FRESH / "source_tasks.jsonl").read_text().splitlines()[0])
        candidate = json.loads((FRESH / "analysis/candidates.jsonl").read_text().splitlines()[0])
        selected = json.loads((FRESH / "analysis/selected.jsonl").read_text().splitlines()[0])
        env = ShortInteraction(task, seconds=10, max_nodes=30000, max_sweeps=128)
        self.assertEqual(selected["category"], "delayed_consequence")
        self.assertEqual(candidate["root_C_max"], 0)
        for k in (1, 2, 3):
            result, calls = model_rollout(
                env, selected, candidate,
                dict(id=task["id"], k=k, arm="normal", replica=0,
                     rollout_seed=27),
                SimpleNamespace(seed=42, max_tokens=128),
                complete_fn=first_legal_tool,
            )
            self.assertEqual(result["status"], "terminal")
            self.assertEqual(result["model_decisions"], k)
            self.assertEqual(len(calls), k)


if __name__ == "__main__":
    unittest.main()
