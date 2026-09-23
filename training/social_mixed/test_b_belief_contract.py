import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from training.social_mixed.b_belief_contract import accepted_favored
from training.social_mixed.reasoning_scoring import score

class BeliefContractTests(unittest.TestCase):
    def test_boundaries_and_support(self):
        self.assertEqual(set(accepted_favored(dict(want=.45,neutral=.40,avoid=.15))),{'want','neutral','undetermined'})
        self.assertEqual(set(accepted_favored(dict(want=.4,neutral=.3,avoid=.3))),{'want','neutral','avoid','undetermined'})
        self.assertEqual(accepted_favored(dict(want=.5,neutral=.25,avoid=.25)),['want'])
        self.assertEqual(accepted_favored(dict(want=1,neutral=0,avoid=0)),['want'])
        self.assertEqual(set(accepted_favored(dict(want=.5,neutral=.5,avoid=0))),{'want','neutral','undetermined'})

    def test_end_to_end_score_and_prompt(self):
        from training.social_mixed.reasoning_bank import load
        from training.b_sft.social_bp_training import native_completion
        from training.social_mixed.paired_requests import request
        t=deepcopy(next(t for t in load('train') if t['paired_view']=='B'))
        t['teacher']['preference_weights']=dict(want=.45,neutral=.40,avoid=.15)
        t['teacher']['gold']=dict(possible_preferences=['want','neutral','avoid'],favored='undetermined')
        completion=native_completion(t)
        call=completion['raw_message']['tool_calls'][0]['function']
        args=json.loads(call['arguments']);args['judgments'][0]['favored']='neutral';call['arguments']=json.dumps(args)
        scored=score(t,completion)
        self.assertTrue(scored['correct']);self.assertFalse(scored['strict_correct'])
        args['judgments'][0]['possible_preferences']=['want','neutral'];call['arguments']=json.dumps(args)
        self.assertFalse(score(t,completion)['correct'])
        completion['finish_reason']='length';self.assertFalse(score(t,completion)['correct'])
        prompt=request(t)['messages'][-1]['content']
        self.assertIn('at most 10 percentage points',prompt)
        self.assertNotIn('use undetermined if the top support is tied',prompt)
        self.assertIn('imposed events are not evidence',prompt)

if __name__=='__main__':unittest.main()
