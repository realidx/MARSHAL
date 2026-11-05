"""Counterfactual signal diagnostics must reveal exactly the declared slot."""
import json
from pathlib import Path
import unittest

from examples.strategic_slices.investigate_game_mechanics import gifted_values
from .test_early_investigation import toy
from .early_investigation import terminal_response_values


class GameMechanicsTests(unittest.TestCase):
    def test_free_signal_can_improve_terminal_decisions(self):
        tree=toy(informative=False)
        tree.worlds=[((1,),(-1,1)),((1,),(-1,-1))]
        old=tree.information_groups
        before=float(tree.world_weights @ terminal_response_values(tree,0)[0])
        after=float(tree.world_weights @ gifted_values(tree,0,(1,1))[0])
        self.assertAlmostEqual(before,.6)
        self.assertAlmostEqual(after,1.)
        self.assertIs(tree.information_groups,old)
        self.assertEqual(len(tree.information_groups[0]),1)

    def test_constant_slot_does_not_leak_other_preferences(self):
        tree=toy(informative=False)
        tree.worlds=[((1,),(-1,1)),((1,),(-1,-1))]
        value=float(tree.world_weights @ gifted_values(tree,0,(1,0))[0])
        self.assertAlmostEqual(value,.6)

    def test_schedule_controls_preserve_native_round_validity(self):
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        folder=Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        raw=json.loads((folder/'information_acquisition.json').read_text())['raw']
        for schedule in ([1,0,0,1],[1,0,1,0]):
            raw['game']['round_robin']=schedule
            self.assertEqual(len(PrivateInvestigationRules(raw).spec.round_robin),4)
        raw['game']['round_robin']=[0,0,1]
        with self.assertRaises(ValueError):PrivateInvestigationRules(raw)

    def test_diagnostic_candidates_obey_complete_native_contract(self):
        from examples.strategic_slices.search_native_acquisition import candidate
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        for geometry in ('compact', 'three', 'three_rich', 'three_targeted', 'fixture', 'historical'):
            for seed in range(12):
                raw = candidate(seed, geometry)
                rules = PrivateInvestigationRules(raw)
                self.assertEqual(len(rules.worlds), 3)
                self.assertEqual(rules.initial().state.turn_index, 0)
                n = rules.spec.n_players
                for start in range(0, len(rules.spec.round_robin), n):
                    self.assertEqual(sorted(rules.spec.round_robin[start:start+n]), list(range(n)))

    def test_native_initial_acquisition_witness(self):
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        from training.b_sft.preference_contract import world_weights
        from .bounded import BoundedPrivateWindow
        from .values import masked_answer_value, window_values
        folder = Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        raw = json.loads((folder/'native_acquisition_three_player.json').read_text())['raw']
        rules = PrivateInvestigationRules(raw)
        tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
            world_weights=world_weights(rules.worlds, raw['background_prior']),
            lookahead_rr=3, seconds=60, max_nodes=20000).solve()
        self.assertEqual(tree.audit_native()['cutoff_leaves'], 0)
        weights = tree.world_weights
        value = masked_answer_value(tree, ego=0, root_index=0,
            root_weights=weights, query_slot=(2,1), k=2)
        self.assertAlmostEqual(value['V_full'], -.25)
        self.assertAlmostEqual(value['V_mask'], -1/3)
        self.assertAlmostEqual(value['S'], 1/12)
        self.assertGreater(window_values(tree, 0, 0, weights, 2)['C_span'], .1)
        queries = [i for i, a in enumerate(tree.entries[0].actions)
                   if a.to_dict() == dict(action='INVESTIGATE', player=2, goal=1)]
        self.assertEqual(len(queries), 1)
        self.assertAlmostEqual(float(weights @ tree.policy[0][queries[0]]), 1.)


if __name__=='__main__':unittest.main()
