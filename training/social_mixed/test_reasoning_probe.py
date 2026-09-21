import unittest
from training.social_mixed.reasoning_probe import summarize

class ProbeTests(unittest.TestCase):
    def test_masked_invalid_and_truncated_not_semantic_contrast(self):
        def row(status='ok',reward=0,eligible=True,finish='stop',outcome='negative'):
            return dict(canonical_id='c',view='Pplus',package_id='p',completion={'finish_reason':finish},
                        score=dict(status=status,reward=reward,semantic_eligible=eligible,semantic_outcome=outcome))
        rows=[row(reward=1,outcome='positive'),row(),row(eligible=False,outcome='masked'),
              row(status='format_failure',eligible=False),row(finish='length',eligible=False)]
        m=summarize(rows)['Pplus']
        self.assertEqual((m['positive'],m['negative'],m['semantic_masked'],m['invalid_nontruncated'],m['truncated']),(1,1,1,1,1))
        self.assertEqual(m['semantic_mixed_groups'],1)
        m=summarize(rows[:1]+rows[2:])['Pplus']
        self.assertEqual(m['semantic_mixed_groups'],0)
        self.assertEqual(m['one_scored_groups'],1)

if __name__=='__main__':unittest.main()
