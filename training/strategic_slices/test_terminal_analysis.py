import copy
import unittest
import numpy as np
from .terminal_analysis import audit_game, summarize_audit, visible_posterior
from .terminal_d import TerminalRollout, mock_generate


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_d import TerminalDTests
        TerminalDTests.setUpClass()
        cls.tree,cls.rows,cls.cfg=TerminalDTests.tree,TerminalDTests.rows,TerminalDTests.cfg

    def test_replay_and_hidden_world_isolation(self):
        cache={}
        for row in self.rows:
            row=dict(row,family='fixture')
            job=TerminalRollout(self.tree,row,0,42)
            while job.status=='running':
                req=job.request(self.cfg);job.accept(mock_generate([req])[0],req)
            game=job.record()
            result=audit_game(self.tree,row,game,self.cfg,cache)
            self.assertEqual(len(result['decisions']),game['controlled_decisions'])
            self.assertGreaterEqual(result['decision_gap_sum'],0)
            self.assertAlmostEqual(result['decisions'][0]['gap'],game['calls'][0]['first_action_oracle_gap'])
            for call in result['decisions']:
                w=np.array(call['posterior'])
                for wi in np.flatnonzero(w):
                    np.testing.assert_allclose(visible_posterior(self.tree,call['node'],row['ego'],w,int(wi)),w)
            altered=copy.deepcopy(game);altered['calls'][0]['request']['seed']+=1
            with self.assertRaisesRegex(ValueError,'request or seed'):
                audit_game(self.tree,row,altered,self.cfg,cache)
            rounded=copy.deepcopy(game)
            rounded['utility']+=1e-16
            rounded['terminal_utilities'][row['ego']]+=1e-16
            audit_game(self.tree,row,rounded,self.cfg,cache)
            rounded['utility']+=1e-3
            with self.assertRaisesRegex(ValueError,'Native utility mismatch'):
                audit_game(self.tree,row,rounded,self.cfg,cache)

    def test_failure_is_null_full_loss_and_keeps_prefix(self):
        row=dict(self.rows[0],family='fixture')
        job=TerminalRollout(self.tree,row,0,42);req=job.request(self.cfg)
        answer=mock_generate([req])[0];answer['completion']['finish_reason']='length';job.accept(answer,req)
        report=audit_game(self.tree,row,job.record(),self.cfg,{})
        self.assertIsNone(report['decision_gap_sum'])
        self.assertIsNone(report['decisions'][0]['gap'])
        self.assertEqual(report['valid_prefix_gap_sum'],0)

    def test_later_step_contrast_and_mixed_completion_are_retained(self):
        row=dict(self.rows[0],family='fixture')
        def decision(n,gap):
            return dict(decision=n,prompt_sha256=f'prompt-{n}',gap=gap,action={},after_model_query=n>1,answer_sensitive=False)
        games=[dict(status='terminal',decision_gap_sum=0,decisions=[decision(1,0),decision(2,0)]),
               dict(status='terminal',decision_gap_sum=.5,decisions=[decision(1,0),decision(2,.5)]),
               dict(status='truncated',decision_gap_sum=None,decisions=[decision(1,None)])]
        r=summarize_audit(row,games)
        self.assertTrue(r['later_step_value_contrast'])
        self.assertTrue(r['any_step_value_contrast'])
        self.assertTrue(r['mixed_completion'])
        self.assertAlmostEqual(r['mean_decision_gap_completed'],.25)


if __name__=='__main__':unittest.main()
