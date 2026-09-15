from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from training.b_sft.favored_belief import marginal, score_belief, verify, export_pair, load_fixture


class FavoredBeliefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=json.loads((Path(__file__).parent/'fixtures/favored_belief_regression.json').read_text())

    def test_joint_marginal_and_robustness(self):
        worlds=(((0,),(-1,1)),((0,),(-1,0)),((0,),(0,1)))
        b=marginal(worlds,1,0)
        self.assertEqual(b['answer'],dict(possible_preferences=['neutral','avoid'],favored='avoid'))
        self.assertEqual(marginal(worlds,1,0,2)['answer']['favored'],'undetermined')
        with self.assertRaises(ValueError):marginal(worlds+worlds[:1],1,0)
        with self.assertRaises(ValueError):marginal(worlds,1,0,float('nan'))

    def test_semantic_reward_and_missing_teacher(self):
        a=dict(possible_preferences=['want','neutral'],favored='want')
        self.assertEqual(score_belief(a,a)['score'],0)
        b=dict(a,favored='neutral')
        self.assertEqual(score_belief(b,a)['score'],-.5)
        self.assertIsNone(score_belief(a,None)['score'])
        self.assertFalse(score_belief(a,dict(possible_preferences=a['possible_preferences']))['favored_mask'])
        self.assertFalse(score_belief(dict(possible_preferences=['want'],favored='undetermined'),a)['format_valid'])

    def test_independent_replay_and_tamper_rejection(self):
        self.assertTrue(verify(self.w))
        w=deepcopy(self.w);w['left']['belief']['answer']['favored']='neutral'
        with self.assertRaises(ValueError):verify(w)
        w=deepcopy(self.w);w['right']['history']=w['left']['history']
        with self.assertRaises(ValueError):verify(w)

    def test_no_injected_posterior_or_linear_conversion(self):
        for key in ['posterior','linear']:
            raw=deepcopy(self.w['fixture'])
            if key=='posterior':raw['initially_possible_preferences']=['want']
            else:raw['game']['goals'][0]['binary']=False
            with self.assertRaises(ValueError):load_fixture(raw,3000)

    def test_export_separates_teacher_and_model_output(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);export_pair(self.w,out)
            prompts=(out/'development_prompts.jsonl').read_text()
            self.assertNotIn('teacher_counts',prompts)
            self.assertNotIn('planning_q',prompts)
            rows=[json.loads(s) for s in (out/'development.jsonl').read_text().splitlines()]
            for r in rows:
                a=json.loads(r['messages'][-1]['tool_calls'][0]['function']['arguments'])
                self.assertEqual(set(a),{'possible_preferences','favored'})


if __name__=='__main__':unittest.main()
