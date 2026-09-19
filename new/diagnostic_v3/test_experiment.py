import unittest,json
from copy import deepcopy
from experiment import load,run_case,parse_b,p_request,reference
from training.b_sft.social_bp_training import native_completion

class Repair(unittest.TestCase):
    def test_gold_repair(self):
        for case in load():
            def call(kind,req):
                if kind=='B':return dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_DISTRIBUTION',arguments=json.dumps(dict(zip(('want','neutral','avoid'),case['gold_belief'])))))]),finish_reason='stop')
                return native_completion(case['task'])
            r=run_case(case,call)
            self.assertEqual(r['B_total_variation'],0)
            self.assertTrue(all(c['regret']<=.1+1e-9 for c in r['cells'].values()))
    def test_wrong_belief_harms_reference_decision(self):
        c=next(c for c in load() if c['id'].endswith(':voluntary'))
        self.assertGreater(reference(c,[1/3]*3)['regret'],.1)
        self.assertAlmostEqual(reference(c,c['gold_belief'])['regret'],0)
    def test_invalid_b_blocks_only_dependent_cells(self):
        c=load()[0]
        def call(kind,req):
            return {'finish_reason':'length'} if kind=='B' else native_completion(c['task'])
        r=run_case(c,call)
        self.assertIsNone(r['cells']['model_B_model_P']['utility'])
        self.assertIsNotNone(r['cells']['correct_B_model_P']['utility'])
    def test_no_evidence_bypass(self):
        for c in load():
            r=p_request(c,[1/3]*3);text=r['messages'][1]['content']
            self.assertNotIn('EVENTS IN ORDER',text)
            self.assertNotIn('CORRECT CURRENT BELIEF',text)
            self.assertIn('CURRENT BINDING STATE',text)
            self.assertEqual(r['tools'],c['requests']['P_gold']['tools'])
    def test_probability_rejection(self):
        c=dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_DISTRIBUTION',arguments='{"want":1,"neutral":1,"avoid":0}'))]))
        self.assertEqual(parse_b(c),(None,'format_failure'))
if __name__=='__main__':unittest.main()

class Measurement(unittest.TestCase):
    def test_problem_invariants(self):
        from experiment import audit_cases
        self.assertTrue(audit_cases(load())['same_prompt_actions_payoffs'])
    def test_pair_coverage(self):
        from experiment import summarize
        c=load()[0]
        r=run_case(c,lambda kind,req: {'finish_reason':'length'} if kind=='B' else native_completion(c['task']))
        s=summarize([r],3)
        self.assertEqual(s['gains']['B_repair_gain']['valid_pairs'],0)
        self.assertEqual(s['gains']['P_repair_given_correct_B']['valid_pairs'],1)
        self.assertEqual(s['missing'],2)
    def test_error_cancellation(self):
        from unittest.mock import patch
        from experiment import model_value,reference
        c={'gold_belief':[.1,0,.9],'task':{'teacher':{'per_world_payoffs':[[[0],[0],[0]],[[1],[0],[-1]]]}}}
        with patch('experiment.action_index',return_value=(0,'ok')):
            m=model_value(c,{},[.9,0,.1])
        self.assertAlmostEqual(m['input_belief_planning_regret'],.8)
        self.assertAlmostEqual(m['regret'],0)
        self.assertAlmostEqual(reference(c,[.9,0,.1])['utility'],-.8)
    def test_prefix_bounds_allow_negative_future(self):
        from examples.final_evaluation.adversarial_checks import prefix_bounds,paired_bounds
        g={'goals':[{'goal_id':0,'binary':True,'required_actions':[{'player_id':0,'action_id':0},{'player_id':1,'action_id':0}]}]}
        b=prefix_bounds(g,[[1],[0]],[-1])
        self.assertEqual((b['lower'],b['upper']),(-1,0))
        self.assertEqual(paired_bounds(b,{'lower':0,'upper':0}),[-1,0])
