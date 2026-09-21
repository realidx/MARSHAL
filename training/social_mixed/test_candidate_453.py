import json
import unittest
from collections import Counter
from training.social_mixed.reasoning_bank import PATH, sha


class CandidateAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary=json.loads((PATH/'candidate_453_audit.json').read_text())
        cls.rows=list(map(json.loads,(PATH/'candidate_453_cases.jsonl').read_text().splitlines()))
        cls.audit={r['canonical_id']:r for r in map(json.loads,(PATH/'qualitative_case_audit.jsonl').read_text().splitlines())}

    def test_candidate_partition_and_hashes(self):
        self.assertEqual(sha((PATH/'candidate_453_cases.jsonl').read_bytes()),self.summary['candidate_cases_sha256'])
        self.assertEqual(sha((PATH/'qualitative_case_audit.jsonl').read_bytes()),self.summary['source_audit_sha256'])
        ids={r['canonical_id'] for r in self.rows}
        self.assertEqual(len(self.rows),len(ids))
        self.assertEqual(len(ids),453)
        self.assertEqual(Counter(r['group'] for r in self.rows),{'invariant':394,'robust_positive_partial':59})
        excluded=set(self.summary['excluded_canonical_ids'])
        self.assertFalse(ids & excluded)
        self.assertEqual(ids | excluded,set(self.audit))
        self.assertEqual(Counter(r['split'] for r in self.rows),{'train':343,'validation':110})

    def test_every_action_has_one_supported_state(self):
        masks=0
        for r in self.rows:
            source=self.audit[r['canonical_id']]['text_envelope']
            positive={a['action_index'] for a in r['actions'] if a['semantic_supervision']=='positive'}
            negative={a['action_index'] for a in r['actions'] if a['semantic_supervision']=='negative'}
            self.assertEqual(positive,set(source['universally_acceptable_indices']))
            self.assertEqual(negative,set(source['always_rejected_indices']))
            self.assertTrue(set(source['original_acceptable_indices'])<=positive)
            self.assertEqual({a['action_index'] for a in r['actions']},set(range(len(r['actions']))))
            outcomes=[set(source['original_acceptable_indices'])]+[set(w['acceptable_indices']) for w in source['witnesses']]
            for a in r['actions']:
                if a['semantic_supervision']=='masked':
                    masks+=1
                    self.assertEqual({a['action_index'] in o for o in outcomes},{True,False})
        self.assertEqual(masks,386)

    def test_split_and_isolated_b_pairs(self):
        families={}
        for r in self.rows:
            self.assertEqual(families.setdefault(r['family'],r['split']),r['split'])
        rows={r['canonical_id']:r for r in self.rows}
        for rel in json.loads((PATH/'candidate_453_relations.json').read_text()):
            self.assertIn(rel['left'],rows);self.assertIn(rel['right'],rows)
            if rel['only_queried_semantic_belief_changes']:
                q=rows[rel['left']]['b_query'];key=(q['player'],q['goal'])
                left,right=[self.audit[rel[k]]['qualitative_beliefs'] for k in ('left','right')]
                self.assertEqual([x for x in left if (x['player'],x['goal'])!=key],
                                 [x for x in right if (x['player'],x['goal'])!=key])
                self.assertNotEqual(left,right)

if __name__=='__main__':unittest.main()
