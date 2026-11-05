"""A changed source/request cannot retain its registered protocol identity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .common import file_hash
from . import pipeline_versions as versions


class PipelineVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.registry=self.root/'versions';self.folder=self.registry/'v1';self.folder.mkdir(parents=True)
        (self.root/'runtime.py').write_text('original source')
        (self.folder/'prompt.json').write_text('{"messages": []}')
        self.record=dict(version='v1',prompt_version='p1',contract_sources={'runtime.py':file_hash(self.root/'runtime.py')},review_files={'prompt.json':file_hash(self.folder/'prompt.json')})
        (self.folder/'SNAPSHOT.json').write_text(json.dumps(self.record))
        (self.registry/'index.json').write_text(json.dumps(dict(versions={'v1':'v1/SNAPSHOT.json'})))
        self.stack=[patch.object(versions,'ROOT',self.root),patch.object(versions,'REGISTRY',self.registry)]
        for p in self.stack:p.start();self.addCleanup(p.stop)
    def test_registered_identity_and_reject_unregistered(self):
        self.assertEqual(versions.registered_snapshot('v1','p1')['sha256'],file_hash(self.folder/'SNAPSHOT.json'))
        with self.assertRaisesRegex(ValueError,'Unregistered'):versions.registered_snapshot('v2','p1')
        with self.assertRaisesRegex(ValueError,'contract differs'):versions.registered_snapshot('v1','p2')
    def test_changed_runtime_requires_new_version(self):
        (self.root/'runtime.py').write_text('different source')
        with self.assertRaisesRegex(ValueError,'source changed'):versions.registered_snapshot('v1','p1')
    def test_changed_prompt_requires_new_version(self):
        (self.folder/'prompt.json').write_text('{"messages": ["different prompt"]}')
        with self.assertRaisesRegex(ValueError,'review artifact changed'):versions.registered_snapshot('v1','p1')
    def test_actual_overrides_are_recorded_and_never_overwritten(self):
        registered=versions.registered_snapshot('v1','p1')
        args=(self.root,registered,{'concurrency':7},{'sequence_length':123},{'version':'v1'},{'runtime.py':'hash'},{'model':'hash'})
        versions.write_run_snapshot(*args)
        saved=json.loads((self.root/'pipeline_snapshot.json').read_text())
        self.assertEqual(saved['actual_options']['concurrency'],7)
        self.assertEqual(saved['resolved_config']['sequence_length'],123)
        self.assertEqual(saved['registered_version'],registered)
        with self.assertRaises(FileExistsError):versions.write_run_snapshot(*args)


if __name__=='__main__':unittest.main()
