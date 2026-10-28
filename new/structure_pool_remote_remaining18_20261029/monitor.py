"""External Linux resource sampling; frozen solver code is unchanged."""
import json,os,resource,signal,subprocess,sys,time
from pathlib import Path
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
cmd=sys.argv[2:];clock=os.sysconf('SC_CLK_TCK');peak={};started=time.monotonic()
proc=subprocess.Popen(cmd)
def stop(sig,frame):
 if proc.poll() is None:proc.send_signal(sig)
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
def descendants(pid):
 ids=[pid]
 for p in ids:
  try:ids.extend(map(int,Path(f'/proc/{p}/task/{p}/children').read_text().split()))
  except (OSError,ValueError):pass
 return ids
with (out/'resources.jsonl').open('w') as log:
 while proc.poll() is None:
  samples=[]
  for pid in descendants(proc.pid):
   try:
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    status=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    sample=dict(pid=pid,cpu_seconds=(int(fields[11])+int(fields[12]))/clock,
     rss_kib=int(status.get('VmRSS','0 kB').split()[0]),threads=int(status.get('Threads','0')),
     affinity=status.get('Cpus_allowed_list','').strip())
    old=peak.setdefault(str(pid),dict(max_rss_kib=0,cpu_seconds=0))
    old['max_rss_kib']=max(old['max_rss_kib'],sample['rss_kib']);old['cpu_seconds']=sample['cpu_seconds']
    samples.append(sample)
   except (OSError,ValueError,KeyError,IndexError):pass
  log.write(json.dumps(dict(elapsed_seconds=time.monotonic()-started,processes=samples))+'\n');log.flush()
  time.sleep(2)
rc=proc.wait();usage=resource.getrusage(resource.RUSAGE_CHILDREN);elapsed=time.monotonic()-started
(out/'resource_summary.json').write_text(json.dumps(dict(command=cmd,exit_code=rc,elapsed_seconds=elapsed,
 child_cpu_seconds=usage.ru_utime+usage.ru_stime,average_busy_cpus=(usage.ru_utime+usage.ru_stime)/elapsed,
 child_maxrss_kib=usage.ru_maxrss,sampled_process_peaks=peak),indent=2)+'\n')
sys.exit(rc)
