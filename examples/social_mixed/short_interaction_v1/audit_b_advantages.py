"""Inspect saved advantages and matched exposure truncation; no inferred rewards."""
import collections,json,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parent
arcs=['new/d67_training_20260924/d67-first-67-updates.tar.gz','new/d67_125_continuation_20260924/d67-125-continuation.tar.gz']
groups=collections.defaultdict(lambda:collections.defaultdict(list))
for arc in arcs:
 with tarfile.open(arc) as tar:
  for m in tar:
   if '/calls/step-' not in m.name or not m.isfile():continue
   step=int(m.name.split('step-')[-1].split('.')[0])
   for line in tar.extractfile(m):
    r=json.loads(line)
    if r['kind']=='B':groups[r['task_id']][step].append(r)
def label(r):
 if r['finish_reason']=='length':return 'truncated'
 if r['score']['status']!='ok' or r.get('protocol_failure'):return 'invalid'
 return 'correct' if r['score'].get('correct') else 'wrong'
def stats(rs):
 out={'n':len(rs),'outcomes':dict(collections.Counter(label(r) for r in rs))}
 for field in ['task_advantage','protocol_advantage','advantage']:
  vals=[r.get(field,r['task_advantage']+r['protocol_advantage']) for r in rs]
  out[field]={'positive':sum(v>1e-9 for v in vals),'zero':sum(abs(v)<=1e-9 for v in vals),'negative':sum(v< -1e-9 for v in vals),'min':min(vals),'max':max(vals)}
 return out
ordered={tid:[rs for _,rs in sorted(steps.items())] for tid,steps in groups.items()}
zero={tid:es for tid,es in ordered.items() if len(es)>=3 and all(label(r)!='correct' for rs in es for r in rs)}
report={}
for name,subset in [('all_two_exposures',{t:e for t,e in ordered.items() if len(e)>=2}),('matched_three_exposures',{t:e for t,e in ordered.items() if len(e)>=3}),('never_correct_three',zero)]:
 n=2 if name=='all_two_exposures' else 3
 report[name]={'tasks':len(subset),'exposures':[stats([r for es in subset.values() for r in es[i]]) for i in range(n)]}
rs=[r for es in zero.values() for rows in es for r in rows]
report['zero_by_outcome']={lab:stats([r for r in rs if label(r)==lab]) for lab in sorted(set(map(label,rs)))}
report['zero_groups']={'total':sum(map(len,zero.values())),'with_positive_task':sum(any(r['task_advantage']>1e-9 for r in rows) for es in zero.values() for rows in es),'with_negative_protocol':sum(any(r['protocol_advantage']< -1e-9 for r in rows) for es in zero.values() for rows in es)}
report['zero_per_task']={tid:[stats(rows) for rows in es] for tid,es in zero.items()}
(ROOT/'b_advantage_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='zero_per_task'},indent=2))
