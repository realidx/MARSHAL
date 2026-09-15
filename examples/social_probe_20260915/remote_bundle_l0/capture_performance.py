"""Read-only 60-second GPU/CPU/vLLM capture beside a running probe; no model requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import urlopen


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=4)
        return dict(stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(error=str(exc))


def proc_snapshot():
    result = {}
    for name in ('loadavg', 'stat', 'meminfo', 'pressure/cpu', 'pressure/io', 'self/cgroup', 'self/status'):
        try:
            result[name] = (Path('/proc')/name).read_text()
        except OSError:
            pass
    return result


def metrics(port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/metrics', timeout=2) as r:
            body = r.read().decode()
        values = {}
        for line in body.splitlines():
            match = re.match(r'^(vllm:[\w]+)(?:\{.*\})?\s+([\d.eE+\-]+)(?:\s.*)?$', line)
            if match:
                name, value = match.groups()
                values[name] = values.get(name, 0.)+float(value)
        return dict(values=values, raw=body)
    except (OSError, ValueError) as exc:
        return dict(error=str(exc))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--run-dir', required=True, type=Path)
    cli.add_argument('--seconds', type=int, default=60)
    args = cli.parse_args()
    if not 5<=args.seconds<=300:
        cli.error('--seconds must be 5–300')
    manifest = json.loads((args.run_dir/'server_manifest.json').read_text())
    gpus = manifest['cuda_visible_devices']
    if isinstance(gpus, str):
        gpus = gpus.split(',')
    ports = [int(c[c.index('--port')+1]) for c in manifest['commands']]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = args.run_dir/f'performance-{stamp}'; out.mkdir(exist_ok=False)
    print('PERFORMANCE_DIR='+str(out), flush=True)
    static = dict(server_manifest=manifest, gpu_topology=command(['nvidia-smi','topo','-m']),
                  gpu_initial=command(['nvidia-smi','-i',','.join(gpus),'-q','-d','PERFORMANCE,CLOCK,POWER,TEMPERATURE']),
                  cgroup_limits={})
    for name in ('cpu.max', 'cpu.stat', 'cpuset.cpus.effective', 'cpu/cpu.cfs_quota_us', 'cpu/cpu.cfs_period_us'):
        path = Path('/sys/fs/cgroup')/name
        if path.exists():
            static['cgroup_limits'][name] = path.read_text()
    (out/'metadata.json').write_text(json.dumps(static,indent=2)+'\n')
    records = []; start = time.monotonic()
    query = 'index,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,clocks.sm,clocks.mem,pstate,temperature.gpu'
    with ThreadPoolExecutor(max_workers=len(ports)+2) as executor, (out/'samples.jsonl').open('x') as stream:
        while time.monotonic()-start < args.seconds:
            tick = time.monotonic()
            gpu = executor.submit(command, ['nvidia-smi','-i',','.join(gpus),'--query-gpu='+query,'--format=csv'])
            ps = executor.submit(command, ['ps','-u',str(os.getuid()),'-o','pid,ppid,pcpu,pmem,psr,stat,comm'])
            servers = {str(p):executor.submit(metrics,p) for p in ports}
            row = dict(elapsed=time.monotonic()-start, utc=datetime.now(timezone.utc).isoformat(),
                       proc=proc_snapshot(), gpu=gpu.result(), processes=ps.result(),
                       servers={p:f.result() for p,f in servers.items()})
            records.append(row); stream.write(json.dumps(row)+'\n'); stream.flush()
            time.sleep(max(0, min(1-(time.monotonic()-tick), args.seconds-(time.monotonic()-start))))
    summary = dict(samples=len(records), seconds=time.monotonic()-start, servers={})
    for port in map(str,ports):
        valid = [(r['elapsed'],r['servers'][port]['values']) for r in records if 'values' in r['servers'][port]]
        stats = dict(metric_samples=len(valid))
        for name in ('vllm:num_requests_running','vllm:num_requests_waiting','vllm:num_requests_swapped'):
            vs = [v[name] for _,v in valid if name in v]
            if vs:
                stats[name] = dict(mean=sum(vs)/len(vs), max=max(vs), zero_fraction=sum(x==0 for x in vs)/len(vs))
        if len(valid)>1:
            dt = valid[-1][0]-valid[0][0]
            for name in ('vllm:generation_tokens_total','vllm:prompt_tokens_total','vllm:num_preemptions_total'):
                if name in valid[0][1] and name in valid[-1][1]:
                    delta = valid[-1][1][name]-valid[0][1][name]
                    stats[name] = dict(delta=delta, per_second=delta/dt if dt>0 and delta>=0 else None)
        summary['servers'][port] = stats
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2), flush=True)


if __name__ == '__main__':
    main()
