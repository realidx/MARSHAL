import json
from pathlib import Path
root=Path(__file__).parent
bank={t['id']:t for t in map(json.loads,open('examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl'))}
rows=list(map(json.loads,(root/'old_BP_main.jsonl').read_text().splitlines()))
out=[]
for r in rows:
 e=r['events']
 if r['kind']!='P' or len(e)<3:continue
 first=e[0]['counts'].get('correct',0)/e[0]['samples'];last=e[-3:];rate=sum(x['counts'].get('correct',0) for x in last)/sum(x['samples'] for x in last)
 if first>3/8 or rate<.75:continue
 t=bank[r['task_id']];out.append(dict(task_id=r['task_id'],skill=t['skill'],q0_observed=e[0]['step']==0,first_step=e[0]['step'],first_correct=e[0]['counts'].get('correct',0),last3_correct=sum(x['counts'].get('correct',0) for x in last),last3_samples=sum(x['samples'] for x in last),effective_groups=sum(x['effective'] for x in e),same_request=len({x['request_sha256'] for x in e})==1,events=e,input=t['input'],teacher=t['teacher']))
(root/'p_acquisition_candidates.json').write_text(json.dumps(out,indent=2))
print('screened',sum(r['kind']=='P' for r in rows),'selected',len(out),'true Q0',sum(r['q0_observed'] for r in out))
for r in out:print(r['task_id'],r['skill'],r['first_step'],r['first_correct'],r['last3_correct'],r['effective_groups'],r['same_request'])
