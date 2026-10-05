"""Optional PyGambit integration test: information structure and policy payoffs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

from examples.strategic_slices.compare_sequence_solver import export_efg, validate_encoding, import_profile
from training.strategic_slices.build import sample_parent
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights


@unittest.skipUnless(importlib.util.find_spec('pygambit'), 'Optional isolated PyGambit installation required')
class SequenceExportTests(unittest.TestCase):
    def test_private_information_and_random_contingent_policy_payoffs(self):
        import pygambit as gbt
        raw = sample_parent(2026100703, 2, rounds=1)
        rules = PrivateInvestigationRules(raw)
        tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
            world_weights=world_weights(rules.worlds, raw['background_prior']),
            lookahead_rr=3, seconds=30)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'game.efg'
            export_efg(tree, path)
            game = gbt.read_efg(path)
            validation = validate_encoding(tree, game)
            self.assertTrue(validation['perfect_recall'])
            profile = game.mixed_behavior_profile()
            rng = np.random.default_rng(7)
            for player in game.players:
                for info in player.infosets:
                    for action, probability in zip(info.actions, rng.dirichlet(np.ones(len(info.actions)))):
                        profile[action] = float(probability)
            import_profile(tree, game, profile)
            values = tree.evaluate()
            actual = np.average(values[0], axis=0, weights=tree.world_weights)
            expected = [float(profile.payoff(p)) for p in game.players]
            np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)
            tree.reference_identity()  # Independent privacy audit on imported policy.


if __name__ == '__main__': unittest.main()
