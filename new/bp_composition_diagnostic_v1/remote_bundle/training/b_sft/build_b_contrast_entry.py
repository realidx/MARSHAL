"""Three review-only entry lessons on an existing train family; no split changes."""
from copy import copy,deepcopy
import hashlib
import json
from pathlib import Path
from training.b_sft.build_b_response_bridges import fixture,offer,response_certificate,verify_task
from training.b_sft.build_bp_pilot import make_task,topology
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.social_named_probe import request,present
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_bp/b_contrast_entry_v2'

def build():
 raw,public=fixture('shared_partner_commitment','binary')
 family=topology(raw)
 historical=[]
 for path in ['examples/social_bp/data/tasks.jsonl','examples/social_bp/b_response_bridges_v1/tasks.jsonl','examples/social_bp/data_two_a100_v1/tasks.jsonl']:
  historical += [json.loads(x) for x in (ROOT/path).read_text().splitlines()]
 assert not any(t['family']==family and t['split'] in ('validation','test') for t in historical)
 rows=[]
 for name,goal,response in [('target_accept',0,'ACCEPT'),('target_reject',0,'REJECT'),('unrelated_accept',1,'ACCEPT')]:
  setup=[{'action':'PASS'},offer(raw,goal)]
  before=PrivateEpisode(raw,setup);prior=before.belief(1,0,observer=0,own=raw['own_preferences'])
  prior={k:prior[k] for k in ['possible_preferences','favored']}
  cert=response_certificate(before,response);assert cert is not None
  after=copy(before);event={'response':response};after.observe(event)
  t=make_task(after,public,setup,[event],'B',0,family,previous=prior,source='b-contrast-entry-v2:'+name)
  t.update(split='train',name_variant=1,diagnostic_group=name,short_teaching=True,
           contrast_group='b-contrast-entry-v2-shared-train',review_only=True)
  t['teacher']['response_certificate']=cert
  check=verify_task(t)
  original=request(t,'action_tools',1);candidate=deepcopy(original);v=present(t,1)
  # Scope restricted to empty-commitment final-response lessons, verified directly.
  state=before.tree.entries[before.index].node.state.public_state()
  assert all(not any(row) for row in state['commitments'])
  offer_row=v['history'][-2]
  timeline=('EVENT ORDER\n'
   +'Before the offer, neither player had any binding commitments.\n'
   +offer_row['actor']+' then proposed these additions: '
   +offer_row['actor']+': '+', '.join(offer_row['self_commitments'])+'; '
   +offer_row['partner']+': '+', '.join(offer_row['partner_commitments'])+'. The offer alone bound nothing.\n'
   +v['history'][-1]['actor']+' then chose '+response+'. '
   +'The current binding commitments listed below are the state AFTER that response.\n\n')
  candidate['messages'][1]['content']=timeline+candidate['messages'][1]['content']
  assert candidate['tools']==original['tools'] and candidate['messages'][0]==original['messages'][0]
  rows.append((t,original,candidate,check))
 assert [t['teacher']['gold'] for t,_,_,_ in rows]==[
  {'possible_preferences':['want'],'favored':'want'},
  {'possible_preferences':['avoid'],'favored':'avoid'},
  {'possible_preferences':['want','avoid'],'favored':'undetermined'}]
 return rows

def main():
 rows=build();OUT.mkdir(exist_ok=True)
 for name,records in [('tasks.jsonl',[r[0] for r in rows]),('requests.jsonl',[{'task_id':t['id'],'condition':'explicit_timeline','request':q} for t,o,q,c in rows]),('original_requests.jsonl',[{'task_id':t['id'],'condition':'original','request':o} for t,o,q,c in rows])]:
  (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
 meta={'review_only':True,'merged':False,'model_tested':False,'families':1,'tasks':3,'family':rows[0][0]['family'],'checks':[r[3] for r in rows], 'note':'Existing train family reused; not three independent scenarios. Candidate adds derived public event timing only; original system/tool/reward preserved. Original requests retained for possible paired presentation diagnostic.', 'files':{n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','requests.jsonl','original_requests.jsonl']}}
 (OUT/'audit.json').write_text(json.dumps(meta,indent=2)+'\n')
 lines=['# B入口对照：一组审核候选','', '仅3题、1个既有train家族；未合并、未调用模型。旧validation/test不动。', '', '候选请求增加由原生状态导出的公开事件前后事实，不提供收益表、posterior或答案。原system、规则、工具和1024预算保留。原始请求另存，以便分离结构简化与事件呈现的影响。','']
 for t,o,q,c in rows:
  lines += ['## '+t['diagnostic_group']+' / '+t['id'],'','### 模型实际system','',q['messages'][0]['content'],'','### 模型实际user','',q['messages'][1]['content'],'','### 工具定义','', '```json',json.dumps(q['tools'],ensure_ascii=False,indent=2),'```','','### 仅审核可见：标签与独立收益证书','','```json',json.dumps(t['teacher']['response_certificate'],ensure_ascii=False,indent=2),'```','']
 (OUT/'review.md').write_text('\n'.join(lines))
 print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
