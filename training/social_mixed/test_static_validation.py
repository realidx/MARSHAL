import unittest
from unittest.mock import patch
from pathlib import Path
from training.social_mixed.reasoning_validation import ReasoningValidator, selection_score
from training.b_sft.social_bp_training import native_completion

class StaticValidationTests(unittest.TestCase):
    def test_static_only_without_interaction_data(self):
        v=ReasoningValidator({},lambda requests: [],concurrency=8)
        # A complete run using native answers; unexpected interaction calls exhaust the iterator.
        tasks=iter(v.tasks)
        def generate(requests):
            return [dict(completion=native_completion(next(tasks))) for _ in requests]
        v.generate=generate
        with patch('training.social_mixed.validation.Episode',side_effect=AssertionError('No selfplay allowed')):
            report=v.run()
        self.assertEqual(report['games'],[])
        self.assertEqual(report['game_calls'],[])
        self.assertEqual({r['task']['paired_view'] for r in report['bp_calls']},{'B','O','Pplus'})
        self.assertFalse(any(k.startswith(('calbench/','games/')) for k in report['metrics']))
        self.assertEqual(selection_score(report['metrics']),[report['metrics']['reasoning/O/macro_accuracy']])
        self.assertTrue(all(r['request']['temperature']==0 for r in report['bp_calls']))
        self.assertFalse(report['protocol']['interaction_enabled'])

    def test_cadence(self):
        import yaml
        for arm in ('outcome','conditioned','decomposed','selfplay'):
            cfg=yaml.safe_load((Path('examples/social_mixed')/(arm+'.yaml')).read_text())
            self.assertEqual(cfg['eval_steps'],20)
            self.assertEqual(cfg['save_steps'],20)

if __name__=='__main__':unittest.main()
