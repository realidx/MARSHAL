"""Generate review candidate without changing any game or target label."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from training.b_sft.b_chronological_prompt import render
from training.b_sft.social_named_probe import present,request
from training.b_sft.build_b_response_bridges import verify_task
ROOT=Path(__file__).resolve().parents[2]

def main():
 source=ROOT/'examples/social_bp/b_contrast_entry_v2/tasks.jsonl'
 out=ROOT/'examples/social_bp/b_chronological_v3';out.mkdir(exist_ok=True)
 tasks=[json.loads(x) for x in source.read_text().splitlines()]
 requests=[];checks=[];lines=['# B 三题：按事件顺序呈现（审核候选）','','游戏、偏好、teacher、标签与v2完全相同。仅替换user呈现；system、工具、奖励、1024输出不变。未合并、未采样。', '','改动：目标按玩家分列；已知偏好全部使用明确姓名；完整动作选项与状态分开；响应前→报价→响应→响应后，不先展示终局状态。保留偏好生成、teacher平局、私有信息归属和旧belief约束。不提供完成目标列表、收益表或答案推理。','']
 for t in tasks:
  checks.append(verify_task(t));old=request(t,'action_tools',t['name_variant']);new=deepcopy(old)
  new['messages'][1]['content']=render(present(t,t['name_variant']))
  assert new['messages'][0]==old['messages'][0] and new['tools']==old['tools']
  assert new['max_tokens']==1024
  requests.append(dict(task_id=t['id'],condition='chronological_tables',request=new))
  lines+=['## '+t['diagnostic_group'],'','### System','',new['messages'][0]['content'],'','### User','',new['messages'][1]['content'],'','### 本地标签（不发送）','',json.dumps(t['teacher']['gold']),'']
 (out/'tasks.jsonl').write_bytes(source.read_bytes())
 (out/'original_requests.jsonl').write_bytes((source.parent/'original_requests.jsonl').read_bytes())
 (out/'requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests))
 (out/'review.md').write_text('\n'.join(lines))
 audit=dict(review_only=True,model_tested=False,merged=False,tasks_unchanged=True,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),checks=checks,changes=['chronological state presentation','player-indexed goal table','explicit names in preference table','full action catalogue instead of post-response remaining-options list'],limitations='Combined presentation intervention; any future change in behavior cannot be attributed to chronology alone. Remaining action options are derivable from full catalogue and binding state.',files={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','requests.jsonl','original_requests.jsonl']})
 (out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n');print(out)
if __name__=='__main__':main()
