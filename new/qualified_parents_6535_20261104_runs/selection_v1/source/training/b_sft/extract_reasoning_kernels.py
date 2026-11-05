"""Describe reasoning contracts and assign current instances; no relabelling."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/social_bp/response_only_v1/tasks.jsonl'
OUT=SOURCE.parent/'kernels_v1'
KERNELS={
 'B1':dict(name='从一次响应反推偏好',chain='各候选偏好→接受/拒绝的终局收益→响应策略→用观察到的响应筛选并更新支持',contrast='相同ACCEPT/REJECT在不同收益条件下需要给出不同belief；包括应该排除和应保留全集',invariant='保留两种响应的收益排序、信息集、先验和响应似然关系'),
 'B2':dict(name='从主动提案反推偏好',chain='各候选偏好→可选提案/PASS/调查的后续自身收益→最优动作集合→观察提案的似然→belief',contrast='同样提出某承诺，有时排除某偏好，有时不能排除；替代行动的收益决定信息量',invariant='保留全部相关备选动作的自身收益排序及最优集合；提案并列不能用利他筛选'),
 'B3':dict(name='连续行为证据更新',chain='第一条行为形成posterior→在该posterior及各方信息下解释后一条行为→累计更新',contrast='后一条证据改变集合/只改变favored/完全不变；不能重置到初始先验或重复计证据',invariant='保留行动顺序、条件似然和私有信息归属'),
 'P1':dict(name='已知偏好下选择行动',chain='各合法动作及对方响应→终局完成情况→自身净收益→任选可接受最优动作',contrast='有益提案/避免损失/PASS；单目标有利但总收益不利；多个同收益动作均可接受',invariant='保留相关承诺组合、对方响应和收益排序；公开信息或私有结果来源不另算内核'),
 'P2':dict(name='概率belief下选择行动',chain='供给的当前belief→各情形的后续结果→期望自身收益→选择行动',contrast='相同可行偏好集合但权重不同导致选择变化；存在未知不代表必须调查',invariant='保留联合belief和条件行动价值；不能擅自假设边缘独立'),
 'P3':dict(name='定性belief下的稳健行动',chain='likely等供给判断→允许的不确定范围→比较跨范围稳健行动',contrast='同一场景改变置信程度；有稳定行动与无稳定行动的区别',invariant='保留定性词的显式审计包络和联合支持；不偷换为某个精确概率'),
 'P4':dict(name='调查的信息价值与机会成本',chain='直接行动收益 vs 花掉当前机会调查后的最优后续收益→是否调查及调查对象',contrast='调查严格有益/无益或有害/收益并列；有后续使用机会与最后一次机会',invariant='保留剩余顺序、结果私有性、答案能否影响后续行动及调查费用'),
 'A0':dict(name='辅助：直接结果读取',chain='读取本人合法获知的调查结果→提交该偏好',contrast='结果属于自己/他人；want/neutral/avoid',invariant='保留信息可见性；不算行为推理内核')}
BLOCKS={
 'M1':dict(name='承诺后果与总收益',operation='对各目标做ALL_OF判断，再求所有完成目标的收益和',variants=['目标不完成','单目标完成','共享承诺完成多个目标','正负收益抵消']),
 'M2':dict(name='仅响应阶段的利他平局',operation='自身收益并列时，仅ACCEPT/REJECT比较他人总收益；残余并列均匀随机',variants=['帮助他人→接受','损害他人→拒绝','双方都并列→随机','提案阶段不能套用此规则']),
 'M3':dict(name='候选兼容性与行动似然',operation='prior×行动条件似然→posterior；possible是正支持集合，favored是唯一最高支持',variants=['严格排除','所有候选仍可能','集合不变但权重变化','最高支持并列']),
 'M4':dict(name='信息与证据归属',operation='区别imposed与voluntary、本人私有结果与他人结果；只条件化可用证据',variants=['固定setup不提供行为证据','公开自主动作提供证据','私有结果不直接共享','上一轮posterior不能重置'])}


def assign(t):
    inp=t['input'];history=inp['voluntary_history'];teacher=t['teacher']
    if t['task']=='B':
        if t.get('direct_answer'):key='A0'
        elif len(history)>1:key='B3'
        elif len(history)==1 and 'response' in history[0]:key='B1'
        elif len(history)==1 and history[0].get('action')=='OFFER':key='B2'
        else:raise ValueError('Unclassified B history '+t['id'])
    elif t['skill']=='information':key='P4'
    elif 'qualitative_certificate' in teacher:key='P3'
    elif inp.get('supplied_belief',{}).get('unresolved_preferences'):key='P2'
    else:key='P1'
    r=dict(id=t['id'],previous_task_id=t['previous_task_id'],split=t['split'],family=t['family'],
           kernel=key,kernel_name=KERNELS[key]['name'],legacy_skill=t['skill'],legacy_stage=t['stage'],
           information_source='private_result' if inp['private_results'] else 'public_and_behavior',
           source=t['source'],contrast_group=t.get('contrast_group'),
           deferred=bool(teacher.get('all_legal_accepted')),training_ready=False)
    r['shared_blocks']=['M4'] if key=='A0' else (['M1','M2','M3','M4'] if key.startswith('B') else ['M1','M2','M4'])
    r['block_assignment_note']='Blocks needed to evaluate the rule correctly; a block need not change the answer in every instance. No claim of causally minimal tasks.'
    if t['task']=='B':
        gold=teacher['gold'];prior=inp.get('previous_belief')
        r.update(observed_actions=[a.get('action',a.get('response')) for a in history],
                 possible=gold['possible_preferences'],favored=gold['favored'],
                 supplied_previous=prior is not None,
                 update_result='not_supplied' if prior is None else 'unchanged' if prior==gold else 'set_changed' if set(prior['possible_preferences'])!=set(gold['possible_preferences']) else 'favored_only')
        cert=teacher.get('response_certificate')
        r['independent_response_microstructure']=None
        if cert:
            from fractions import Fraction
            records=cert['world_checks']
            r['independent_response_microstructure']=dict(
                own_tie_present=any(w['payoffs']['ACCEPT'][1]==w['payoffs']['REJECT'][1] for w in records),
                social_breaks_own_tie=any(w['payoffs']['ACCEPT'][1]==w['payoffs']['REJECT'][1] and w['payoffs']['ACCEPT'][0]!=w['payoffs']['REJECT'][0] for w in records),
                randomized_response=any(0<Fraction(p)<1 for w in records for p in w['response_likelihood'].values()),
                multiple_goals_completed=sum(cert['completed_goals']['ACCEPT'])>1)
    else:
        r.update(acceptable_actions=len(teacher['acceptable_actions']),legal_actions=len(inp['legal_actions']),
                 acceptable_kinds=sorted({a.get('action',a.get('response')) for a in teacher['acceptable_actions']}),
                 unresolved_preferences=len(inp.get('supplied_belief',{}).get('unresolved_preferences',[])))
        if key=='P4':
            margin=teacher['own_query_margin'];r['query_value_relation']='better' if margin>1e-9 else 'worse' if margin < -1e-9 else 'tied'
            r['query_own_margin']=margin
    return r


def main():
    rows=[json.loads(x) for x in SOURCE.read_text().splitlines()]
    assignments=[assign(t) for t in rows];assert len(assignments)==403
    grouped=defaultdict(list)
    for r in assignments:grouped[r['kernel']].append(r)
    summaries={k:dict(count=len(v),splits=dict(Counter(r['split'] for r in v)),
                     legacy_skills=dict(Counter(r['legacy_skill'] for r in v)),
                     deferred=sum(r['deferred'] for r in v),
                     representative_train_id=next((r['id'] for r in v if r['split']=='train'),None)) for k,v in grouped.items()}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'assignments.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in assignments))
    artifact=dict(version='reasoning-kernels-v1',source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  task_kernels=KERNELS,shared_operations=BLOCKS,summary=summaries,
                  coverage_status='Contracts and structural assignment only. Existing controlled-pair completeness and causal minimality are not certified. No new samples or model calls.')
    (OUT/'kernels.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    lines=['# B/P推理内核：第一版','',
           '范围：当前403题，保持原train/validation/test。7类推理任务内核＋1类直接读取辅助题。每题一个主归属，同时由共享运算组成；不是7种互不重叠的认知能力。此步不调整配额、不改标签、不处理暂置P，也不解决B rollout瓶颈。','',
           '## 主内核与现有覆盖','', '| 内核 | 推理问题 | Train | Validation | Test | 合计 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for k,definition in KERNELS.items():
        s=summaries[k];c=s['splits'];lines.append(f"| {k} | {definition['name']} | {c.get('train',0)} | {c.get('validation',0)} | {c.get('test',0)} | {s['count']} |")
    for k,d in KERNELS.items():
        lines+=['',f"## {k}：{d['name']}",'',d['chain']+'。','', '**需要的对照关系：**'+d['contrast']+'。', '', '**同内核变体必须保持：**'+d['invariant']+'。']
    lines+=['','## 共享运算块','']
    for k,b in BLOCKS.items():lines += [f"- **{k} {b['name']}**：{b['operation']}。对照轴：{'；'.join(b['variants'])}。"]
    lines+=['','## 需要纠正的旧分类','',
            '- formation/update/maintain不是三个独立内核：同一个逆推问题可以给旧belief或不给，也可以恰好得到“维持”的结论。它们保留为题目属性。',
            '- 48道result_use中41道归P1，7道归P2：私有结果的来源本身不产生一种新的收益规划内核。信息可见性由M4检查。',
            '- 净收益抵消、利他、冲突不是按故事再分三个大题库：它们是M1/M2的不同对照条件，应嵌入主内核成组出现。',
            '- B3明确复用B1/B2，但多了累计条件化，因此单列组合内核。P3复用P2的belief决策，但标签依据是整个定性区间，因此单列，防止把它当精确概率题。',
            '- D等级、玩家/目标数量、名字、公开或私有来源都是属性，不能据其数量宣称内核覆盖丰富。',
            '', '## 已经看出的覆盖边界','',
            '- B3的29题目前都是OFFER→ACCEPT；未覆盖OFFER→REJECT、多个提案周期或更长的独立证据序列。',
            '- 184道P都是主动提案决策，包含调查选项；没有单独训练模型回应offer的P题。B中的响应推断不能替代P执行响应。此处只记录缺口，不补题。',
            '- P4共40题：按重新计算的最佳调查与最佳非调查自身收益，5题调查更好、27题更差、8题并列。并列并不等于“调查反例”；这8题与先前全动作得分的8题不是同一分类。',
            '- 现有36道B有独立最终响应证书，可直接标记自身平局、他人收益破平局、随机响应、多个目标完成；其余题没有自动声称是哪种最小微机制。',
            '- 8道全动作得分P保留deferred标记；8道solver循环P不在403题中。本轮均不处理。4道直接读取B只列辅助项，不据此决定训练配额。',
            '', '## 下一步边界','',
            '当前完成的是内核定义及逐题结构归属，不是最小教学题或完整对照组的认证。后续应逐个内核选代表题、验证哪些条件是真正必要的、检查控制变量对照是否完整，再决定保留及变体数量。不能仅靠一个自动标签就宣布题目有同一因果内核。',
            '', '机器可读定义、计数和train代表ID在kernels.json；403题的归属、原ID、证据形态和暂置状态在assignments.jsonl。未改动源数据。']
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
