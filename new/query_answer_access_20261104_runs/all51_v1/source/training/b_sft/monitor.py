"""Read-only machine GPU/process telemetry, separate from allocator measurements."""

import json
import subprocess
import threading
import time
from pathlib import Path


class ResourceMonitor:
    def __init__(self, path, interval=5):
        self.path = Path(path)
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    @staticmethod
    def query(fields, query_type):
        try:
            result = subprocess.run(['nvidia-smi', f'--query-{query_type}={fields}',
                                     '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=4)
            return dict(returncode=result.returncode, csv=result.stdout.strip(), error=result.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as error:
            return dict(error=str(error))

    def run(self):
        with self.path.open('a') as stream:
            while not self.stop_event.is_set():
                row = dict(time=time.time(), gpu=self.query(
                    'index,uuid,memory.total,memory.used,memory.free,utilization.gpu', 'gpu'),
                    processes=self.query('gpu_uuid,pid,used_gpu_memory', 'compute-apps'))
                meminfo = Path('/proc/meminfo')
                if meminfo.exists():
                    row['host_memory'] = [line for line in meminfo.read_text().splitlines()
                                          if line.startswith(('MemAvailable:', 'MemTotal:'))]
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                self.stop_event.wait(self.interval)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=10)
