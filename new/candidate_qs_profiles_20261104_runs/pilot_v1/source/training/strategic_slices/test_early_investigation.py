"""Analytic and native-tree checks of full-terminal investigation diagnostics."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

import numpy as np

from .early_investigation import terminal_response_values, measure_early_investigation
from .values import extreme_value


def toy(informative=True):
    def action(kind):
        return NS(to_dict=lambda: {'action': kind})
    def leaf(values):
        return NS(actor=None, children=[], payoff=np.array(values, dtype=float)[:, None])
    entries = [NS(actor=0, children=[1, 2], actions=[action('INVESTIGATE'), action('PASS')]),
               NS(actor=0, children=[3, 4], actions=[action('A'), action('B')]),
               leaf([.6, .6]), leaf([1, 0]), leaf([0, 1])]
    return NS(entries=entries, w=2, world_weights=np.array([.5, .5]),
        policy=[np.array([[0., 0.], [1., 1.]]), np.array([[1., 1.], [0., 0.]]), None, None, None],
        information_groups={0: [np.array([0, 1])],
                            1: [np.array([0]), np.array([1])] if informative else [np.array([0, 1])]})


class EarlyInvestigationTests(unittest.TestCase):
    def test_optimizes_future_decisions_and_values_query_access(self):
        tree=toy()
        full=terminal_response_values(tree, 0)
        banned=terminal_response_values(tree, 0, forbid_queries=True)
        self.assertAlmostEqual(float(tree.world_weights @ full[0]), 1.)
        self.assertAlmostEqual(float(tree.world_weights @ banned[0]), .6)

    def test_does_not_use_unobserved_world_identity(self):
        tree=toy(informative=False)
        full=terminal_response_values(tree, 0)
        self.assertAlmostEqual(float(tree.world_weights @ full[1]), .5)
        self.assertAlmostEqual(float(tree.world_weights @ full[0]), .6)

    def test_native_full_response_matches_independent_entrance_solver(self):
        from examples.strategic_slices.check_entry_information import restore
        folder=Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        fixture=json.loads((folder/'public_history_information.json').read_text())
        tree=restore(fixture,fixture,folder/fixture['reference_file'])
        rows=measure_early_investigation(tree, 'fixture')
        self.assertEqual({r['ego'] for r in rows}, set(range(tree.n)))
        for ego in range(tree.n):
            candidates=[r for r in rows if r['ego']==ego]
            self.assertAlmostEqual(sum(r['oracle_information_set_mass'] for r in candidates), 1.)
            row=max(candidates, key=lambda r: r['oracle_information_set_mass'])
            independent=extreme_value(tree, ego, row['root_index'], row['world_weights'],
                                      2*len(tree.rules.spec.round_robin))
            np.testing.assert_allclose(independent['root_Q'], row['root_Q'], atol=1e-8, rtol=0)
            self.assertAlmostEqual(independent['value'], row['V_full'])
            self.assertEqual(row['own_proposals_after_investigation'], 0)


if __name__ == '__main__':
    unittest.main()
