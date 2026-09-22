import unittest
from copy import deepcopy
from training.social_mixed.reasoning_bank import load
from training.social_mixed.feedback_sampling import build_windows,stable
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_training import ReasoningCollector

class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks=load('train');cls.relations=load('train','relations.jsonl')
        cls.windows=build_windows(cls.tasks,cls.relations)
        cls.by={(t['canonical_id'],t['paired_view']):t for t in cls.tasks}

    def test_certified_relations(self):
        self.assertTrue(all(self.windows.values()))
        for kind in ('update','maintain'):
            for a,b in self.windows[kind]:
                x=self.by[a,'B'];y=self.by[b,'B']
                h=x['input']['voluntary_history'];k=y['input']['voluntary_history']
                self.assertLess(len(h),len(k));self.assertEqual(h,k[:len(h)])
                self.assertEqual(x['input']['queries'],y['input']['queries'])
                self.assertEqual(x['teacher']['gold']==y['teacher']['gold'],kind=='maintain')
        for a,b in self.windows['must_change']:
            sa={stable(x) for x in self.by[a,'O']['teacher']['acceptable_actions']}
            sb={stable(x) for x in self.by[b,'O']['teacher']['acceptable_actions']}
            self.assertTrue(sa.isdisjoint(sb))

    def test_no_validation_or_previous_gold(self):
        for pairs in self.windows.values():
            for pair in pairs:
                for cid in pair:
                    t=self.by[cid,'B'];self.assertEqual(t['split'],'train')
                    self.assertNotIn('previous_belief',t['input'])
                    text=request(t)['messages'][1]['content']
                    self.assertNotIn('CORRECT PREVIOUS BELIEF',text)

    def test_resume_identifies_sampling_change(self):
        c=ReasoningCollector({'bp_train':self.tasks},lambda r:[])
        old=deepcopy(c.state);old.pop('feedback_version')
        with self.assertRaises(ValueError):c.restore(old,arm='decomposed')
        c.restore(deepcopy(c.state),arm='decomposed')

if __name__=='__main__':unittest.main()
