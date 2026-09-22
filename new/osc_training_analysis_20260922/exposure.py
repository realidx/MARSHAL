import io,tarfile,json,re
from collections import Counter,defaultdict
from pathlib import Path
SRC=Path('new/osc_training_evidence_20260922/training');OUT=Path(__file__).resolve().parent
chains={'outcome':{'871236':(0,7),'871285':(8,29),'871623':(30,99)},'conditioned':{'871298':(0,43),'871607':(44,89)}}
result={}
for arm,jobs in chains.items():
 payload=b''.join(p.read_bytes() for p in sorted(SRC.glob(arm+'.tar.gz.part-*')))
 counts=Counter();unique=defaultdict(set);parents=defaultdict(set);mass=Counter();groups=defaultdict(set)
 with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as tf:
  for m in tf:
   if '/calls/' not in m.name or not m.isfile():continue
   job=next((j for j in jobs if '-'+j+'/' in m.name),None)
   match=re.search(r'step-(\d+)\.jsonl$',m.name)
   if not job or not match:continue
   step=int(match[1]);lo,hi=jobs[job]
   if not lo<=step<=hi:continue
   for line in tf.extractfile(m):
    r=json.loads(line);v=r['kind'];rel=str(r['belief_action_relevant']);key=v+'/'+rel
    counts[key]+=1;unique[key].add(r['canonical_id']);parents[key].add(r['package_id']);groups[key].add(r['group'])
    mass[key]+=abs(r['task_advantage'])*r['task_weight']
 result[arm]={k:dict(responses=n,cases=len(unique[k]),parents=len(parents[k]),groups=len(groups[k])) for k,n in counts.items()}
 print(arm,result[arm],flush=True)
(OUT/'exposure_summary.json').write_text(json.dumps(result,indent=2)+'\n')
