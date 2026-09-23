import json,unittest
from pathlib import Path
import numpy as np
from training.social_mixed.build_progressive_bank import certify
from training.b_sft.social_bp_curriculum import acceptable

class ProgressiveTests(unittest.TestCase):
    def test_sufficient_certification_with_mixtures(self):
        rng=np.random.default_rng(42)
        for response in (False,True):
            actions=[{'response':'ACCEPT'},{'response':'REJECT'}] if response else [{'action':'PASS'},{'action':'OFFER'}]
            for _ in range(100):
                pay=rng.integers(-3,4,(2,3,2))/2
                labels=certify(pay,actions)
                for w in [*np.eye(3),*rng.dirichlet(np.ones(3),20)]:
                    good=acceptable(np.einsum('awp,w->ap',pay,w),0,actions=actions)
                    for j,l in enumerate(labels):
                        if l=='positive':self.assertIn(j,good)
                        if l=='negative':self.assertNotIn(j,good)

    def test_candidate_invariants(self):
        from training.social_mixed.build_progressive_bank import OUT
        rows=[json.loads(l) for l in (OUT/'tasks.jsonl').read_text().splitlines()]
        families={};parents={}
        for t in rows:
            families.setdefault(t['family'],set()).add(t['split'])
            parents.setdefault(t['canonical_id'],set()).add(t['paired_view'])
            self.assertNotIn('previous_belief',t['input'])
            self.assertFalse(t['training_ready'])
            if t['paired_view']=='B' and t['input']['private_results']:
                fact=t['input']['private_results'][0]
                self.assertEqual(t['teacher']['gold']['possible_preferences'],[fact['preference']])
        self.assertTrue(all(len(s)==1 for s in families.values()))
        self.assertTrue(all(s=={'B','O','Pplus'} for s in parents.values()))
        self.assertTrue(any(t['learning_stage']=='single_choice_identifying' for t in rows))
        self.assertTrue(any(t['learning_stage']=='single_choice_uncertain' for t in rows))
        for split in ('train','validation'):
            common=[json.loads(l) for l in (OUT/f'common_{split}.jsonl').read_text().splitlines()]
            self.assertTrue(all(t['p_train_eligible'] and t['split']==split for t in common))
            self.assertEqual(len(common)%3,0)

if __name__=='__main__':unittest.main()
