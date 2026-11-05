"""Meaningful own-first, decoder failure and same-context group checks."""
import unittest
from .scoring import score,values


class ResponseScoringTests(unittest.TestCase):
    def response(self,own,others):
        return dict(actions=[dict(response='REJECT'),dict(response='ACCEPT')],Q=own,Q_others=others)

    def test_social_gain_cannot_compensate_own_loss(self):
        row=self.response([1.,.999],[0.,10000.])
        self.assertTrue(score(row,0)['correct']);self.assertFalse(score(row,1)['correct'])
        self.assertEqual(score(row,1)['active_axis'],'own')
        self.assertAlmostEqual(score(row,1)['task_reward'],-.001)

    def test_own_tie_has_continuous_social_regret(self):
        row=self.response([0.,0.],[2.,4.])
        self.assertEqual(score(row,0)['task_reward'],-2.)
        self.assertFalse(score(row,0)['correct']);self.assertTrue(score(row,1)['correct'])
        self.assertEqual(score(row,1)['active_axis'],'others_sum')

    def test_proposal_has_no_social_tie_break(self):
        row=dict(actions=[dict(action='PASS'),dict(action='INVESTIGATE',player=1,goal=0)],Q=[1.,1.],Q_others=[0.,9.])
        self.assertTrue(score(row,0)['correct']);self.assertTrue(score(row,1)['correct'])
        self.assertEqual(score(row,0)['active_axis'],'own')

    def test_both_response_levels_tied_accept_both(self):
        row=self.response([1.,1.],[2.,2.])
        self.assertEqual(values(row)[3].tolist(),[0,1])
        self.assertTrue(all(score(row,i)['task_reward']==0 for i in range(2)))

    def test_matches_saved_response_tolerance(self):
        tied=self.response([0.,5e-10],[3.,0.]);strict=self.response([0.,2e-9],[3.,0.])
        self.assertEqual(values(tied)[-1],'others_sum');self.assertEqual(values(strict)[-1],'own')

    def test_invalid_and_truncated_keep_separate_penalty(self):
        row=self.response([0.,0.],[2.,4.])
        for status in ['invalid_action','truncated']:
            result=score(row,None,status)
            self.assertEqual(result['task_reward'],-2.);self.assertEqual(result['protocol_penalty'],-.2)
            self.assertFalse(result['correct'])

    def test_unchanged_grpo_groups_receive_real_signal(self):
        from training.strategic_slices.terminal_training import group_advantages
        row=self.response([0.,0.],[2.,4.]);r=[score(row,i)['task_reward']for i in [0,1]*4]
        advantages,_,_=group_advantages(r)
        self.assertLess(advantages[0],0);self.assertGreater(advantages[1],0)


if __name__=='__main__':unittest.main()
