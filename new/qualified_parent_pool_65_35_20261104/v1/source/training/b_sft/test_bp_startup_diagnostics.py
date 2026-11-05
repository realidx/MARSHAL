import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

from training.b_sft.bp_cpu_preflight import check_cpu_contract
from training.b_sft.bp_runtime_monitor import snapshot
from training.b_sft.bp_startup import startup_phase


class DiagnosticsTests(unittest.TestCase):
    def test_nested_failure_cancels_watchdog_and_preserves_phase_evidence(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, BP_STARTUP_DIAGNOSTICS='1'):
            cfg=SimpleNamespace(social_bp_curriculum=True,num_gpus_per_node=2,output_dir=folder)
            with patch('training.b_sft.bp_startup.faulthandler.dump_traceback_later') as begin, \
                 patch('training.b_sft.bp_startup.faulthandler.cancel_dump_traceback_later') as end:
                with self.assertRaisesRegex(ValueError,'original error'):
                    with startup_phase(cfg,'outer'):
                        with startup_phase(cfg,'inner'):
                            raise ValueError('original error')
                begin.assert_called_once();end.assert_called_once()
            rows=[json.loads(line) for p in Path(folder).glob('startup-*.jsonl') for line in p.read_text().splitlines()]
            self.assertEqual([r['phase'] for r in rows],['inner','outer'])
            self.assertTrue(all(r['status']=='failed' and 'cpu_seconds' in r for r in rows))
            events=[json.loads(line) for p in Path(folder).glob('startup_events-*.jsonl') for line in p.read_text().splitlines()]
            self.assertEqual([r['event'] for r in events],['begin','begin','end','end'])

    def test_monitor_excludes_unrelated_processes_and_sensitive_arguments(self):
        parent=psutil.Process(os.getppid())
        with patch.object(parent,'children',return_value=[]):
            row=snapshot(parent)
        allowed={parent.pid}
        self.assertTrue(all(p['pid'] in allowed for p in row['processes']))
        self.assertTrue(all('cmdline' not in p and 'environ' not in p for p in row['processes']))
        with patch.object(parent,'children',side_effect=PermissionError('restricted')):
            self.assertEqual(snapshot(parent)['unavailable']['process_tree'],'PermissionError')

    def test_real_cpu_batch_and_loss_contract(self):
        result=check_cpu_contract()
        self.assertEqual(result['samples'],128)
        self.assertTrue(result['finite_nonzero_gradient'])


if __name__=='__main__':unittest.main()
