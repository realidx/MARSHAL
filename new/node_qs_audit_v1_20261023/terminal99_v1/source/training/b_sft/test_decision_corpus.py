"""Regression checks for reference labels, branch links and split integrity."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from training.b_sft.decision_corpus import export_fixture, validate, partition


class DecisionCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((Path(__file__).parent/'fixtures/decision_corpus_regression.json').read_text())
        cls.rows, cls.gold, cls.links, cls.certificate = export_fixture(cls.raw, 20000, 4, 'development')

    def test_native_replay_and_answer_contract(self):
        validate(self.rows, self.gold, self.links)
        self.assertTrue(self.links)
        self.assertEqual({r['task'] for r in self.rows}, {'B', 'P'})
        self.assertTrue(self.certificate['proof']['belief_to_planning'])
        self.assertTrue(all(not r['messages'][-1]['content'] for r in self.rows))

    def test_teacher_leak_is_rejected(self):
        rows = deepcopy(self.rows)
        payload = json.loads(rows[0]['messages'][1]['content'])
        payload['support'] = self.gold[0]['possible_preferences']
        rows[0]['messages'][1]['content'] = json.dumps(payload)
        with self.assertRaisesRegex(ValueError, 'Teacher-only'):
            validate(rows, self.gold, self.links)

    def test_cross_split_and_cross_game_links_are_rejected(self):
        for key in ('split', 'source_id'):
            links = deepcopy(self.links)
            links[0][key] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'branch link'):
                validate(self.rows, self.gold, links)

    def test_incorrect_planning_answer_is_rejected(self):
        rows = deepcopy(self.rows)
        p = next(r for r in rows if r['task'] == 'P')
        p['messages'][2]['tool_calls'][0]['function']['arguments'] = '{"action_index": -1}'
        with self.assertRaisesRegex(ValueError, 'Nonoptimal'):
            validate(rows, self.gold, self.links)

    def test_linear_goals_are_not_silently_changed(self):
        raw = deepcopy(self.raw)
        raw['game']['goals'][0]['binary'] = False
        with self.assertRaisesRegex(ValueError, 'binary'):
            export_fixture(raw, 20000, 4, 'development')

    def test_player_count_and_import_partition(self):
        self.assertEqual(partition(5, 'any', 'generated'), 'ood_test')
        for n in (3, 4, 5):
            self.assertEqual(partition(n, 'any', 'development'), 'development')
        self.assertEqual(partition(3, 'same', 'generated'), partition(4, 'same', 'generated'))


if __name__ == '__main__':
    unittest.main()
