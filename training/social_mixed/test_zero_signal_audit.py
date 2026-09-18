"""Negative controls for the low-signal data audit."""
from copy import deepcopy
import unittest
from training.social_mixed.audit_zero_signal import SOURCE, OUT, read, audit_task, interface_check


class AuditControls(unittest.TestCase):
    def test_visible_reconstruction_rejects_corrupt_belief_label(self):
        task = deepcopy(next(t for t in read(SOURCE/'bp_train.jsonl')
                             if t['id'] == '7cd2fc6f9dba54d841b2'))
        task['teacher']['gold']['possible_preferences'] = ['neutral']
        with self.assertRaises(AssertionError):
            audit_task(task)

    def test_empty_self_action_survives_interface(self):
        rows = read(OUT/'bridge_candidates.jsonl')
        targets = [t for t in rows if t['bridge_target'] == 'ordinary_alternative_empty_self']
        self.assertEqual(len(targets), 4)
        for task in targets:
            result = interface_check(task)
            self.assertTrue(result['all_passed'])
            self.assertTrue(result['gold_calls'])
            for call in result['gold_calls']:
                self.assertEqual(call['arguments']['self_commitments'], [])


if __name__ == '__main__':
    unittest.main()
