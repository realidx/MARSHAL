import unittest
from copy import deepcopy
from collections import Counter
from training.social_mixed.compact_bank import load
from training.social_mixed.reasoning_training import ReasoningCollector
from training.social_mixed.coverage_sampling import plan
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_scoring import score
from training.b_sft.social_bp_training import native_completion

class CompactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows,meta,sha=load()
        cls.data=dict(bp_train=rows,compact_metadata=meta,compact_bank_sha256=sha)

    def test_interfaces_and_joint_pool(self):
        rows=self.data['bp_train']
        self.assertEqual(len(rows),600)
        self.assertEqual(Counter(t['paired_view'] for t in rows),dict(O=200,B=200,Pplus=200))
        self.assertTrue(all(t['split']=='train' and t['p_train_eligible'] for t in rows))
        for t in rows:
            req=request(t)
            self.assertTrue(req['messages'])
            if t['paired_view']!='Pplus':self.assertTrue(score(t,native_completion(t))['correct'])
            else:
                self.assertIn('positive',t['p_supervision']['action_states'])
                self.assertIn('negative',t['p_supervision']['action_states'])

    def test_operation_links_and_source_preservation(self):
        import json
        from training.social_mixed.compact_bank import PATH, SOURCE
        from training.social_mixed.operation_curriculum import evidence_input
        source={t['id']:t for t in map(json.loads,(SOURCE/'common_train.jsonl').read_text().splitlines())}
        by={t['canonical_id']:t for t in self.data['bp_train'] if t['paired_view']=='O'}
        for t in self.data['bp_train']:
            for field in ('input','teacher','p_supervision','split'):
                self.assertEqual(t.get(field),source[t['id']].get(field))
        links=list(map(json.loads,(PATH/'operation_links.jsonl').read_text().splitlines()))
        for r in links:
            self.assertIn(r['left'],by);self.assertIn(r['right'],by)
            if r['kind'] in ('prior_contrast','result_contrast'):
                a=evidence_input(by[r['left']]);b=evidence_input(by[r['right']])
                self.assertNotEqual(a.pop(r['changed_field']),b.pop(r['changed_field']))
                self.assertEqual(a,b)
        self.assertTrue(any(r['kind']=='same_scene_operation_link' for r in links))

    def test_four_complete_rounds_and_resume(self):
        c=ReasoningCollector(self.data,lambda r:[])
        for step in range(200):
            c.state['block']=step
            batch=plan(c)
            self.assertEqual(len(set((cid,v) for cid,v,_ in batch)),12)
            if step in (49,99,149,199):
                self.assertEqual(len(c.state['coverage']),600)
                self.assertEqual({x['count'] for x in c.state['coverage'].values()},{(step+1)//50})
        d=ReasoningCollector(self.data,lambda r:[])
        d.restore(deepcopy(c.state),arm='decomposed')
        self.assertEqual(plan(c),plan(d))
        bad=deepcopy(c.state);bad.pop('compact_bank_sha256')
        with self.assertRaises(ValueError):d.restore(bad,arm='decomposed')

if __name__=='__main__':unittest.main()
