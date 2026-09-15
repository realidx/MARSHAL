"""Read-only Linux process CPU accounting over a short interval; no model calls."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import time


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def parse_stat(raw):
    # comm can contain spaces and parentheses. The final ')' ends field 2.
    end = raw.rindex(')')
    fields = raw[end+2:].split()
    return dict(name=raw[raw.index('(')+1:end], ppid=int(fields[1]),
                ticks=int(fields[11])+int(fields[12]), start=int(fields[19]))


def snapshot():
    result = dict(at=time.monotonic(), stat=read('/proc/stat'),
                  loadavg=read('/proc/loadavg'), cpu_pressure=read('/proc/pressure/cpu'),
                  processes={}, unreadable=0)
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            p = parse_stat((path/'stat').read_text())
            p['uid'] = path.stat().st_uid
            result['processes'][path.name] = p
        except (OSError, ValueError, IndexError):
            result['unreadable'] += 1
    return result


def compare(before, after, ticks_per_second):
    elapsed = after['at']-before['at']
    ranked = []
    for pid, p in after['processes'].items():
        old = before['processes'].get(pid)
        if old is None or old['start'] != p['start']:
            continue
        pct = 100*(p['ticks']-old['ticks'])/ticks_per_second/elapsed
        ranked.append(dict(pid=int(pid), **p, cpu_percent=pct))
    return sorted(ranked, key=lambda p: p['cpu_percent'], reverse=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--seconds', type=int, default=10)
    args = cli.parse_args()
    if not 2 <= args.seconds <= 30:
        cli.error('--seconds must be 2–30')
    if not Path('/proc/stat').exists():
        cli.error('Run on the Linux server, not the Mac')
    args.output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    print(f'Capturing CPU use for {args.seconds}s; no processes are stopped.', flush=True)
    time.sleep(args.seconds)
    after = snapshot()
    ranked = compare(before, after, os.sysconf('SC_CLK_TCK'))
    users = defaultdict(float)
    parents = defaultdict(float)
    for p in ranked:
        users[str(p['uid'])] += p['cpu_percent']
        parents[str(p['ppid'])] += p['cpu_percent']
        try:
            p['user'] = pwd.getpwuid(p['uid']).pw_name
        except KeyError:
            p['user'] = str(p['uid'])
    for p in ranked[:60]:
        root = Path('/proc')/str(p['pid'])
        current = read(root/'stat')
        if current is None or parse_stat(current)['start'] != p['start']:
            p['exited_before_details'] = True
            continue
        status = read(root/'status') or ''
        p['status'] = {line.split(':', 1)[0]:line.split(':', 1)[1].strip()
                       for line in status.splitlines() if line.startswith(
                           ('Threads:', 'Cpus_allowed_list:', 'Mems_allowed_list:'))}
        p['cgroup'] = read(root/'cgroup')
        # No command arguments or environment variables (may contain credentials).
        if p['uid'] == os.getuid():
            for name in ('exe', 'cwd'):
                try:
                    p[name] = str((root/name).readlink())
                except OSError:
                    pass
    report = dict(utc=datetime.now(timezone.utc).isoformat(),
                  elapsed=after['at']-before['at'], logical_cpus=os.cpu_count(),
                  loadavg=after['loadavg'], cpu_pressure=after['cpu_pressure'],
                  cpu_percent_definition='100% = one logical CPU; process threads aggregated; interval delta, not lifetime average',
                  visibility_note='Only readable processes surviving both snapshots are ranked; short-lived or hidden processes may be missing.',
                  by_uid=dict(users), by_parent_pid=dict(parents), processes=ranked,
                  before=before, after=after)
    (args.output/'cpu.json').write_text(json.dumps(report, indent=2)+'\n')
    print('loadavg: '+str(after['loadavg']).strip())
    print('CPU pressure: '+str(after['cpu_pressure']).strip())
    print('CPU%    USER             PID       PPID      THREADS  ALLOWED_CPUS    NAME')
    for p in ranked[:30]:
        s = p.get('status', {})
        print(f"{p['cpu_percent']:7.1f} {p['user']:16} {p['pid']:<9} {p['ppid']:<9} "
              f"{s.get('Threads','?'):<8} {s.get('Cpus_allowed_list','?'):<15} {p['name']}")
    print('CPU_REPORT='+str((args.output/'cpu.json').resolve()))


if __name__ == '__main__':
    main()
