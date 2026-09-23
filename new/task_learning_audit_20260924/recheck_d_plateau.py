"""Recheck ceiling/floor versus mixed learning, using archived per-question call counts."""
import json
from pathlib import Path
from collections import Counter
P=Path(__file__).parent
rows=[json.loads(l) for l in (P/'new_D.jsonl').read_text().splitlines()]
windows=[(0,40),(40,80),(80,120),(120,148)]
def stats(events):
 c=Counter()
 for e in events:c.update(e['counts'])
 n=c['correct']+c['wrong']
 return (c['correct']/n if n else None,n,c)
out={}
for kind in ('O','B','Pplus'):
 rr=[t for t in rows if t['kind']==kind];repeated=[t for t in rr if t['exposures']>=3]
 bins=Counter();panel=[];ids={}
 for t in repeated:
  p,n,c=stats(t['events'])
  b='no_scored' if p is None else 'always_correct' if p==1 else 'always_wrong' if p==0 else 'mixed'
  bins[b]+=1
  v=[stats([e for e in t['events'] if lo<=e['step']<hi])[0] for lo,hi in windows]
  if all(x is not None for x in v):panel.append((t,v,b))
 earlyzero=[];earlyperfect=[]
 for t in rr:
  a,na,_=stats([e for e in t['events'] if e['step']<40]);b,nb,_=stats([e for e in t['events'] if e['step']>=40])
  if a==0 and b is not None:earlyzero.append((t['task_id'],na,nb,b))
  if a==1 and b is not None:earlyperfect.append((t['task_id'],na,nb,b))
 def panel_summary(ps):
  return dict(n=len(ps),rates=[sum(v[j] for _,v,_ in ps)/len(ps) for j in range(4)] if ps else [])
 out[kind]=dict(total=len(rr),single=sum(t['exposures']==1 for t in rr),repeated_ge3=len(repeated),
 repeated_categories=dict(bins),fixed_panel=panel_summary(panel),
 mixed_fixed_panel=panel_summary([p for p in panel if p[2]=='mixed']),
 early_zero_revisited=len(earlyzero),early_zero_later_correct=sum(x[3]>0 for x in earlyzero),
 early_perfect_revisited=len(earlyperfect),early_perfect_later_wrong=sum(x[3]<1 for x in earlyperfect),
 early_zero_examples=earlyzero,early_perfect_examples=earlyperfect,
 mixed_panel_ids=[t['task_id'] for t,_,b in panel if b=='mixed'])
(P/'d_plateau_recheck.json').write_text(json.dumps(out,indent=2)+'\n')
for k,v in out.items():print(k,json.dumps({a:b for a,b in v.items() if not a.endswith(('examples','ids'))}))
