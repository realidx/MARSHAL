import json
from pathlib import Path
import unittest
from training.social_mixed.reasoning_bank import load, panel
from training.social_mixed.reasoning_preflight import audit
from training.social_mixed.reasoning_scoring import decision_metrics
from training.b_sft.social_bp_training import native_completion, reward


class ReasoningBankTests(unittest.TestCase):
    def test_full_label_algebra_and_split_contract(self):
        result=audit()
        self.assertTrue(result['passed'])
        self.assertEqual(result['counts']['train']['cases'],373)
        self.assertEqual(result['counts']['validation']['cases'],124)
        self.assertFalse(result['context_checked'])
        self.assertTrue(any(r['relation']=='must_change' for r in load('validation','relations.jsonl')))

    def test_p_cannot_reconstruct_history_and_uses_supplied_belief(self):
        from copy import deepcopy
        from training.social_mixed.paired_requests import request
        for t in load('train') + load('validation'):
            if t['paired_view'] != 'Pplus': continue
            original = request(t)
            changed = deepcopy(t)
            # Evidence and the canonical O input must not affect a P request.
            changed['input']['voluntary_history'] = [{'sentinel': 'HISTORY_LEAK'}]
            changed['input']['imposed_setup'] = [{'sentinel': 'SETUP_LEAK'}]
            changed['input']['background_prior'] = {'sentinel': 'PRIOR_LEAK'}
            changed['canonical_action_task'] = {'sentinel': 'CANONICAL_O_LEAK'}
            self.assertEqual(request(changed), original)
            changed = deepcopy(t)
            changed['input']['supplied_belief']['semantic_beliefs'][0]['favored'] = 'BELIEF_SENTINEL'
            self.assertIn('BELIEF_SENTINEL', request(changed)['messages'][1]['content'])
            self.assertEqual(original['tools'], request(changed)['tools'])

    def test_native_gold_scores_and_regret_mapping(self):
        rows=load('train')
        # Across all canonical decisions, the action decoder must agree with
        # teacher values; exact regret may be nonzero within original tolerance.
        for t in rows:
            completion=native_completion(t)
            self.assertTrue(reward(t,completion)['correct'],t['id'])
            m=decision_metrics(t,completion)
            if t['task']=='P':
                self.assertIsNotNone(m['action_index'],t['id'])
                self.assertGreaterEqual(m['own_regret'],-1e-8)

    def test_panel_keeps_complete_parent_views(self):
        chosen=panel(); all_rows=load('validation')
        parents={t['package_id'] for t in chosen}
        self.assertEqual({t['id'] for t in chosen},{t['id'] for t in all_rows if t['package_id'] in parents})
        self.assertEqual({t['paired_view'] for t in chosen},{'O','B','Pplus'})


if __name__=='__main__':unittest.main()
