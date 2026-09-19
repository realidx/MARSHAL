import unittest,json
from copy import deepcopy
from evaluate import load,score,summarize
from training.b_sft.social_bp_training import native_completion

class Pilot(unittest.TestCase):
    def test_gold_and_truncation(self):
        _,tasks,_=load()
        for t in tasks.values():
            if t['task']=='analytic_B':c=dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_BELIEFS',arguments=json.dumps(t['teacher']['gold'])))]),finish_reason='stop')
            else:c=native_completion(t)
            self.assertTrue(score(t,c)['correct'],t['id'])
            c['finish_reason']='length';self.assertFalse(score(t,c)['correct'])
    def test_missing_not_zero(self):
        _,tasks,_=load();summary,_=summarize([],tasks,3)
        self.assertTrue(all(r['accuracy'] is None for r in summary['conditions'].values()))
    def test_inverse_bayes(self):
        _,tasks,_=load()
        for t in tasks.values():
            if t['task']!='analytic_B':continue
            l=t['teacher']['likelihood'];self.assertEqual(t['teacher']['posterior'],[p/sum(l) for p in l])
    def test_p_tools_match(self):
        _,_,r=load()
        for v in ('voluntary','preset'):
            prefix='binary_complementarity:'+v+':'
            self.assertEqual(r[prefix+'P_gold']['request']['tools'],r[prefix+'P_infer']['request']['tools'])
if __name__=='__main__':unittest.main()
