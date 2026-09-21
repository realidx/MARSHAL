import unittest
import numpy as np
from training.social_mixed.audit_qualitative_cases import audit_case, matches


def fixture(pay, probability=.9, response=False):
    worlds=[[[1],[1]],[[1],[0]]]
    weights=[probability,1-probability]
    actions=[{'response':'ACCEPT'},{'response':'REJECT'}] if response else [{'action':'PASS'},{'action':'OFFER'}]
    from training.b_sft.preference_contract import belief
    gold=belief({'want':probability,'neutral':1-probability,'avoid':0.})
    case=dict(canonical_id='synthetic',labels=dict(worlds=worlds,posterior=weights,
        per_world_payoffs=pay,action_values=np.einsum('awp,w->ap',np.array(pay),weights).tolist(),
        query_candidates=[dict(player=1,goal=0,gold=gold)]))
    task=dict(input=dict(player=0,own_preferences={'goal_0':'want'},legal_actions=actions))
    return case,task


class QualitativeAuditTests(unittest.TestCase):
    def test_invariant_dominance(self):
        case,task=fixture([[[2,0],[2,0]],[[1,0],[1,0]]])
        for mode in ('text_envelope','b_contract'):
            result=audit_case(case,task,mode)
            self.assertEqual(result['status'],'reward_labels_invariant_in_envelope')
            self.assertEqual(result['universally_acceptable_indices'],[0])

    def test_same_favored_disjoint_actions(self):
        case,task=fixture([[[1.5,0],[0,0]],[[1,0],[1,0]]])
        result=audit_case(case,task,'b_contract')
        self.assertTrue(result['disjoint_action_witness'])
        self.assertFalse(result['original_positive_labels_all_robust'])
        for witness in result['witnesses']:
            self.assertTrue(matches(np.array(witness['weights']),case,'b_contract'))

    def test_response_social_tie_is_checked(self):
        case,task=fixture([[[1,1.5],[1,0]],[[1,1],[1,1]]],response=True)
        result=audit_case(case,task,'b_contract')
        self.assertTrue(result['disjoint_action_witness'])
        self.assertEqual(result['worst_own_regret_by_action'],[0.,0.])
        self.assertGreater(result['worst_response_tie_social_gap'][0],.1)

    def test_undetermined_regions(self):
        case,task=fixture([[[10,0],[0,0]],[[0,0],[10,0]]],.5)
        result=audit_case(case,task,'b_contract')
        self.assertEqual(result['convex_regions'],2)
        self.assertTrue(result['witnesses'])
        for witness in result['witnesses']:
            self.assertTrue(matches(np.array(witness['weights']),case,'b_contract'))

class ExportedWitnessTests(unittest.TestCase):
    def test_every_exported_witness_and_complete_coverage(self):
        import json
        from training.social_mixed.reasoning_bank import load, PATH, sha
        from training.b_sft.social_bp_curriculum import acceptable
        cases={c['canonical_id']:c for split in ('train','validation') for c in load(split,'cases.jsonl')}
        tasks={t['canonical_id']:t for split in ('train','validation') for t in load(split) if t['paired_view']=='Pplus'}
        payload=(PATH/'qualitative_case_audit.jsonl').read_bytes()
        rows=list(map(json.loads,payload.splitlines()))
        summary=json.loads((PATH/'qualitative_case_audit_summary.json').read_text())
        self.assertEqual(sha(payload),summary['audit_sha256'])
        self.assertEqual({r['canonical_id'] for r in rows},set(cases))
        self.assertEqual(len(rows),len(cases))
        for row in rows:
            case=cases[row['canonical_id']];task=tasks[row['canonical_id']]
            for mode in ('text_envelope','b_contract'):
                result=row[mode]
                for witness in result['witnesses']:
                    w=np.array(witness['weights'])
                    self.assertGreaterEqual(w.min(),-1e-9)
                    self.assertAlmostEqual(w.sum(),1.)
                    self.assertTrue(matches(w,case,mode))
                    vals=np.einsum('awp,w->ap',np.array(case['labels']['per_world_payoffs']),w)
                    self.assertTrue(np.allclose(vals,witness['values'],atol=1e-10,rtol=0))
                    actual=acceptable(vals,task['input']['player'],actions=task['input']['legal_actions'])
                    self.assertEqual(actual,witness['acceptable_indices'])
                    self.assertNotEqual(actual,result['original_acceptable_indices'])
                    self.assertTrue(set(result['universally_acceptable_indices'])<=set(actual))
                    self.assertFalse(set(result['always_rejected_indices']) & set(actual))


if __name__=='__main__':unittest.main()
