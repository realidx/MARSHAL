"""Compact proposal-inference and self-response maintenance controls, CPU only."""
from collections import Counter
from copy import copy
import hashlib,json
from pathlib import Path
import numpy as np
from training.b_sft.debug.audit_readable_pretraining import reconstruct,independent_backward,VALUES
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.social_named_probe import request

ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/'examples/social_bp/response_only_v1'
OUT=BASE/'kernels_v1/b2_b3/core_v1'
B2={
 'strict_want':'7d6a70b356e39b20f3ac',
 'strict_avoid':'9397a0c49ddb9ec0197d',
 'alternative_favors_avoid':'f8348fabafd994b7a4f5',
 'alternative_favors_want':'3be65e09e3476ccbe7df',
 'joint_alternative_want':'06bd789fa7da0e346473',
 'joint_alternative_avoid':'39dc67d4c6321a30b292',
 'no_information':'576cc463db80d2e135ee',
 'full_set_but_favored':'5e0715550406c882029d'}
B3={
 'retain_singleton':'7a519adc803c7f849b61',
 'retain_two_favored':'b37ed8a919467985827e',
 'retain_full_undetermined':'62d04e7f67c35539701c',
 'retain_full_favored':'c799fe2d16baf7ec798c'}

def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def check(t,cache):
 inp=t['input'];raw,own=reconstruct(inp);key=stable([raw,inp['imposed_setup']])
 if key not in cache:
  root=PrivateEpisode(raw,inp['imposed_setup'],seconds=30,max_nodes=100000)
  cache[key]=(root,audit_native(root.tree),independent_backward(root.tree))
 root,native,independent=cache[key];e=copy(root);e.events=[];q=inp['queries'][0]
 facts=[(f['player'],f['goal'],VALUES[f['preference']]) for f in inp['private_results']]
 assert e.tree.certificate['policy_sha256']==t['teacher']['policy_sha256']
 trace=[]
 for action in inp['voluntary_history']:
  entry=e.tree.entries[e.index];before=e._weights(inp['observer'],own,facts)
  prior=e.belief(q['player'],q['goal'],observer=inp['observer'],own=own,private_results=facts)
  ai=[a.to_dict() for a in entry.actions].index(action)
  likelihood=e.tree.policy[e.index][ai]
  support=np.flatnonzero(before>0)
  trace.append(dict(actor=entry.actor,observer_action=entry.actor==inp['observer'],action=action,
                    prior=prior,min_likelihood=float(likelihood[support].min()),max_likelihood=float(likelihood[support].max())))
  e.observe(action)
  after=e._weights(inp['observer'],own,facts)
  trace[-1]['joint_posterior_unchanged']=bool(np.allclose(before,after,atol=1e-9,rtol=0))
  trace[-1]['posterior']=e.belief(q['player'],q['goal'],observer=inp['observer'],own=own,private_results=facts)
 gold={k:trace[-1]['posterior'][k] for k in ('possible_preferences','favored')}
 assert gold==t['teacher']['gold'],t['id']
 np.testing.assert_allclose([trace[-1]['posterior']['preference_weights'][v] for v in VALUES],
                            [t['teacher']['preference_weights'][v] for v in VALUES],atol=1e-9)
 if 'previous_belief' in inp:
  previous={k:trace[-1]['prior'][k] for k in ('possible_preferences','favored')}
  assert previous==inp['previous_belief'],t['id']
 assert e.tree.entries[e.index].node.state.public_state()==inp['current_state']
 # All root alternatives matter, not only the observed offer. Export likelihoods
 # averaged using the observer's prior, not omniscient realized preferences.
 root_weights=root._weights(inp['observer'],own,facts);alternatives=[]
 for ai,a in enumerate(root.tree.entries[0].actions):
  by_pref={}
  for name,v in VALUES.items():
   mask=np.array([w[q['player']][q['goal']]==v for w in root.tree.worlds]);mass=root_weights[mask].sum()
   by_pref[name]=float(np.dot(root_weights[mask],root.tree.policy[0][ai,mask])/mass) if mass else None
  alternatives.append(dict(action=a.to_dict(),likelihood_by_queried_preference=by_pref))
 return dict(id=t['id'],split=t['split'],root_group=hashlib.sha256(key.encode()).hexdigest(),
             native=native,independent_backward=independent,trace=trace,root_alternatives=alternatives)


def main():
 payload=(BASE/'tasks.jsonl').read_bytes();bank={t['id']:t for t in map(json.loads,payload.splitlines())}
 assignment={r['id']:r for r in map(json.loads,(BASE/'kernels_v1/assignments.jsonl').read_text().splitlines())}
 target=[t for t in bank.values() if assignment[t['id']]['kernel'] in ('B2','B3')]
 cache={};checks={t['id']:check(t,cache) for t in target}
 for t in target:
  if assignment[t['id']]['kernel']=='B3':
   last=checks[t['id']]['trace'][-1]
   assert last['observer_action'] and last['joint_posterior_unchanged']
 selected=set(B2.values())|set(B3.values())
 assert len(selected)==12 and all(bank[i]['split']=='train' for i in selected)
 assert all(assignment[i]['kernel']=='B2' for i in B2.values())
 assert all(assignment[i]['kernel']=='B3' for i in B3.values())
 # Two genuine same-root comparisons; other representatives are not falsely
 # described as a complete controlled pair or all possible proposal coverage.
 pairs=[('alternative_favors_avoid','alternative_favors_want'),('joint_alternative_want','joint_alternative_avoid')]
 for a,b in pairs:
  assert checks[B2[a]]['root_group']==checks[B2[b]]['root_group']
  assert bank[B2[a]]['teacher']['gold']!=bank[B2[b]]['teacher']['gold']
 held=[t for t in target if t['split']!='train'];reserve=[t for t in target if t['split']=='train' and t['id'] not in selected]
 assert len(held)==32 and len(reserve)==36
 assert not {bank[i]['family'] for i in selected}&{t['family'] for t in held}
 OUT.mkdir(parents=True,exist_ok=True);files={}
 def write(name,rows):
  data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(data)
  files[name]=dict(count=len(rows),sha256=hashlib.sha256(data).hexdigest())
 write('b2_train_tasks.jsonl',[bank[i] for i in B2.values()]);write('b3_maintenance_tasks.jsonl',[bank[i] for i in B3.values()])
 write('reserve_tasks.jsonl',reserve);write('heldout_tasks.jsonl',held);write('audit.jsonl',checks.values())
 reqs=[];cards=[]
 for kind,spec in [('B2',B2),('B3-maintenance',B3)]:
  for role,i in spec.items():
   t=bank[i];req=request(t,'action_tools',t.get('name_variant',0));assert req['max_tokens']==1024
   reqs.append(dict(task_id=i,kernel=kind,role=role,request=req))
   cards += [f'## {kind} / {role}', '',f'ID: {i}','', '### 模型题面','',req['messages'][1]['content'],'','### 本地审核，不发送给模型','',
              json.dumps(dict(gold=t['teacher']['gold'],trace=checks[i]['trace'],alternatives=checks[i]['root_alternatives']),ensure_ascii=False),'']
 write('requests.jsonl',reqs)
 b1=json.loads((BASE/'kernels_v1/b1/core_v1/manifest.json').read_text())
 b1_ids={t['id'] for t in map(json.loads,(BASE/'kernels_v1/b1/core_v1/train_tasks.jsonl').read_text().splitlines())}
 retained=b1_ids|selected
 candidate=[t for t in bank.values() if t['task']!='B' or t['split']!='train' or t['id'] in retained]
 assert len(candidate)==279 and sum(t['task']=='B' and t['split']=='train' for t in candidate)==28
 write('bp_candidate_tasks.jsonl',candidate)
 write('selection.jsonl',[dict(id=t['id'],kernel=assignment[t['id']]['kernel'],split=t['split'],
   role='core_train' if t['id'] in B2.values() else 'maintenance_control' if t['id'] in B3.values() else 'heldout_unchanged' if t['split']!='train' else 'reserve_train') for t in target])
 summary=dict(version='b2-b3-core-v1',source_sha256=hashlib.sha256(payload).hexdigest(),
  B2=dict(original_train=29,core_train=8,reserve=21,validation_unchanged=13,test_unchanged=9),
  B3=dict(original_train=19,maintenance_controls=4,reserve=15,validation_unchanged=5,test_unchanged=5,
          substantive_sequential_update_examples=0,all_29_joint_posteriors_unchanged=True),
  B_train_total_after_b1_b2_b3=28,candidate_total=279,checks=len(checks),
  independent_backward=sum(c['independent_backward'] for c in checks.values()),
  roles=dict(B2=B2,B3=B3),paired_B2=pairs,files=files,training_ready=False,merged=False,model_tested=False)
 (OUT/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 (OUT/'cards.md').write_text('# B2和B3保留题：题面与独立审核区\n\n'+'\n'.join(cards))
 report='''# B2/B3实际精简

| 数据 | 原train | 保留 | 备用 | validation/test |
| --- | ---: | ---: | ---: | --- |
| B2 主动提案逆推 | 29 | 8 | 21 | 13/9，保持不动 |
| B3 自己响应后的belief维持 | 19 | 4 | 15 | 5/5，保持不动 |

## B2保留内容

- 严格区分want与avoid的两道代表题；来自不同场景，不冒充单变量配对。
- 同一场景两个不同提案分别支持want/neutral与neutral/avoid：2题。
- 较复杂联合情形中的同场景替代提案：2题。
- 主动提案没有信息，保留原belief：1题。
- 全集不缩小但favored改变：1题。

两组同场景替代提案已核对root一致、标签不同。没有声称这8题覆盖所有合法提案，也没有为每个PASS/INVESTIGATE分支补题。动作似然审核考虑所有合法备选行动，主动提案并列不使用利他筛选。当前不修改题面；有旧belief/无旧belief属性保留，不能把差异算成独立推理内核。

## B3的重要纠正

现有29题全部是别人OFFER→观察者自己ACCEPT。逐题检查的不仅是possible/favored，而是完整联合posterior：自己的响应前后全部不变。它们是“不要把自己的行动当成他人偏好的新证据”的维持对照，不是29个真正累计新证据的推理场景。

只保留4种代表：单值、二值且favored、全集undetermined、全集且favored。它们属于同一个维持内核的答案形态对照，不能再次计为4种独立能力。剩余15道train备用。真正的多条外部行为证据导致集合或权重变化，当前仍是缺口，本轮不新造题。

## 验证与文件

80题重新求解，核对策略hash、原生状态/收益、前后belief、gold和posterior；适用时另作独立backward对照，适用数量见manifest。B2的完整根节点备选行动似然、B3前后联合posterior是否相同的检查见audit.jsonl。研究者的审核信息与模型题面分离。

b2_train_tasks.jsonl为8题核心；b3_maintenance_tasks.jsonl为4题维持对照；reserve_tasks.jsonl为36题备用；heldout_tasks.jsonl保留32题原划分。cards.md给出完整题面及标签；selection.jsonl给出逐题去向。

叠加B1的16题，B训练核心从152题缩为28题。bp_candidate_tasks.jsonl为实际合并的279题候选库：28道B train、67道B heldout、184道P。P完全保留，包括之前暂置的8题，不在本轮处理。原403题库不改写；未切换采样器、未设置权重、未启用训练或模型测试。对新核心不能宣称已具有完整B3训练信号。
'''
 (OUT/'review.md').write_text(report)
 assert hashlib.sha256((BASE/'tasks.jsonl').read_bytes()).hexdigest()==summary['source_sha256']
 print(json.dumps({k:summary[k] for k in ('B2','B3','B_train_total_after_b1_b2_b3','candidate_total','checks','independent_backward')},ensure_ascii=False))

if __name__=='__main__':main()
