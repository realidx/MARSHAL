"""Freeze the reviewed request route and close P4 acquisition/use coverage."""
import hashlib
import json
from pathlib import Path
from training.b_sft.social_named_probe import request
from training.b_sft import review_prompt
from training.social_mixed import policy_prompt
from training.social_mixed.core import Episode
ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'examples/social_mixed/current_train_probe_v2'
SOURCES=['training/b_sft/decision_policy.py','training/social_mixed/frozen/bp_display.py','training/b_sft/review_prompt.py','training/b_sft/social_prompt.py','training/b_sft/social_named_probe.py','training/social_mixed/policy_prompt.py','training/social_mixed/frozen/selfplay_prompt.py']
def digest(data):return hashlib.sha256(data).hexdigest()
def read(p):return [json.loads(x) for x in p.read_text().splitlines()]
def main():
 PACK.mkdir(exist_ok=True)
 old=read(ROOT/'examples/social_mixed/current_train_probe_v1/bp.jsonl')
 p4=ROOT/'examples/social_bp/p4_information_core_v1'
 # Preserve the other kernels to enable a same-task prompt comparison.
 rows=[t for t in old if t['probe_kernel']!='P4']
 for diagnostic,name in [(False,'train_tasks.jsonl'),(True,'diagnostic_tasks.jsonl')]:
  for t in read(p4/name):
   t.update(probe_kernel='P4',probe_completion=t['completion_mode'],probe_diagnostic_only=diagnostic)
   rows.append(t)
 data=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows).encode();(PACK/'bp.jsonl').write_bytes(data)
 requests=[dict(task_id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in rows]
 reqdata=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests).encode();(PACK/'requests.jsonl').write_bytes(reqdata)
 links=read(p4/'acquisition_use_links.jsonl');ids={t['id'] for t in rows}
 assert all({r['parent'],*r['children']}<=ids for r in links)
 (PACK/'p4_links.json').write_text(json.dumps(links,indent=2)+'\n')
 resets=read(ROOT/'examples/social_mixed/selfplay_audit_v2/probe_resets.jsonl');resets=[r for r in resets if r['split']=='train']
 sp=[dict(reset_id=r['id'],request=Episode(r,r['id'],0,20260916).request()) for r in resets]
 (PACK/'selfplay_initial_requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in sp))
 m=dict(version='current-train-probe-v2',bp_prompt=review_prompt.VERSION,selfplay_prompt=policy_prompt.VERSION,
   bp_tasks=len(rows),training_core_tasks=len(rows)-1,diagnostic_tasks=1,bp_repeats=8,bp_sha256=digest(data),requests_sha256=digest(reqdata),
   source_sha256={n:digest((ROOT/n).read_bytes()) for n in SOURCES},selfplay_train_resets=len(resets),selfplay_repeats=4,
   selection='Keep previous non-P4 tasks; include all 15 P4 core tasks plus one separately marked all-legal diagnostic. No model-dependent selection.',
   label_contract_review_required=['B favored under simplified policy and unspecified prior', 'P initial-prior belief after removing draw probabilities'],
   p4_core=15,p4_acquisition=10,p4_result_use=5,p4_diagnostic_result_use=1,model_tested=False)
 (PACK/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
 cards=['# B/P实际请求审阅稿','以下就是实际请求的system和user内容；标签未进入请求。完整工具定义见requests.jsonl。','']
 for t,r in zip(rows,requests):
  cards += [f'## {t["probe_kernel"]} / {t["id"]} / {t["probe_completion"]}'+(' / diagnostic only' if t.get('probe_diagnostic_only') else ''),'']
  cards += [msg['role'].upper()+'\n\n'+msg['content']+'\n' for msg in r['request']['messages']]
 (PACK/'bp_review.md').write_text('\n'.join(cards))
 cards=['# Self-play实际初始请求审阅稿','']
 for r in sp:
  cards += [f'## {r["reset_id"]}','']+[msg['role'].upper()+'\n\n'+msg['content']+'\n' for msg in r['request']['messages']]
 (PACK/'selfplay_review.md').write_text('\n'.join(cards))
 print(json.dumps(m,indent=2))
if __name__=='__main__':main()
