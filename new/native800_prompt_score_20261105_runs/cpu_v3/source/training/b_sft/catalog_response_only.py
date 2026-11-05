"""Inventory migrated B/P questions without changing labels or training quotas."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from training.b_sft.decision_policy import optimal_indices

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/social_bp/response_only_v1/tasks.jsonl'
OUT=SOURCE.parent/'catalog'


def classify(t):
    inp=t['input'];game=inp['game'];teacher=t['teacher'];history=inp['voluntary_history']
    state=inp['current_state'];remaining=len(game['round_robin'])-state['turn_index']
    public={(r['player'],r['goal']) for r in inp['public_preferences']}
    hidden=game['n_players']*len(game['goals'])-len(public)
    occurrences=Counter((a['player_id'],a['action_id']) for g in game['goals'] for a in g['required_actions'])
    coupled=any(n>1 for n in occurrences.values())
    record=dict(id=t['id'],previous_task_id=t['previous_task_id'],split=t['split'],task=t['task'],
                family=t['family'],source=t['source'],legacy_stage=t['stage'],legacy_skill=t['skill'],
                players=game['n_players'],goals=len(game['goals']),publicly_hidden_slots=hidden,
                voluntary_events=len(history),remaining_proposal_opportunities=remaining,
                shared_goal_commitments=coupled,training_ready=False)
    tags=[]
    if t['task']=='B':
        if t.get('direct_answer'):ability='直接调查结果读取'
        elif not history:ability='先验约束推断'
        elif all('response' in a for a in history):ability='由接受拒绝反推偏好'
        elif any(a.get('action')=='INVESTIGATE' for a in history):ability='调查选择及后续行为推断'
        else:ability='由主动提案及后续行为反推偏好'
        if len(history)>1:tags.append('累计行为证据')
        if coupled:tags.append('共享承诺与多目标收益')
        gold=teacher['gold'];prior=inp.get('previous_belief')
        if prior:
            record['belief_change']='不变' if prior==gold else ('候选集合变化' if prior['possible_preferences']!=gold['possible_preferences'] else '仅favored变化')
        else:record['belief_change']='无提供旧belief'
        record.update(answer_set_size=len(gold['possible_preferences']),favored=gold['favored'],
                      gold=gold,status='B瓶颈单独处理')
        if len(gold['possible_preferences'])>1 and gold['favored']!='undetermined':tags.append('概率支持强弱')
        if t.get('direct_answer'):difficulty='D0 直接读取'
        elif len(history)<=1 and hidden<=1:difficulty='D1 单步单隐藏偏好'
        elif remaining<=1 and len(history)<=2:difficulty='D2 多候选或组合证据'
        else:difficulty='D3 多步行为与后续计划'
    else:
        ability={'complete':'已知偏好下的收益规划','uncertain':'不确定belief下的收益决策',
                 'result_use':'将私有调查结果用于决策','information':'调查的信息价值与机会成本'}[t['skill']]
        actions=inp['legal_actions'];accepted=teacher['acceptable_actions']
        ids=[actions.index(a) for a in accepted]
        values=np.asarray(teacher['action_values'])
        strict=optimal_indices(values,inp['player'],actions).tolist()
        qualitative='qualitative_certificate' in teacher
        record.update(legal_actions=len(actions),accepted_actions=len(accepted),
                      decision='响应' if inp['pending_offer'] else '提案',
                      label_basis='定性belief区间稳健判分' if qualitative else '当前belief期望收益及0.1容差',
                      accepted_action_kinds=sorted({a.get('action',a.get('response')) for a in accepted}),
                      strict_optimal_count=None if qualitative else len(strict),
                      tolerance_extra_count=None if qualitative else len(set(ids)-set(strict)),
                      status='暂置：所有合法动作可得分' if len(accepted)==len(actions) else 'P待逐项检查')
        if qualitative:tags.append('定性belief区间')
        if t.get('information_positive') is not None:record['legacy_information_positive']=t['information_positive']
        if coupled:tags.append('共享承诺与多目标收益')
        if t['skill']=='information' or remaining>1:difficulty='D3 多步行为与后续计划'
        elif qualitative or hidden>1 or game['n_players']>2:difficulty='D2 多候选或组合证据'
        else:difficulty='D1 单步单隐藏偏好'
    record.update(ability=ability,difficulty=difficulty,tags=tags)
    return record


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(x) for x in SOURCE.read_text().splitlines()]
    assert len(rows)==403 and len({t['id'] for t in rows})==403
    catalog=[classify(t) for t in rows]
    # Validate exact-set reward membership; any accepted action, not just the first.
    from training.b_sft.social_named_probe import present,action_call
    from training.b_sft.social_bp_training import reward
    checked=0
    for t in rows:
        if t['task']!='P':continue
        visible=present(t,t.get('name_variant',0))
        for native in t['teacher']['acceptable_actions']:
            shown=visible['legal_actions'][t['input']['legal_actions'].index(native)]
            name,args=action_call(shown)
            response=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='tool_calls')
            assert reward(t,response)['reward']==1,(t['id'],native)
            checked+=1
    families=defaultdict(set)
    for t in rows:families[t['family']].add(t['split'])
    assert all(len(s)==1 for s in families.values())
    grouped=defaultdict(list)
    for r in catalog:grouped[r['split']+'/'+r['task']+'/'+r['difficulty']+'/'+r['ability']].append(r['id'])
    summary=dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),total=len(rows),
                 kinds=dict(Counter(r['task'] for r in catalog)),
                 split_counts={s:dict(Counter(r['task'] for r in catalog if r['split']==s)) for s in ('train','validation','test')},
                 abilities=dict(Counter(r['ability'] for r in catalog)),
                 difficulties=dict(Counter(r['difficulty'] for r in catalog)),
                 p_multiple_answers=sum(r['task']=='P' and r['accepted_actions']>1 for r in catalog),
                 p_tolerance_extra_tasks=sum(r['task']=='P' and bool(r['tolerance_extra_count']) for r in catalog),
                 deferred_p=sum(r['status'].startswith('暂置') for r in catalog),
                 accepted_actions_scored_correct=checked,family_split_disjoint=True,
                 note='Structural difficulty heuristic, not measured model difficulty. Preserve every source row; no sampling, relabelling or training enablement.')
    (OUT/'catalog.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in catalog))
    (OUT/'groups.json').write_text(json.dumps(grouped,ensure_ascii=False,indent=2)+'\n')
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    lines=['# 403题整理：response-only altruism','',
           '本次仅整理，未修改题面、标签、划分或训练配额。8道solver循环题不在403题中；403题中的8道全动作得分P题保留并单独暂置，不补题或求解。B推理瓶颈单独处理。', '',
           '难度是结构启发式，不是模型实测：D0直接读取；D1单步单隐藏偏好；D2多候选、组合证据或定性belief；D3信息价值/后续计划/多步行为。共享承诺、多目标求和等复杂性另设标签，不能把同一D级解释为同等难度。旧stage/skill保留用于追溯。','',
           '| 划分 | B | P | 合计 |','| --- | ---: | ---: | ---: |']
    for split,c in summary['split_counts'].items():lines.append(f"| {split} | {c.get('B',0)} | {c.get('P',0)} | {sum(c.values())} |")
    lines+=['','| 推理能力 | 题数 |','| --- | ---: |']
    for ability,n in summary['abilities'].items():lines.append(f'| {ability} | {n} |')
    lines+=['','| 结构难度 | 题数 |','| --- | ---: |']
    for d,n in sorted(summary['difficulties'].items()):lines.append(f'| {d} | {n} |')
    lines+=['',f"P共184题，其中{summary['p_multiple_answers']}题允许多个答案；逐一提交528个可接受动作，全部获得二元reward=1。184题当前全部是提案决策，没有P响应题。",
            f"非定性P中{summary['p_tolerance_extra_tasks']}题包含严格最优之外的容差答案。定性P使用整个belief区间的稳健判定，不用单个prior的期望值冒充标签依据。",
            '', 'P按acceptable_actions集合判分，不只认第一个示范答案。提案自身收益最优并列可任选；响应自身收益并列后仍比较他人收益。残余并列的任意单次选择均可判对，不检验跨样本是否均匀。P目前保留0.1容差，和teacher求解的严格最优规则有区别。B必须提交完整候选集合及正确favored，不能任选一个可能偏好。',
            '', '逐题分类见catalog.jsonl；按split/任务/结构难度/能力索引见groups.json。所有403题仍training_ready=False，未接入正式训练。']
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
