"""Check distinctions that could otherwise falsely certify social reasoning."""
import unittest
import json
from pathlib import Path
from training.b_sft.structure_audit import action_audit, shortlist, audit


class StructureAuditTests(unittest.TestCase):
    def test_sensitive_but_common_optimum(self):
        a=action_audit([[2,2,0],[2,0,1]])
        self.assertTrue(a['value_sensitive'])
        self.assertEqual(a['common_optimal_actions'],[0])
        self.assertEqual(a['best_fixed_action_worst_regret'],0)
        self.assertIsNone(a['disjoint_optimal_pair'])

    def test_no_common_action_without_disjoint_pair(self):
        a=action_audit([[1,1,0],[0,1,1],[1,0,1]])
        self.assertEqual(a['common_optimal_actions'],[])
        self.assertIsNone(a['disjoint_optimal_pair'])
        self.assertEqual(a['best_fixed_action_worst_regret'],1)

    def test_switch_and_ties(self):
        a=action_audit([[2,0],[0,3]])
        self.assertEqual(a['disjoint_optimal_pair'],[0,1])
        self.assertEqual(a['best_fixed_action_worst_regret'],2)
        self.assertEqual(action_audit([[1,1+1e-12]])['common_optimal_actions'],[0,1])

    def test_shortlist_excludes_holdout_and_does_not_fill_quota(self):
        def row(key,split,coverage):
            return dict(structure_id=key,id=key,split=split,status='ok',players=3,coverage=coverage)
        rows=[row('a','train',['maintain']), row('b','development',['maintain']),
              row('c','test',['unique']), row('d','train',['other']),row('d','validation',['other'])]
        chosen=shortlist(rows,8)
        self.assertEqual([r['structure_id'] for r in chosen],['a'])

    def test_native_fixture_and_budget_failure(self):
        raw=json.loads((Path(__file__).parent/'fixtures/decision_corpus_regression.json').read_text())
        c=dict(fixture=raw, source_id='test', split='development')
        result=audit(c,20000)
        self.assertEqual(result['status'],'ok')
        self.assertTrue(result['fixed_action_audit']['common_optimal_actions'])
        self.assertFalse(result['observable_switch_witness'])
        self.assertFalse(result['positive_value_of_information_proven'])
        failed=audit(c,1)
        self.assertEqual(failed['status'],'unavailable')
        self.assertEqual(failed['coverage'],[])

    def test_unknown_cannot_supply_coverage(self):
        r=dict(structure_id='a',id='a',split='train',status='unavailable',players=3,coverage=['fake'])
        self.assertEqual(shortlist([r],8),[])


if __name__=='__main__':unittest.main()
