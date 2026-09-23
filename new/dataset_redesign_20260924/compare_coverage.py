import json,statistics
from pathlib import Path
from collections import Counter
D=Path(__file__).resolve().parent;A=D.parent/'task_learning_audit_20260924'
read=lambda p:[json.loads(l) for l in p.open()]
result={}
for label,name,end in [('old_to99','old_BP_main',99),('old_to147','old_BP_main',147),('old_to205','old_BP_main',205),('D_to147','new_D',147)]:
 rows=read(A/(name+'.jsonl'));out={}
 for kind in sorted({r['kind'] for r in rows}):
  size=({'B':294,'P':300} if name.startswith('old') else {'O':373,'B':373,'Pplus':314})[kind]
  counts=[sum(e['step']<=end for e in r['events']) for r in rows if r['kind']==kind];counts=[n for n in counts if n]
  groups=sum(counts);out[kind]=dict(bank_size=size,groups=groups,seen=len(counts),unseen=size-len(counts),once=counts.count(1),repeated=sum(n>1 for n in counts),median_seen=statistics.median(counts),max=max(counts),top_10_task_group_share=sum(sorted(counts,reverse=True)[:10])/groups)
 result[label]=out
(D/'coverage_comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
