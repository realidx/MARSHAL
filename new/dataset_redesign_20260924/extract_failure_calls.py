"""Extract archived prompts/answers; no regenerated prompts substituted."""
import json,tarfile,hashlib
from pathlib import Path
from collections import defaultdict,Counter
D=Path(__file__).resolve().parent;R=D.parents[1]
queue={(r['bank'],r['id']):r for r in map(json.loads,(D/'review_queue.jsonl').open())}
rows=defaultdict(list)
archives=[('old',R/'new/old_bp_full_training_calls_20260924'/n) for n in ('860494-steps-0-102.tar.gz','861241-steps-100-205.tar.gz')]+[('current',R/'new/d_evidence_20260924/training'/n) for n in ('d0-72-874127.tar.gz','d72-148-875169.tar.gz')]
for bank,path in archives:
 with tarfile.open(path) as tf:
  for m in tf:
   if not m.isfile() or '/calls/step-' not in '/'+m.name or not m.name.endswith('.jsonl'):continue
   step=int(m.name.split('step-')[1].split('.')[0])
   if bank=='old' and path.name.startswith('860494') and step>=100:continue
   for line in tf.extractfile(m):
    r=json.loads(line);key=(bank,r['task_id'])
    if key not in queue:continue
    rows[key].append({k:r.get(k) for k in ('request','text','completion','score','task_advantage','protocol_advantage','protocol_failure','replica','group','finish_reason')}|dict(step=step,archive=path.name,member=m.name))
summary=[]
folder=D/'archived_failure_calls';folder.mkdir(exist_ok=True)
for key,q in queue.items():
 bank,tid=key;rr=sorted(rows[key],key=lambda r:(r['step'],r['replica']))
 assert len(rr)==sum(e['samples'] for e in q['feedback']['events']),(key,len(rr))
 assert all(abs(r['task_advantage'] or 0)<1e-12 for r in rr),key
 def fingerprint(r):
  req=dict(r['request']);req.pop('seed',None);req.pop('model',None)
  return hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest()
 assert len({fingerprint(r) for r in rr})==1
 (folder/f'{bank}-{tid}.json').write_text(json.dumps(dict(bank=bank,id=tid,source_task=q['source_task'],calls=rr),ensure_ascii=False,indent=2)+'\n')
 summary.append(dict(bank=bank,id=tid,calls=len(rr),steps=sorted({r['step'] for r in rr}),request_hash=fingerprint(rr[0])))
(D/'archived_failure_index.json').write_text(json.dumps(summary,indent=2)+'\n')
print('tasks',len(summary),'calls',sum(r['calls'] for r in summary))
