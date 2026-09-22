import json,hashlib
from pathlib import Path
BASE=Path('/tmp/osc-evidence');OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
q0={a:read(BASE/'training'/n/f'{n}-seed42-{j}'/'validation/step-0.json') for a,n,j in [('O','outcome','871236'),('C','conditioned','871298')]}
qc={a:{r['task']['id']:r for r in d['bp_calls']} for a,d in q0.items()}
same_input=[k for k in qc['O'] if qc['O'][k]['prompt_ids']==qc['C'][k]['prompt_ids']]
different=[k for k in same_input if qc['O'][k]['response_ids']!=qc['C'][k]['response_ids']]
flips=[k for k in same_input if qc['O'][k]['score']['correct']!=qc['C'][k]['score']['correct']]
endpoints={}
for a,n,j,s in [('O','outcome','871623',100),('C','conditioned','871607',90)]:
 d=read(BASE/'training'/n/f'{n}-seed42-{j}'/f'validation/step-{s}.json');curr={r['task']['id']:r for r in d['bp_calls']}
 rows=[]
 for k,r in curr.items():
  if r['task']['paired_view']!='O':continue
  old=qc[a][k];assert old['prompt_ids']==r['prompt_ids'];assert old['task']['teacher']==r['task']['teacher']
  rows.append(dict(id=k,parent=r['task']['package_id'],relevant=r['task']['belief_action_relevant'],q0=old['score']['correct'],final=r['score']['correct'],final_valid=r['score']['status']=='ok' and r['completion']['finish_reason']!='length'))
 endpoints[a]=rows
calbench={};index={}
for p in sorted((BASE/'calbench').glob('*/*/games/results.json')):
 rs=read(p);name=p.parents[1].name;index[name]={r['game_id']:r for r in rs}
 calbench[name]=dict(success=sum(r['metrics']['coordination_rate']==1 for r in rs),meetings=sum(r['metrics']['meetings_scheduled'] for r in rs),strict_format_failures=sum(r['strict_envelope_failures'] for r in rs),games=len(rs))
pairs=[]
for prefix in ['outcome','conditioned']:
 names=sorted([n for n in index if n.startswith(prefix)],key=lambda n:int(n.split('-')[0].removeprefix(prefix)))
 for x,y in zip(names,names[1:]):
  a,b=index[x],index[y];assert set(a)==set(b)
  lost=[k for k in a if a[k]['metrics']['coordination_rate']==1 and b[k]['metrics']['coordination_rate']!=1]
  gained=[k for k in a if a[k]['metrics']['coordination_rate']!=1 and b[k]['metrics']['coordination_rate']==1]
  pairs.append(dict(before=x,after=y,lost=lost,gained=gained))
result=dict(q0_same_prompt_count=len(same_input),q0_different_response_tokens=len(different),q0_different_correctness=flips,
            endpoint_cases=endpoints,calbench=calbench,calbench_pairs=pairs)
(OUT/'detailed_checks.json').write_text(json.dumps(result,indent=2)+'\n')
print('Q0 sameprompt/differentoutput/correctnessflip',len(same_input),len(different),len(flips))
for a,rows in endpoints.items():
 for relevant in [True,False]:
  rs=[r for r in rows if r['relevant']==relevant]
  print(a,relevant,len(rs),'parents',len({r['parent'] for r in rs}),'lost',sum(r['q0'] and not r['final'] for r in rs),'gain',sum(not r['q0'] and r['final'] for r in rs))
print(json.dumps(pairs,indent=2))
