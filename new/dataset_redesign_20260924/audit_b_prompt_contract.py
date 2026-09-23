import json,tarfile
from pathlib import Path
from collections import Counter
from training.b_sft.preference_contract import belief
R=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
rows={}
for t in map(json.loads,(R/'examples/social_mixed/paired_bank_v2/tasks.jsonl').open()):
 if t['task']!='B':continue
 mass=t['teacher']['preference_weights'];zero=belief(mass,0)
 if zero!=t['teacher']['gold']:
  rows[t['id']]=dict(id=t['id'],split=t['split'],mass=mass,teacher=t['teacher']['gold'],literal_unique_top=zero,archived=None)
for fn in ('d0-72-874127.tar.gz','d72-148-875169.tar.gz'):
 with tarfile.open(R/'new/d_evidence_20260924/training'/fn) as tf:
  for m in tf:
   if not m.isfile() or not m.name.startswith('./calls/step-') or not m.name.endswith('.jsonl'):continue
   for line in tf.extractfile(m):
    r=json.loads(line);tid=r['task_id']
    if tid not in rows:continue
    entry=rows[tid];counts=entry.setdefault('observed',{'legal':0,'teacher_correct':0,'literal_top_correct':0,'literal_top_marked_wrong':0})
    if r['score'].get('status')=='ok' and not r.get('protocol_failure') and r.get('finish_reason')!='length':
     counts['legal']+=1;counts['teacher_correct']+=bool(r['score'].get('correct'))
     try:
      fn=r['completion']['raw_message']['tool_calls'][0]['function'];j=json.loads(fn['arguments'])['judgments'][0]
      literal=set(j['possible_preferences'])==set(entry['literal_unique_top']['possible_preferences']) and j['favored']==entry['literal_unique_top']['favored']
      counts['literal_top_correct']+=literal;counts['literal_top_marked_wrong']+=literal and not r['score'].get('correct')
     except (KeyError,IndexError,ValueError,TypeError):pass
    if rows[tid]['archived'] is not None:continue
    txt='\n'.join(x['content'] for x in r['request']['messages'])
    rows[tid]['archived']=dict(archive=fn,member=m.name,unique_top='uniquely most supported remaining value' in txt,
                             explicit_margin='10 percentage points' in txt,request=r['request'])
(D/'b_prompt_contract.json').write_text(json.dumps(list(rows.values()),ensure_ascii=False,indent=2)+'\n')
print(dict(Counter(r['split'] for r in rows.values())))
print('archived',sum(r['archived'] is not None for r in rows.values()),'unique_top_without_margin',sum(bool(r['archived']) and r['archived']['unique_top'] and not r['archived']['explicit_margin'] for r in rows.values()))
