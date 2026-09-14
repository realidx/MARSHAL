"""Portable baseline checks with mocked HTTP; no GPU or teacher dependencies."""
from collections import Counter
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from run_probe import ENTRY,verify_bundle


class BaselineTests(unittest.TestCase):
    def test_exact_counts_and_test_exclusion(self):
        manifest,rows=verify_bundle(ENTRY/'bundle')
        self.assertEqual(len(rows),320)
        self.assertEqual(Counter(r['split'] for r in rows),{'train':256,'validation':64})
        self.assertEqual(sum(p['formal_requests'] for p in manifest['stages']),2304)
        self.assertTrue(all('teacher' not in r for r in rows))

    def test_sampler_preserves_all_first_attempts_and_separate_preflight(self):
        spec=importlib.util.spec_from_file_location('pilot_sampler',ENTRY/'bundle/remote_bp_probe.py')
        sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(dict(choices=[dict(message=dict(content='Still reasoning.'),finish_reason='length')])).encode()
        with tempfile.TemporaryDirectory() as tmp,patch.object(sampler,'urlopen',return_value=Response()) as http,redirect_stdout(io.StringIO()):
            total=0
            for split,n,expected in (('train',8,2048),('validation',4,256)):
                result=sampler.run(ENTRY/f'bundle/{split}_requests.jsonl',Path(tmp)/split,['http://mock/v1']*4,'social-base',group_size=n)
                self.assertEqual(result['completed'],expected)
                self.assertEqual(result['truncated_submissions'],expected)
                samples=[json.loads(s) for s in (Path(tmp)/split/'samples.jsonl').read_text().splitlines()]
                self.assertEqual(set(Counter(s['task_id'] for s in samples).values()),{n});total+=expected
            self.assertEqual(http.call_count,total)
            result=sampler.run(ENTRY/'bundle/train_requests.jsonl',Path(tmp)/'preflight',['http://mock/v1'],'social-base',preflight=True)
            self.assertEqual(result['completed'],2)
            self.assertEqual(http.call_count,2306)


if __name__=='__main__':unittest.main()
