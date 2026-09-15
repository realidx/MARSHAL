import json
from copy import deepcopy
from pathlib import Path
import unittest

from training.b_sft.evidence_switch import verify_witness, mine_fixture, constructed, disjoint


class EvidenceSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=json.loads((Path(__file__).parent/'fixtures/evidence_switch_regression.json').read_text())

    def test_native_replay_and_disjoint_optima(self):
        self.assertTrue(verify_witness(self.w))
        self.assertEqual(self.w['left']['support'],['want'])
        self.assertEqual(self.w['right']['support'],['want','neutral','avoid'])
        self.assertEqual(self.w['left']['optimal_actions'],[1])
        self.assertEqual(self.w['right']['optimal_actions'],[0])

    def test_tampered_support_values_and_state_are_rejected(self):
        for key,value in [('support',['avoid']),('q',[0,1]),('physical_key','fake')]:
            w=deepcopy(self.w);w['left'][key]=value
            with self.assertRaises(ValueError):verify_witness(w)

    def test_observation_must_be_replayed_not_asserted(self):
        w=deepcopy(self.w)
        w['left']['history']=w['right']['history']
        with self.assertRaises(ValueError):verify_witness(w)

    def test_generator_reproduces_witness(self):
        r=mine_fixture(constructed(94002),3000,512,6)
        self.assertEqual(r['status'],'found')
        self.assertTrue(verify_witness(r['witness']))

    def test_budget_is_not_negative_proof(self):
        r=mine_fixture(constructed(94002),3000,1,6)
        self.assertEqual(r['status'],'decision_budget')
        self.assertIsNone(r['witness'])

    def test_shared_optimum_and_action_mismatch_do_not_pass(self):
        a=dict(actions=['accept','reject'],optimal_actions=[0,1])
        b=dict(actions=['accept','reject'],optimal_actions=[1])
        self.assertFalse(disjoint(a,b))
        b=dict(actions=['reject','accept'],optimal_actions=[0])
        self.assertFalse(disjoint(a,b))


if __name__=='__main__':unittest.main()
