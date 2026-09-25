import json
import unittest
from copy import deepcopy
from pathlib import Path
from new.diagnostic_v7p.experiment import load, p_request, p_task
from training.social_mixed.history_free_requests import request
from training.b_sft.social_named_probe import present

class InterfaceTests(unittest.TestCase):
    def test_frozen_cases_and_training_renderer(self):
        _,cases=load()
        old=json.loads(Path('new/diagnostic_v7/cases.json').read_text())
        self.assertEqual(cases,old)
        for c in cases:
            for belief in [c['gold_judgment'],dict(possible_preferences=['want','neutral','avoid'],favored='undetermined'),dict(possible_preferences=['avoid'],favored='avoid')]:
                task=p_task(c,belief);r=p_request(c,belief)
                self.assertEqual(r,request(task))
                self.assertEqual(r['tools'],c['requests']['O']['tools'])
                text=r['messages'][1]['content']
                self.assertIn('favored states which preference is better supported',text)
                self.assertNotIn('EVENTS SINCE GAME START',text)
                self.assertNotIn('INITIAL STATE AT GAME START',text)
                from training.b_sft.review_prompt import state_table
                v=present(c['task'],0)
                self.assertIn('\n'.join(state_table(v,v['binding_commitments'],'CURRENT BINDING STATE')),text)
                q=task['input']['queries'][0]
                beliefs=task['input']['supplied_belief']['semantic_beliefs']
                target=[b for b in beliefs if (b['player'],b['goal'])==(q['player'],q['goal'])]
                self.assertEqual(len(target),1)
                self.assertEqual(target[0]['favored'],belief['favored'])

if __name__=='__main__':unittest.main()
