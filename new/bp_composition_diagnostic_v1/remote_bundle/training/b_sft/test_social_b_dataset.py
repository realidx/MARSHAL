import unittest
import json
from copy import deepcopy

from training.b_sft.social_b_dataset import mine, validate_pair, random_fixture, transition
from training.b_sft.social_b_oracle import BeliefOracle, forward_fixture


class DatasetTests(unittest.TestCase):
    def test_authored_temporal_pairs_and_corruption(self):
        raw, prefix = forward_fixture()
        records, labels, pairs, audit = mine(raw, prefix, 1, 2)
        self.assertFalse(audit['failures'])
        self.assertTrue({'formation', 'maintain', 'strength_change'} <= {p['category'] for p in pairs})
        for p in pairs:
            validate_pair(raw, prefix, records[p['before']], records[p['after']], p, labels)
            validate_pair(raw, prefix, records[p['before']], records[p['after']],
                          json.loads(json.dumps(p)), labels)
            self.assertNotEqual(p['actor'], raw['ego'])
        p = next(p for p in pairs if p['category'] == 'formation')
        broken = deepcopy(labels)
        broken[p['after']]['answer']['possible_preferences'] = ['avoid', 'want', 'neutral']
        with self.assertRaises(AssertionError):
            validate_pair(raw, prefix, records[p['before']], records[p['after']], p, broken)
        for r in records.values():
            inp = r['input']
            self.assertFalse({'answer', 'witness_world', 'comparisons', 'category', 'values'} & inp.keys())
            self.assertEqual(inp['public_type_catalogues'], raw['type_catalogues'])

    def test_seeded_query_is_independent_and_setup_not_evidence(self):
        a = random_fixture(920001, hidden=1)
        self.assertEqual(a, random_fixture(920001, hidden=1))
        raw, prefix, target, goal = a
        rows = raw['type_catalogues'][str(target)]
        self.assertEqual([r[goal] for r in rows], [1, 0, -1])
        self.assertEqual(len({tuple(r[:goal] + r[goal+1:]) for r in rows}), 1)
        o = BeliefOracle(raw, prefix)
        self.assertEqual(len(o.belief(target, goal)['possible_preferences']), 3)
        self.assertTrue(all(not e['comparisons'] for e in o.events))

    def test_coverage_does_not_call_full_uncertainty_maintenance(self):
        b = lambda values: {'possible_preferences': values}
        self.assertEqual(transition(b(['want','neutral','avoid']), b(['want','neutral'])), 'formation')
        self.assertEqual(transition(b(['want','neutral']), b(['neutral'])), 'update')
        self.assertEqual(transition(b(['want','neutral']), b(['want','neutral'])), 'maintain')
        self.assertEqual(transition(b(['want','neutral','avoid']), b(['want','neutral','avoid'])), 'uninformative')
        with self.assertRaises(AssertionError):
            transition(b(['want']), b(['want','avoid']))


if __name__ == '__main__':
    unittest.main()
