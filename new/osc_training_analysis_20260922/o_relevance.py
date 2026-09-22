import json,tarfile,io,re
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
BASE=Path('/tmp/osc-evidence/training/outcome')
segs={'871236':(0,7),'871285':(8,29),'871623':(30,99)}
val={};series={};panel={}
for job,(lo,hi) in segs.items():
 root=BASE/f'outcome-seed42-{job}'
 for folder in ('static_o_monitor','validation'):
  for p in (root/folder).glob('step-*.json'):
   if 'FAILED' in p.name:continue
   d=json.loads(p.read_text());step=d['completed_updates']
   if not ((lo==0 and step==0) or lo<step<=hi+1):continue
   rows=[r for r in d.get('bp_calls',d.get('calls',[])) if r['task']['paired_view']=='O']
   val[step]=rows
for step,rows in sorted(val.items()):
 for r in rows:
  t=r['task'];cid=t['canonical_id'];panel[cid]=t
  series.setdefault(cid,[]).append(dict(step=step,correct=r['score']['correct'],valid=r['score']['status']=='ok' and r['completion']['finish_reason']!='length',regret=r['score'].get('own_regret')))
windows=defaultdict(Counter);cases=defaultdict(Counter)
payload=b''.join(p.read_bytes() for p in sorted((ROOT/'new/osc_training_evidence_20260922/training').glob('outcome.tar.gz.part-*')))
with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as tf:
 for m in tf:
  if '/calls/' not in m.name or not m.isfile():continue
  job=next((j for j in segs if '-'+j+'/' in m.name),None);match=re.search(r'step-(\d+)\.jsonl$',m.name)
  if not job or not match:continue
  step=int(match[1]);lo,hi=segs[job]
  if not lo<=step<=hi:continue
  groups=defaultdict(list)
  for line in tf.extractfile(m):
   r=json.loads(line);groups[r['group']].append(r)
  for rs in groups.values():
   r=rs[0];rel=r['belief_action_relevant'];w=windows[step//10,rel];w['groups']+=1
   valid=[x for x in rs if not x['protocol_failure']]
   rewards=[x['score']['reward'] for x in valid]
   w['responses']+=len(rs);w['valid']+=len(valid);w['correct']+=sum(rewards)
   w['mixed_groups']+=int(bool(rewards) and max(rewards)>min(rewards))
   w['all_valid_wrong_groups']+=int(bool(rewards) and max(rewards)==0)
   w['all_valid_correct_groups']+=int(bool(rewards) and min(rewards)==1)
   w['truncated']+=sum(x['completion']['finish_reason']=='length' for x in rs)
   w['tokens']+=sum(len(x['response_ids']) for x in rs)
   cases[r['canonical_id']]['groups']+=1
result=dict(training_windows=[dict(first=10*k[0],last=10*k[0]+9,relevant=k[1],**dict(v)) for k,v in sorted(windows.items())],
 panel=[dict(canonical_id=cid,parent=t['package_id'],kernel=t['source_kernel'],mode=t['completion_mode'],relevant=t['belief_action_relevant'],trajectory=series[cid]) for cid,t in panel.items()],
 validation_windows=[dict(step=step,relevant=rel,n=sum(r['task']['belief_action_relevant']==rel for r in rows),correct=sum(r['score']['correct'] is True for r in rows if r['task']['belief_action_relevant']==rel)) for step,rows in sorted(val.items()) for rel in (True,False)],
 training_case_exposure={k:dict(v) for k,v in cases.items()})
(OUT/'o_relevance.json').write_text(json.dumps(result,indent=2)+'\n')
for w in result['training_windows']:
 print(w['first'],w['relevant'],'groups',w['groups'],'acc',round(w['correct']/w['valid'],3),'mixed',round(w['mixed_groups']/w['groups'],3),'allwrong',w['all_valid_wrong_groups'],'len',round(w['tokens']/w['responses']), 'trunc',round(w['truncated']/w['responses'],3))
print('PANEL')
for r in result['panel']:
 print(r['canonical_id'][:8],r['parent'][:8],r['kernel'],r['mode'],r['relevant'],''.join('1' if x['correct'] else '0' for x in r['trajectory']))
