"""Offline descriptive audit. No checkpoint or causal estimates from sampled calls."""
import json,tarfile
from pathlib import Path
from collections import defaultdict,Counter
R=Path(__file__).resolve().parents[2]; D=R/'new/task_learning_audit_20260924'
def read(p):return [json.loads(l) for l in p.open()]
bank={r['id']:r for r in read(R/'examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl')}
def rate(e):
 c=e['counts'];n=c.get('correct',0)+c.get('wrong',0)
 return c.get('correct',0)/n if n else None
def describe(rows):
 out={}
 for key,rr in rows.items():
  pairs=[]
  for r in rr:
   es=r['events']; a,b=es[0],es[-1]
   if len(es)>1 and a['request_sha256']==b['request_sha256'] and rate(a)!=None and rate(b)!=None:pairs.append((rate(a),rate(b)))
  out[key]={'tasks':len(rr),'groups':sum(r['exposures'] for r in rr),'effective':sum(e['effective'] for r in rr for e in r['events']),'persistent_failure':sum(r['persistent_failure_observed'] for r in rr),'never_correct':sum(r['never_observed_correct'] for r in rr),'matched':len(pairs),'first':sum(a for a,b in pairs)/len(pairs) if pairs else None,'last':sum(b for a,b in pairs)/len(pairs) if pairs else None,'up':sum(b>a for a,b in pairs),'down':sum(b<a for a,b in pairs)}
 return out
out={}
for phase in ('old_BP_to99','old_BP_main'):
 rows=defaultdict(list)
 for r in read(D/(phase+'.jsonl')):rows[r['kind']+'/'+bank[r['task_id']]['skill']].append(r)
 out[phase]=describe(rows)
persistent={r['task_id'] for r in read(D/'old_BP_main.jsonl') if r['kind']=='B' and r['persistent_failure_observed']}
counts=defaultdict(Counter); examples={}; windows=defaultdict(lambda:defaultdict(Counter))
for fn in ('860494-steps-0-102.tar.gz','861241-steps-100-205.tar.gz'):
 with tarfile.open(R/'new/old_bp_full_training_calls_20260924'/fn) as t:
  for m in t:
   if not m.isfile() or not m.name.endswith('.jsonl'):continue
   step=int(m.name.split('step-')[1].split('.')[0])
   if fn.startswith('860494') and step>=100:continue
   for line in t.extractfile(m):
    r=json.loads(line);tid=r['task_id'];s=r['score'];kind=r['kind'];skill=bank[tid]['skill'];win=min(step//50,3)
    if r.get('finish_reason')=='length' or s.get('status')!='ok' or r.get('protocol_failure'):continue
    if kind=='B':
     label=('both_correct' if s.get('set_exact') and s.get('favored_exact') else 'set_only_wrong' if not s.get('set_exact') and s.get('favored_exact') else 'favored_only_wrong' if s.get('set_exact') else 'both_wrong')
     keys=['all/'+skill,'pre99/'+skill if step<100 else 'post99/'+skill]
     if tid in persistent:keys+=['persistent/'+skill]
     for k in keys:
      counts[k][label]+=1; counts[k]['false_exclusions']+=s.get('false_exclusions',0);counts[k]['extra_possibilities']+=s.get('extra_possibilities',0)
     if tid in persistent and tid not in examples:
      examples[tid]={'skill':skill,'kernel':bank[tid]['kernel'],'gold':bank[tid]['teacher'].get('gold'),'weights':bank[tid]['teacher'].get('preference_weights'),'score':s,'text':r.get('text'),'step':step}
    windows[kind+'/'+skill][tid][str(win)+'_correct']+=bool(s.get('correct'));windows[kind+'/'+skill][tid][str(win)+'_n']+=1
out['B_error_components']={k:dict(v) for k,v in counts.items()}
out['fixed_four_window_panel']={}
for k,ts in windows.items():
 panel={tid:c for tid,c in ts.items() if all(c[str(w)+'_n'] for w in range(4))}
 out['fixed_four_window_panel'][k]={'n':len(panel),'rates':[sum(c[str(w)+'_correct']/c[str(w)+'_n'] for c in panel.values())/len(panel) if panel else None for w in range(4)]}
out['persistent_B_examples']=examples
(D/'operation_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='persistent_B_examples'},ensure_ascii=False,indent=2))
# Fixed task panels remove task-composition changes, not sampling noise or exposure selection.
extra={}
for name in ('old_BP_main','new_D'):
 rs=read(D/(name+'.jsonl')); z={}
 for kind in sorted({r['kind'] for r in rs}):
  failures=[r for r in rs if r['kind']==kind and r['persistent_failure_observed']]
  z[kind]={'persistent':len(failures),'never_effective':sum(not any(e['effective'] for e in r['events']) for r in failures)}
 extra[name]=z
extra['new_D_fixed_panel']={}
for kind in ('O','B','Pplus'):
 panel=[]
 for r in read(D/'new_D.jsonl'):
  if r['kind']!=kind or len({e['request_sha256'] for e in r['events']})!=1:continue
  wins=[Counter() for _ in range(4)]
  for e in r['events']:wins[min(e['step']//40,3)].update(e['counts'])
  if all(c['correct']+c['wrong'] for c in wins):panel.append([c['correct']/(c['correct']+c['wrong']) for c in wins])
 extra['new_D_fixed_panel'][kind]={'n':len(panel),'rates':[sum(r[i] for r in panel)/len(panel) for i in range(4)] if panel else []}
assert all(len({e['request_sha256'] for e in r['events']})==1 for r in read(D/'old_BP_main.jsonl'))
out['additional']=extra
(D/'operation_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
