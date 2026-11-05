"""Keep v3 presentation and add audited train-only counterexamples to action shortcuts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from training.b_sft.b_chronological_prompt import render
from training.b_sft.social_named_probe import request,present
from training.b_sft.build_b_response_bridges import verify_task
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_bp/b_chronological_controls_v4'

def main():
 source=ROOT/'examples/social_bp/b_response_bridges_v1/tasks.jsonl'
 bank=[json.loads(x) for x in source.read_text().splitlines()]
 existing={t['id']:t for t in map(json.loads,(ROOT/'examples/social_bp/b_chronological_v3/tasks.jsonl').read_text().splitlines())}
 selected=[t for t in bank if t['split']=='train' and 'previous_belief' in t['input'] and any(t['source'].endswith(s) for s in ('shared_partner_commitment:binary','shared_partner_commitment:altruistic','shared_partner_commitment:conflict','coupled_payoffs:net_payoff'))]
 assert len(selected)==11 and set(existing)<=set(t['id'] for t in selected)
 held=[]
 for file in ['examples/social_bp/data/tasks.jsonl','examples/social_bp/b_response_bridges_v1/tasks.jsonl','examples/social_bp/data_two_a100_v1/tasks.jsonl']:
  held += [t for t in map(json.loads,(ROOT/file).read_text().splitlines()) if t['split'] in ('validation','test')]
 assert not {t['family'] for t in selected}&{t['family'] for t in held}
 OUT.mkdir(exist_ok=True);tasks=[];requests=[];checks=[]
 lines=['# B对照检查：固定v3呈现','','11题：保留原3题，加入8道已有train对照；共2个结构家族。不是新增独立数据，也未合并到正式训练采样器。未调用模型。', '', '时序、目标表格、具名偏好呈现保持v3，不再增加提示。规则、工具、1024预算与二元reward不变。', '', '| ID | 对照机制 | 证据 | 旧belief | 标签 |','| --- | --- | --- | --- | --- |']
 for old in selected:
  t=deepcopy(existing.get(old['id'],old))
  if t['id'] in existing:assert t['input']==old['input'] and t['teacher']['gold']==old['teacher']['gold']
  t['check_role']='anchor' if t['id'] in existing else 'counterexample'
  t['control_mechanism']=old['source'].split(':')[-1]
  t['diagnostic_group']=t['control_mechanism']+'_'+old['evidence_relation']+'_'+old['input']['voluntary_history'][0]['response'].lower()
  t['review_only']=True
  check=verify_task(t);checks.append(check)
  req=request(t,'action_tools',t['name_variant']);req['messages'][1]['content']=render(present(t,t['name_variant']))
  requests.append(dict(task_id=t['id'],condition='chronological_tables',request=req));tasks.append(t)
  if t['id'] in existing:
   previous=next(r for r in map(json.loads,(ROOT/'examples/social_bp/b_chronological_v3/requests.jsonl').read_text().splitlines()) if r['task_id']==t['id'])
   assert previous['request']==req
  lines.append('| '+' | '.join([t['id'],t['control_mechanism'],old['evidence_relation']+' / '+old['input']['voluntary_history'][0]['response'],json.dumps(t['input']['previous_belief']),json.dumps(t['teacher']['gold'])])+' |')
 for t,q in zip(tasks,requests):
  lines+=['','## '+t['diagnostic_group']+' / '+t['id'],'','### 模型实际user','',q['request']['messages'][1]['content'],'','### 本地独立收益证书（不发送）','','```json',json.dumps(t['teacher']['response_certificate'],ensure_ascii=False,indent=2),'```']
 for name,rows in [('tasks.jsonl',tasks),('requests.jsonl',requests)]:
  (OUT/name).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
 (OUT/'review.md').write_text('\n'.join(lines))
 audit=dict(tasks=11,anchors=3,added_checks=8,families=2,all_train=True,heldout_family_overlap=0,anchor_requests_byte_equivalent=True,merged=False,model_tested=False,checks=checks,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),renderer_sha256=hashlib.sha256((ROOT/'training/b_sft/b_chronological_prompt.py').read_bytes()).hexdigest(),note='Existing train semantics reused; no new independent scenarios or held-out generalization claim.',planned_samples=88,group_size=8,files={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','requests.jsonl']})
 (OUT/'audit.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
