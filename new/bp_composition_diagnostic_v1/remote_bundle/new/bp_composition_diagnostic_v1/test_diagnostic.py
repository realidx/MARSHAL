"""CPU regression checks for privacy, contrast validity, and honest scoring."""
from copy import deepcopy
import json
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

import numpy as np

from prepare import HERE, common_context, request
from evaluate import load, summarize
from training.b_sft.social_bp_training import native_completion, reward
from training.b_sft.social_named_probe import present, action_call


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.tasks, cls.requests = load()

    def test_shared_context_and_no_hidden_answer_leak(self):
        for task in self.tasks.values():
            poisoned = deepcopy(task)
            poisoned['teacher'] = {'secret': 'DO_NOT_EXPOSE_LABEL'}
            self.assertEqual(request(task), request(poisoned))
            if task['condition'] != 'P_gold':
                poisoned['input']['supplied_belief']['joint_distribution'] = [
                    dict(probability='DO_NOT_EXPOSE_BELIEF', preferences=[])]
                self.assertEqual(request(task), request(poisoned))
            rendered = json.dumps(request(task))
            for field in ('policy_sha256', 'type_catalogues', 'acceptable_actions', 'per_world_payoffs'):
                self.assertNotIn(field, rendered)
        for case in {t['case_id'] for t in self.tasks.values()}:
            ts = [t for t in self.tasks.values() if t['case_id'] == case]
            self.assertEqual(len({common_context(t) for t in ts}), 1)
            ps = [t for t in ts if t['task'] == 'P']
            self.assertEqual(request(ps[0])['tools'], request(ps[1])['tools'])

    def test_evidence_contrasts_have_identical_physical_state(self):
        certs = json.loads((HERE / 'certificates.json').read_text())
        for family in {t['family'] for t in self.tasks.values()}:
            a = self.tasks[f'{family}:voluntary:P_infer']
            b = self.tasks[f'{family}:preset:P_infer']
            self.assertEqual(a['input']['current_state'], b['input']['current_state'])
            self.assertEqual(a['input']['legal_actions'], b['input']['legal_actions'])
            self.assertFalse({json.dumps(x, sort_keys=True) for x in a['teacher']['acceptable_actions']} &
                             {json.dumps(x, sort_keys=True) for x in b['teacher']['acceptable_actions']})
        for cert in certs:
            self.assertTrue(cert['teacher']['verified'])
            self.assertFalse(cert['teacher']['uniqueness_proven'])
            if cert['provenance'] == 'voluntary':
                self.assertGreater(cert['history_probability'], 0)
                self.assertGreater(cert['min_regret_of_prior_acceptable_under_posterior'], .1)
                for event in cert['trace']:
                    if event['actor'] == 0:
                        np.testing.assert_allclose(event['likelihood_by_world'], event['likelihood_by_world'][0])
            else:
                np.testing.assert_allclose(cert['posterior'], cert['prior'])

    def test_gold_completions_and_wrong_legal_actions(self):
        for t in self.tasks.values():
            self.assertEqual(reward(t, native_completion(t))['reward'], 1)
            if t['task'] == 'P':
                actions = t['input']['legal_actions']
                wrong = next(j for j, a in enumerate(actions) if a not in t['teacher']['acceptable_actions'])
                name, args = action_call(present(t)['legal_actions'][wrong])
                completion = dict(raw_message=dict(tool_calls=[dict(function=dict(
                    name=name, arguments=json.dumps(args)))]), finish_reason='tool_calls')
                self.assertEqual(reward(t, completion)['status'], 'ok')
                self.assertEqual(reward(t, completion)['reward'], 0)

    def test_invalid_and_truncated_stay_in_denominator(self):
        records = [dict(task_id=tid, replica=0, completion=native_completion(t)) for tid, t in self.tasks.items()]
        records[0]['completion'] = dict(raw_message=dict(tool_calls=[]), finish_reason='stop')
        records[1]['completion']['finish_reason'] = 'length'
        summary, _ = summarize(records, self.tasks, 1)
        self.assertTrue(summary['overall']['complete'])
        self.assertEqual(summary['overall']['correct'], 10)
        self.assertEqual(summary['overall']['legal'], 10)
        self.assertEqual(summary['overall']['accuracy'], 10 / 12)

    def test_missing_and_infrastructure_do_not_masquerade_as_complete(self):
        records = [dict(task_id=tid, replica=0, completion=native_completion(t)) for tid, t in self.tasks.items()]
        records[0]['completion'] = dict(status='infrastructure_failure')
        records.pop()
        summary, _ = summarize(records, self.tasks, 1)
        self.assertFalse(summary['overall']['complete'])
        self.assertIsNone(summary['overall']['accuracy'])
        self.assertEqual(summary['overall']['missing'], 1)
        self.assertEqual(summary['complete_triples'], 2)
        with self.assertRaises(ValueError):
            summarize(records + records[:1], self.tasks, 1)

    def test_oracle_smoke_is_not_model_evidence(self):
        records = [dict(task_id=tid, replica=0, completion=native_completion(t)) for tid, t in self.tasks.items()]
        summary, _ = summarize(records, self.tasks, 1)
        self.assertEqual(summary['overall']['accuracy'], 1)
        self.assertEqual(summary['joint_outcome_counts'], {'B1_gold1_infer1': 4})
        self.assertEqual(summary['gold_minus_infer_accuracy_on_complete_triples'], 0)

    def test_two_endpoint_runner_uses_historical_sampling_and_balances_replicas(self):
        import run
        lookup = {json.dumps(r['request']['messages'], sort_keys=True): tid for tid, r in self.requests.items()}
        seen = []
        def fake_urlopen(req, timeout):
            body = json.loads(req.data)
            self.assertEqual((body['temperature'], body['top_p'], body['top_k'], body['repetition_penalty']), (1., 1., -1, 1.))
            self.assertNotIn('teacher', body)
            tid = lookup[json.dumps(body['messages'], sort_keys=True)]
            done = native_completion(self.tasks[tid]); seen.append(req.full_url)
            return io.BytesIO(json.dumps(dict(choices=[dict(message=done['raw_message'], finish_reason='stop')])).encode())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'mock_run'
            argv = ['run.py', '--base-url', 'http://mock-a/v1', 'http://mock-b/v1',
                    '--model', 'mock', '--output', str(output), '--repeats', '2']
            with patch('sys.argv', argv), patch.object(run, 'urlopen', fake_urlopen), patch('builtins.print'):
                run.main()
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['overall']['correct'], 24)
            self.assertTrue((output / 'COMPLETE.json').exists())
            self.assertEqual(seen.count('http://mock-a/v1/chat/completions'), 12)
            self.assertEqual(seen.count('http://mock-b/v1/chat/completions'), 12)


if __name__ == '__main__':
    unittest.main()
