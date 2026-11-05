"""Read-only host/process diagnostics for one training driver's descendants.

Runs outside Ray so blocked worker Python threads cannot block sampling. Never
signals workers, reads process environments, or samples unrelated job processes.
"""
import argparse
import json
import os
from pathlib import Path
import time

import psutil


def process_record(process):
    with process.oneshot():
        row = dict(pid=process.pid, ppid=process.ppid(), name=process.name(),
                   created=process.create_time(), status=process.status(),
                   threads=process.num_threads(), cpu=process.cpu_times()._asdict(),
                   memory=process.memory_info()._asdict(), switches=process.num_ctx_switches()._asdict())
        try: row['io'] = process.io_counters()._asdict()
        except (AttributeError, psutil.Error): pass
        try: row['allowed_cpus'] = process.cpu_affinity()
        except (AttributeError, psutil.Error): pass
    for name in ('schedstat', 'wchan'):
        try: row[name] = Path(f'/proc/{process.pid}/{name}').read_text().strip()
        except OSError: pass
    return row


def snapshot(parent):
    result = dict(unix=time.time(), processes=[], unavailable={})
    for name, reader in (('load',os.getloadavg), ('memory',psutil.virtual_memory),
                         ('swap',psutil.swap_memory), ('cpu',psutil.cpu_times),
                         ('disk_io',psutil.disk_io_counters)):
        try:
            value=reader()
            result[name]=value._asdict() if hasattr(value,'_asdict') else value
        except (OSError,psutil.Error) as exc:
            result['unavailable'][name]=type(exc).__name__
    result['pressure'] = {}
    for kind in ('cpu', 'memory', 'io'):
        try: result['pressure'][kind] = Path('/proc/pressure', kind).read_text().strip()
        except OSError: pass
    try: children=parent.children(recursive=True)
    except (OSError,psutil.Error) as exc:
        children=[];result['unavailable']['process_tree']=type(exc).__name__
    for process in [parent, *children]:
        if process.pid == os.getpid(): continue
        try: result['processes'].append(process_record(process))
        except (OSError,psutil.Error): pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=10)
    args = parser.parse_args()
    parent = psutil.Process(args.pid)
    with args.output.open('a', buffering=1) as stream:
        while parent.is_running():
            try: row = snapshot(parent)
            except psutil.NoSuchProcess: break
            stream.write(json.dumps(row) + '\n')
            time.sleep(args.interval)


if __name__ == '__main__': main()
