"""B/P-only has no training episodes; evaluation remains shared across arms."""
from collections import Counter
import unittest
from unittest.mock import patch
from training.social_mixed.core import Collector, load_data, arm_mixture
from training.social_mixed.distribution_sampling import select
from training.social_mixed.test_core import generated
from training.social_mixed.run import validate_course_coverage


def fake_generate(requests):
    outputs=[]
    for req in requests:
        names={t['function']['name'] for t in req['tools']}
        outputs.append(generated('PASS' if 'PASS' in names else 'REJECT',{}))
    return outputs


class BPOnlyTests(unittest.TestCase):
    def test_no_selfplay_access_or_episode_and_exact_bp_weights(self):
        data=load_data();bp_data={'bp_train':data['bp_train']}
        with patch('training.social_mixed.core.Episode',side_effect=AssertionError('Training must not start self-play')):
            rows,units,games,metrics=Collector(bp_data,fake_generate,concurrency=8).collect(3,'bp',token_target=1)
        self.assertFalse(games)
        self.assertEqual({r['kind'] for r in rows},{'B','P'})
        self.assertEqual({r['task_id'] for r in rows},{t['id'] for t in select(data['bp_train'],3,42)})
        self.assertEqual(set(Counter(u['group'] for u in units).values()),{8})
        for kind in ('B','P'):
            self.assertAlmostEqual(sum(r['loss_weight'] for r in rows if r['kind']==kind)/len(rows),.5)
        self.assertEqual(metrics['generated_tokens'],sum(len(r['response_ids']) for r in rows))
        self.assertEqual(metrics['admitted_reset_groups'],0)
        self.assertEqual(metrics['peak_active_games'],0)

    def test_validation_matches_mixed_and_includes_selfplay(self):
        collector=Collector(load_data(),fake_generate,concurrency=8)
        bp=collector.collect(0,'bp',validation=True)
        mixed=collector.collect(0,'mixed',validation=True)
        self.assertEqual(bp,mixed)
        self.assertTrue(bp[2])
        self.assertEqual({r['kind'] for r in bp[0]},{'B','P','selfplay'})

    def test_bp_requires_complete_curriculum(self):
        with self.assertRaisesRegex(ValueError,'missing kernels'):
            validate_course_coverage({'bp_train':[dict(kernel='B1')]},'bp')
        self.assertEqual(arm_mixture('bp'),{'B':.5,'P':.5})
        with self.assertRaises(KeyError):arm_mixture('unknown')

if __name__=='__main__':unittest.main()
