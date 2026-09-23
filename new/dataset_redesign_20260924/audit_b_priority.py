"""Recompute persistent-failure B labels under the recorded teacher; no label edits."""
import json,time,traceback
from pathlib import Path
from collections import Counter
from training.social_mixed.audit_zero_signal import audit_task
D=Path(__file__).resolve().parent
rows=[json.loads(l) for l in (D/'review_queue.jsonl').open()]
results=[]
with (D/'b_recompute.jsonl').open('w') as f:
 for r in rows:
  if r['source_task']['task']!='B':continue
  start=time.monotonic()
  try:
   audit,_=audit_task(r['source_task'])
   result=dict(bank=r['bank'],id=r['id'],status='teacher_recomputed',audit=audit)
  except Exception as exc:
   result=dict(bank=r['bank'],id=r['id'],status='unresolved',error=repr(exc),traceback=traceback.format_exc())
  result['seconds']=time.monotonic()-start;results.append(result)
  f.write(json.dumps(result)+'\n');f.flush()
  print(r['bank'],r['id'],result['status'],round(result['seconds'],2),flush=True)
summary=dict(statuses=dict(Counter(r['bank']+'/'+r['status'] for r in results)),
 independent_backward=sum(r.get('audit',{}).get('independent_information_compatible_backward',False) for r in results),
 policy_hash_match=sum(r.get('audit',{}).get('selected_policy_match',False) for r in results),
 caveat='Teacher reconstruction and scorer checks do not prove the natural-language prompt identifies a unique policy.')
(D/'b_recompute_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
