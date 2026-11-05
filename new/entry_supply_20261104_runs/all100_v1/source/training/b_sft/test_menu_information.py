import unittest
from copy import deepcopy
import numpy as np

from training.b_sft.debug.audit_menu_information import audit_root, best, immediate_fixture, learner_values, direct_value
from training.b_sft.social_cases_expand import information_fixture
from training.b_sft.social_b_oracle import BeliefOracle


class MenuInformationTests(unittest.TestCase):
    def test_menu_can_win_entirely_through_immediate_matching(self):
        raw,prefix=immediate_fixture();raw['game']['menu_enabled']=True
        result=audit_root(raw,prefix)
        ordinary=best([r for r in result['actions'] if r['kind']!='MENU'],'full')[0]
        menu=best([r for r in result['actions'] if r['kind']=='MENU'],'full')[0]
        self.assertEqual(ordinary['full'][0],.5)
        self.assertEqual(menu['full'][0],1)
        self.assertEqual(menu['full'],menu['immediate'])
        self.assertFalse(menu['later_learner'])
        self.assertEqual(menu['belief_use_gain'],[0,0])
        self.assertTrue(result['strict_menu_advantage_without_later_learner'])
        self.assertFalse(result['menu_information_candidates'])

    def test_offer_information_is_used_in_a_later_decision(self):
        raw,prefix=information_fixture('two_types')
        result=audit_root(raw,prefix[:3])
        winner=best(result['actions'],'full')[0]
        self.assertEqual(winner['full'][0],1.5)
        self.assertEqual(winner['frozen'][0],1)
        self.assertEqual(best(result['actions'],'frozen')[0]['frozen'][0],1)
        self.assertTrue(winner['later_learner'])
        witness=result['information_witnesses'][0]
        self.assertTrue(witness['direct_native_values_verified'])
        self.assertEqual(sum(b['probability'] for b in witness['branches']),1)
        self.assertTrue(any(b['next_full_actions']!=b['next_frozen_actions'] for b in witness['branches']))

    def test_information_gain_does_not_prove_menu_adds_a_unique_capability(self):
        raw,prefix=information_fixture('two_types');raw['game']['menu_enabled']=True
        result=audit_root(raw,prefix[:3])
        self.assertTrue(result['menu_information_candidates'])
        self.assertEqual(best(result['actions'],'full')[0]['full'],
                         best([r for r in result['actions'] if r['kind']!='MENU'],'full')[0]['full'])

    def test_ablation_keeps_all_other_player_policies_fixed(self):
        raw,prefix=information_fixture('two_types')
        oracle=BeliefOracle(raw,prefix[:3]);tree=oracle.solve();original=deepcopy(tree.policy)
        full,policy=learner_values(tree,raw['ego'])
        frozen,other=learner_values(tree,raw['ego'],frozen=True)
        for i,e in enumerate(tree.entries):
            if e.actor is not None:
                np.testing.assert_array_equal(tree.policy[i],original[i])
                if e.actor!=raw['ego']:
                    np.testing.assert_array_equal(policy[i],original[i])
                    np.testing.assert_array_equal(other[i],original[i])
        for ai,child in enumerate(tree.entries[0].children):
            actual=direct_value(tree,policy,raw['ego'],raw['own_preferences'],ai)
            np.testing.assert_allclose(actual,np.average(full[child],axis=0,weights=tree.world_weights))


if __name__=='__main__':unittest.main()
