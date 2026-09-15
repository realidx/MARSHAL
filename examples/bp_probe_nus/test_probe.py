"""CPU-only integration checks for the portable sampler, no local labels needed."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from run_probe import ENTRY, verify_bundle, prompt_token_length


class PortableProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / 'bundle'
        shutil.copytree(ENTRY / 'bundle', self.bundle)
        spec = importlib.util.spec_from_file_location('portable_test_sampler', self.bundle / 'remote_bp_probe.py')
        self.sampler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sampler)

    def test_bundle_runs_without_repository_or_teacher_dependencies(self):
        manifest, rows = verify_bundle(self.bundle)
        count = 0
        class Response:
            def __init__(self, message): self.message = message
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'choices': [{'message': self.message, 'finish_reason': 'stop'}]}).encode()
        def reply(req, timeout):
            nonlocal count
            count += 1
            payload = json.loads(req.data)
            names = [t['function']['name'] for t in payload['tools']]
            # A text JSON answer must remain a failed tool submission.
            if count == 1: return Response({'content': '{"action":"PASS"}'})
            # INVESTIGATE need not be the first registered tool.
            name = 'INVESTIGATE' if 'INVESTIGATE' in names else names[0]
            return Response({'content': 'Mock explanation.', 'tool_calls': [
                {'function': {'name': name, 'arguments': '{}'}}]})
        with patch.object(self.sampler, 'urlopen', side_effect=reply), redirect_stdout(io.StringIO()):
            result = self.sampler.run(self.bundle / 'requests.jsonl', Path(self.tmp.name) / 'probe',
                                     ['http://mock/v1'], 'social-base', group_size=manifest['group_size'])
        self.assertEqual(count, 64)
        self.assertEqual(result['native_submissions'], 63)
        self.assertEqual(result['text_submissions'], 0)
        self.assertEqual(result['completed_without_protocol_submission'], 1)
        samples = [json.loads(s) for s in (Path(self.tmp.name) / 'probe/samples.jsonl').read_text().splitlines()]
        self.assertEqual(samples[0]['raw_message']['content'], '{"action":"PASS"}')
        self.assertEqual(len(samples), len(rows)*2)

    def test_preflight_transport_failure_is_not_retried(self):
        with patch.object(self.sampler, 'urlopen', side_effect=TimeoutError) as request, redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                self.sampler.run(self.bundle / 'requests.jsonl', Path(self.tmp.name) / 'preflight',
                                 ['http://mock/v1'], 'social-base', preflight=True, group_size=2)
        self.assertEqual(request.call_count, 2)
        result = json.loads((Path(self.tmp.name) / 'preflight/summary.json').read_text())
        self.assertEqual(result['infrastructure_failures'], 2)

    def test_modified_question_bundle_is_rejected(self):
        with (self.bundle / 'requests.jsonl').open('a') as f: f.write('\n')
        with self.assertRaises(ValueError): verify_bundle(self.bundle)

    def test_context_check_counts_input_ids_not_encoding_fields(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                self.kwargs = kwargs
                return {'input_ids': list(range(4495)), 'attention_mask': [1]*4495}
        tokenizer = Tokenizer()
        request = {'messages': [{'role': 'user', 'content': 'Question'}], 'tools': [{'type': 'function'}]}
        self.assertEqual(prompt_token_length(tokenizer, request), 4495)
        self.assertTrue(tokenizer.kwargs['return_dict'])
        self.assertFalse(tokenizer.kwargs['truncation'])
        self.assertEqual(tokenizer.kwargs['tools'], request['tools'])

    def test_context_check_rejects_batched_or_missing_token_ids(self):
        class Tokenizer:
            def apply_chat_template(self, *args, **kwargs): return {'input_ids': [[1, 2, 3]]}
        with self.assertRaises(ValueError):
            prompt_token_length(Tokenizer(), {'messages': [], 'tools': []})


if __name__ == '__main__': unittest.main()
