"""Coverage gates and native menu/negative-payoff control regressions."""
import unittest
from pathlib import Path

from training.b_sft.online_social import OnlineSocial
from training.b_sft.social_dataset_v4 import menu_fixture, require_coverage, post_evidence
from training.b_sft.social_lm_eval import load_pack


class DatasetV4Tests(unittest.TestCase):
    def test_menu_choices_match_complete_binding_bundles(self):
        for second in (False, True):
            raw, prefix = menu_fixture(second)
            env = OnlineSocial(raw, prefix)
            values = env.p_reference_values()
            self.assertEqual(values['basis'], 'direct_terminal')
            best = max(values['values'], key=lambda v: v['value'])
            self.assertEqual(best['action'], {'response': 'CHOOSE_2' if second else 'CHOOSE_1'})
            self.assertEqual(best['value'], 2 if second else 1)

    def test_empty_or_old_coverage_cannot_be_published_as_repaired(self):
        with self.assertRaisesRegex(ValueError, 'evidence-followed-by-planning'):
            require_coverage([])

    def test_generated_smoke_has_informed_planning_and_balanced_controls(self):
        path = Path(__file__).resolve().parents[2]/'new/local_data/social_smoke_v4'
        if not path.exists(): self.skipTest('Build the v4 smoke pack first')
        _, points = load_pack(path, 'both')
        rows = [p['row'] for p in points]
        require_coverage(rows, smoke=True)
        self.assertTrue(all(r['teacher']['B_aux_mask'] and r['teacher']['P_reference']['mask'] for r in rows))
        with self.assertRaisesRegex(ValueError, 'evidence-followed-by-planning'):
            require_coverage([r for r in rows if not post_evidence(r)], smoke=True)
        # Removing the negative controls must fail even if positive accuracy is easy.
        rows = [r for r in rows if not (r['supervision']['P_basis']=='direct_terminal'
                                        and r['supervision']['response_target']=='reject')]
        with self.assertRaisesRegex(ValueError, 'balanced'):
            require_coverage(rows, smoke=True)


if __name__ == '__main__': unittest.main()
