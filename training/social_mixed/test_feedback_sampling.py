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

    def test_fixed_coverage_relations_and_resume(self):
        from training.social_mixed.coverage_sampling import plan
        c=ReasoningCollector({'bp_train':self.tasks},lambda r:[])
        for step in range(50):
            c.state['block']=step
            batch=plan(c)
            for view in ('O','B','Pplus'):
                ids=[cid for cid,v,slot in batch if v==view]
                self.assertEqual(len(ids),4);self.assertEqual(len(set(ids)),4)
            for kind,prefix in [('must_change','must_change'),('update','update'),('maintain','maintain')]:
                pair=tuple(cid for cid,v,slot in batch if slot.startswith(prefix))
                if pair:self.assertIn(pair,self.windows[kind])
            for cid,v,slot in batch:
                if v=='Pplus':self.assertTrue(c.views[cid,v].get('p_train_eligible',True))
        # No task can run far ahead of the global frontier, even inside a tiny relation pool.
        for view in ('O','B','Pplus'):
            counts=[c.state['coverage'].get(view+':'+cid,{}).get('count',0)
                    for cid in c.schedule if view!='Pplus' or c.views[cid,view].get('p_train_eligible',True)]
            self.assertLessEqual(max(counts)-min(counts),1)
        d=ReasoningCollector({'bp_train':self.tasks},lambda r:[])
        d.restore(deepcopy(c.state),arm='decomposed')
        self.assertEqual(plan(c),plan(d))
        bad=deepcopy(c.state);bad.pop('coverage_version')
        with self.assertRaises(ValueError):d.restore(bad,arm='decomposed')

    def test_P_difficulty_ignores_audit_history_and_gold(self):
        from training.social_mixed.task_difficulty import describe
        t=deepcopy(next(t for t in self.tasks if t['paired_view']=='Pplus'))
        before=describe(t)
        t['input']['voluntary_history']=[{'action':'PASS'}]*100
        t['teacher']={}
        self.assertEqual(before,describe(t))

    def test_all_three_arms_reject_old_sampling_state(self):
        c=ReasoningCollector({'bp_train':self.tasks},lambda r:[])
        old=deepcopy(c.state);old['coverage_version']='d-coverage-fixed12-pcategories-v2'
        for arm in ('outcome','conditioned','decomposed'):
            with self.assertRaises(ValueError):c.restore(old,arm=arm)

    def test_resume_identifies_sampling_change(self):
        c=ReasoningCollector({'bp_train':self.tasks},lambda r:[])
        old=deepcopy(c.state);old.pop('feedback_version')
        with self.assertRaises(ValueError):c.restore(old,arm='decomposed')
        c.restore(deepcopy(c.state),arm='decomposed')

if __name__=='__main__':unittest.main()
