import unittest

from semantic_sufficiency import certify


def payoffs(first, second):
    return [[[value, 0.] for value in first],
            [[value, 0.] for value in second]]


class SemanticSufficiencyCertificate(unittest.TestCase):
    def test_undetermined_region_detects_changed_optimum(self):
        judgment = {
            'possible_preferences': ['want', 'neutral', 'avoid'],
            'favored': 'undetermined',
        }
        certificate = certify(judgment, payoffs([0, 0, 0], [1, 0, -1]))
        self.assertFalse(certificate['decision_sufficient'])
        self.assertGreater(len(certificate[
            'distinct_vertex_optimal_action_sets']), 1)

    def test_singleton_support_is_decision_sufficient(self):
        judgment = {
            'possible_preferences': ['want'],
            'favored': 'want',
        }
        certificate = certify(judgment, payoffs([0, 0, 0], [1, 0, -1]))
        self.assertTrue(certificate['decision_sufficient'])
        self.assertEqual(certificate['invariant_optimal_action_indices'], [1])

    def test_favored_region_is_checked_beyond_one_posterior(self):
        judgment = {
            'possible_preferences': ['want', 'neutral', 'avoid'],
            'favored': 'want',
        }
        certificate = certify(judgment, payoffs([0, 0, 0], [1, 0, -1]))
        self.assertTrue(certificate['decision_sufficient'])
        self.assertEqual(certificate['invariant_optimal_action_indices'], [1])
        self.assertGreater(len(certificate['components'][0]['vertices']), 1)

    def test_invariant_tie_set_is_preserved(self):
        judgment = {
            'possible_preferences': ['want', 'neutral', 'avoid'],
            'favored': 'undetermined',
        }
        certificate = certify(judgment, payoffs([1, 2, 3], [1, 2, 3]))
        self.assertTrue(certificate['decision_sufficient'])
        self.assertEqual(certificate['invariant_optimal_action_indices'], [0, 1])


if __name__ == '__main__':
    unittest.main()
