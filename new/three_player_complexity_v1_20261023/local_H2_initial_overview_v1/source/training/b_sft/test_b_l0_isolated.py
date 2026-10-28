"""Check isolated payoff contrasts, native legality, and historical split boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from training.b_sft.build_b_l0_isolated import build_tasks, check_legacy, make_request
from training.b_sft.build_b_response_bridges import verify_task
from training.b_sft.social_bp_training import native_completion, reward


class IsolatedL0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = build_tasks()

    def test_every_label_and_previous_belief_reconstructs(self):
        for t in self.tasks:
            with self.subTest(task=t['id']):
                verify_task(t)

    def test_only_offered_goal_changes_and_all_prerequisites_matter(self):
        for t in self.tasks:
            cert = t['teacher']['response_certificate']
            offered = 0 if t['evidence_relation'] == 'target' else 1
            self.assertEqual(cert['completed_goals']['ACCEPT'], [offered == 0, offered == 1])
            self.assertEqual(cert['completed_goals']['REJECT'], [False, False])
            goals = t['input']['game']['goals']
            sets = [{(a['player_id'], a['action_id']) for a in g['required_actions']} for g in goals]
            self.assertFalse(sets[0] & sets[1])
            for g in sets:
                self.assertEqual({p for p, _ in g}, {0, 1})
            offer = t['input']['imposed_setup'][-1]
            vectors = [offer['proposer_action'], offer['partner_action']]
            # Removing any offered prerequisite really breaks this goal.
            for p, a in sets[offered]:
                broken = deepcopy(vectors)
                broken[p][a] = 0
                self.assertFalse(all(broken[q][b] for q, b in sets[offered]))

    def test_no_constant_answer_solves_the_three_assisted_contrasts(self):
        for split in ('train', 'validation'):
            rows = [t for t in self.tasks if t['split'] == split and t['b_lesson_step'] == 'assisted']
            self.assertEqual(len(rows), 3)
            self.assertEqual({tuple(t['teacher']['gold']['possible_preferences']) for t in rows},
                             {('want',), ('avoid',), ('want', 'avoid')})
            self.assertEqual(sum(t['skill'] == 'maintain' for t in rows), 1)
            for t in rows:
                c = native_completion(t)
                fn = c['raw_message']['tool_calls'][0]['function']
                args = json.loads(fn['arguments'])
                args['judgments'][0].update(t['input']['previous_belief'])
                fn['arguments'] = json.dumps(args)
                self.assertEqual(reward(t, c)['reward'], int(t['skill'] == 'maintain'))

    def test_split_is_structural_and_existing_test_cannot_be_reused(self):
        check_legacy(self.tasks)
        train = {t['family'] for t in self.tasks if t['split'] == 'train'}
        val = {t['family'] for t in self.tasks if t['split'] == 'validation'}
        self.assertFalse(train & val)
        old = [json.loads(s) for s in Path('examples/social_bp/b_response_bridges_v1/tasks.jsonl').read_text().splitlines()]
        held_out = next(t for t in old if t['split'] == 'test')
        with self.assertRaises(AssertionError):
            check_legacy([held_out])

    def test_requests_use_existing_protocol_without_teacher_leakage(self):
        for t in self.tasks:
            req = make_request(t)['request']
            self.assertEqual(req['max_tokens'], 1024)
            self.assertEqual(req['temperature'], .8)
            self.assertEqual({x['function']['name'] for x in req['tools']}, {'SUBMIT_BELIEFS'})
            text = json.dumps(req)
            for forbidden in ('response_certificate', 'policy_sha256', 'preference_weights', 'type_catalogues'):
                self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
