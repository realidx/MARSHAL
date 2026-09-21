from copy import deepcopy
from unittest.mock import patch
import unittest
from training.social_mixed.reasoning_bank import load
from training.social_mixed.audit_p_world_scope import audit_case

class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=load('train','cases.jsonl')
        cls.tasks={t['canonical_id']:t for t in load('train') if t['paired_view']=='Pplus'}

    def test_real_world_support_covered(self):
        for c in self.cases:
            r=audit_case(c,self.tasks[c['canonical_id']])
            self.assertEqual(r['missing_visible_worlds'],0)
            self.assertLess(r['source_posterior_outside_visible_mass'],1e-9)

    def test_detect_removed_visible_world(self):
        c=next(c for c in self.cases if sum(v>0 for v in c['labels']['posterior'])>1)
        changed=deepcopy(c);lab=changed['labels']
        index=next(i for i,v in enumerate(lab['posterior']) if v>0)
        del lab['worlds'][index];del lab['posterior'][index]
        r=audit_case(changed,self.tasks[c['canonical_id']])
        self.assertEqual(r['missing_visible_worlds'],1)
        self.assertEqual(r['conclusion'],'visible_support_not_covered')

if __name__=='__main__':unittest.main()
