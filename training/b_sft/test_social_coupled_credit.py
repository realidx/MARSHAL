import unittest
from training.b_sft.social_coupled_credit import credits,demo,NativeEpisode,fixture,experiment,greedy_partner,normalized_utility

class CoupledCreditTests(unittest.TestCase):
    def test_credit_separates_b_means_from_p_conditional_outcomes(self):
        c=credits([[0,2],[2,2]])
        self.assertEqual(c['B_credit'],[-1,1])
        self.assertEqual(c['P_credit'],[[-2,2],[0,0]])
        self.assertEqual(credits([[5,7],[7,7]])['B_credit'],c['B_credit'])

    def test_incomplete_branches_are_not_selection_biased(self):
        self.assertFalse(credits([[0,None],[1,1]])['mask'])
        with self.assertRaises(ValueError):credits([[1],[2]])

    def test_native_outcomes_and_unknown_partner_symmetry(self):
        d=demo();single=d['single_world_control'];balanced=d['balanced_uncertainty_control']
        self.assertEqual(single['outcome_matrix'],[[.5,0],[0,0]])
        self.assertEqual(single['credit']['B_credit'],[.25,-.25])
        self.assertEqual(balanced['outcome_matrix'],[[.25,0],[.25,0]])
        self.assertEqual(balanced['credit']['B_credit'],[0,0])
        for r in (single,balanced):
            for b in r['branches']:
                for o in b['outcomes']:
                    self.assertTrue(o['terminal'])
                    raw,_=fixture();e=NativeEpisode(raw,o['history'])
                    self.assertTrue(e.node.state.is_terminal)
            for bi in (0,1):
                self.assertEqual([x['p_seed'] for x in r['branches'] if x['B_index']==bi],[200007,200008])

    def test_native_illegal_submission_leaves_state_unchanged(self):
        raw,prefix=fixture();env=NativeEpisode(raw,prefix);before=env.visible()
        with self.assertRaises(ValueError):env.step({'action_index':0})
        self.assertEqual(before,env.visible())

    def test_failed_rollout_masks_comparison_without_terminal_reward(self):
        raw,prefix=fixture();base=NativeEpisode(raw,prefix)
        def b(ctx,rng):
            self.assertNotIn('world',ctx)
            ctx['history'].clear()
            return 'Uncertain partner preferences.'
        result=experiment(raw,prefix,base.worlds,b,
                          lambda ctx,b,rng:{'action_index':0},
                          lambda ctx,rng:ctx['legal_actions'][0],greedy_partner)
        self.assertFalse(result['credit']['mask'])
        self.assertEqual(result['outcome_matrix'],[[None,None],[None,None]])
        for branch in result['branches']:
            for outcome in branch['outcomes']:
                self.assertFalse(outcome['terminal'])
                self.assertIsNone(outcome['reward'])
                self.assertEqual(outcome['history'],prefix)
        self.assertEqual(base.visible()['history'],prefix)

    def test_terminal_reward_normalization(self):
        self.assertEqual(normalized_utility(-2,[1,-2]),0)
        self.assertEqual(normalized_utility(1,[1,-2]),1)
        with self.assertRaises(ValueError):normalized_utility(0,[0,0])

if __name__=='__main__':unittest.main()
