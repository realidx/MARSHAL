"""Restrict inherited Slurm affinity to one logical CPU per physical core."""
import json,os,sys
from pathlib import Path
original=sorted(os.sched_getaffinity(0));cores={}
for cpu in original:
 root=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
 key=((root/'physical_package_id').read_text().strip(),(root/'core_id').read_text().strip())
 cores.setdefault(key,cpu)
wanted=int(os.environ['SLURM_CPUS_PER_TASK'])
if len(cores)<wanted:raise RuntimeError(f'Only {len(cores)} physical cores in allocation, need {wanted}')
chosen=sorted(cores.values())[:wanted];os.sched_setaffinity(0,chosen)
print(json.dumps(dict(physical_affinity=dict(original=original,chosen=chosen,physical_cores=len(chosen)))),flush=True)
os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
