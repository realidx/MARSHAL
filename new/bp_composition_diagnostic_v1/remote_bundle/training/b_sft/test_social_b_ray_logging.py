"""Exercise the installed Ray log monitor without starting a Ray cluster."""
import os
from pathlib import Path
import tempfile
import unittest

from roll.distributed.scheduler.log_monitor import LogMonitor


class RayLoggingTests(unittest.TestCase):
    def test_constructor_and_actual_file_publication(self):
        records = []

        class Publisher:
            def publish_logs(self, data):
                records.append(data)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"worker-{'a'*56}-{'b'*8}-{os.getpid()}.out"
            path.write_text('B GRPO log compatibility check\n')
            monitor = LogMonitor(node_ip_address='127.0.0.1', logs_dir=directory,
                                 gcs_publisher=Publisher(), is_proc_alive_fn=lambda pid: True)
            try:
                monitor.update_log_filenames()
                monitor.open_closed_files()
                self.assertTrue(monitor.check_log_files_and_publish_updates())
                self.assertEqual(records[0]['lines'], ['B GRPO log compatibility check'])
                self.assertEqual(records[0]['pid'], os.getpid())
            finally:
                for info in monitor.open_file_infos:
                    info.file_handle.close()


if __name__ == '__main__':
    unittest.main()
