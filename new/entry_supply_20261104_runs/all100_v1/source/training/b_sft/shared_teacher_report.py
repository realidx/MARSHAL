"""Independent all-world trace checks and human-readable shared-teacher report."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import numpy as np

from training.b_sft.shared_teacher import native,specification,VERSION
from benac_p.endgame_diagnose import decode_action


def verify_traces(raw,episodes):
    rules,worlds,types=native(raw)
    actual=[tuple(tuple(row) for row in e['environment_world']) for e in episodes]
    if set(actual)!=set(worlds) or len(actual)!=len(worlds):raise ValueError('Need exactly one full trajectory for each joint world')
    rebuilt=[];labels={1:'want',0:'neutral',-1:'avoid'};b_checks=0;p_checks=0
    for e,world in zip(episodes,actual):
        node=rules.initial();prefix_states=[node]
        if len(e['records'])!=len(e['history']):raise ValueError('Missing acting-player record')
        for i,(a,r) in enumerate(zip(e['history'],e['records'])):
            inp=r['input'];p=rules.actor(node)
            if inp['history']!=e['history'][:i] or inp['player']!=p or tuple(inp['own_preferences'])!=world[p]:raise ValueError('Observation chronology/own type mismatch')
            if inp['public_state']!=node.state.public_state():raise ValueError('Public state mismatch')
            if inp['pending_offer']!=(None if node.pending is None else node.pending.to_dict()):raise ValueError('Pending offer mismatch')
            if r['P']['selected']!=a:raise ValueError('Selected action did not execute')
            node=rules._apply(node,decode_action(a));prefix_states.append(node)
        if not node.state.is_terminal:raise ValueError('Incomplete trace is not an outcome')
        if (np.array(world)@node.state.goal_satisfaction()).tolist()!=e['utilities']:raise ValueError('Terminal utility mismatch')
        rebuilt.append(prefix_states)
    for e in episodes:
        for r in e['records']:
            inp=r['input'];p=inp['player'];h=inp['history'];own=tuple(inp['own_preferences'])
            compatible=[j for j,(other,w) in enumerate(zip(episodes,actual)) if other['history'][:len(h)]==h and w[p]==own]
            if not compatible:raise ValueError('Empty independently reconstructed information set')
            expected_queries=[dict(player=other,goal=g) for other in sorted(types) if other!=p for g in range(len(types[other][0])) if len({row[g] for row in types[other]})>1]
            if inp['queries']!=expected_queries or len(r['B'])!=len(expected_queries):raise ValueError('Incomplete public query schedule')
            for q,b in zip(expected_queries,r['B']):
                if (b['player'],b['goal'])!=(q['player'],q['goal']):raise ValueError('B query mismatch')
                counts=Counter(labels[actual[j][q['player']][q['goal']]] for j in compatible)
                support=[labels[x] for x in (1,0,-1) if labels[x] in counts];rank=counts.most_common()
                favored=rank[0][0] if len(rank)==1 or rank[0][1]>1.25*rank[1][1] else 'undetermined'
                if b['answer']!=dict(possible_preferences=support,favored=favored):raise ValueError('B fails independent whole-trajectory likelihood check')
                b_checks+=1
            scores=[]
            for j in compatible:
                if episodes[j]['history'][len(h)]!=r['P']['selected']:raise ValueError('Same information produced a different action')
                end=next(n for n in rebuilt[j][len(h)+1:] if n.state.turn_index>=r['window_end'])
                scores.append(np.array(actual[j])@end.state.goal_satisfaction())
            mean=np.array(scores).mean(axis=0);chosen=next(x for x in r['P']['actions'] if x['action']==r['P']['selected'])
            if abs(chosen['own']-mean[p])>1e-9 or abs(chosen['others']-(mean.sum()-mean[p]))>1e-9:
                raise ValueError('P prediction differs from actual same-policy window execution')
            p_checks+=1
    return dict(episodes=len(episodes),B_queries_checked=b_checks,P_chosen_predictions_checked=p_checks,
        method='Reconstruct each information set by prefix-matching independently completed full-world trajectories; compare B and actual window-end expected utilities. Counterfactual actions additionally rely on solver certificates and small exhaustive regression tests.')


def report(root):
    summaries=[];checks={};example=None
    for i in range(1,5):
        d=root/f'game-{i}';result=json.loads((d/'result.json').read_text());raw=result['fixture']
        eps=[json.loads(f.read_text()) for f in sorted(d.glob('episode-*.json'))]
        checked=verify_traces(raw,eps);checks[str(i)]=checked
        unique={}
        for e in eps:
            for r in e['records']:unique.setdefault(json.dumps(r['input'],sort_keys=True),r)
        informative=[r for r in unique.values() if r['evidence_after_action']['public_worlds_after']<r['evidence_after_action']['public_worlds_before']]
        summary=dict(game=i,id=result['id'],old_history=result['old_history']['status'],seconds=result['seconds'],
            worlds=len(eps),unique_actor_observations=len(unique),windows=result['windows'],max_nodes=max(x['nodes'] for x in result['certificates']),
            max_sweeps=max(x['sweeps'] for x in result['certificates']),
            prosocial_ties=sum(r['P']['prosocial_tie_resolved'] for r in unique.values()),
            residual_ties=sum(r['P']['residual_tie'] for r in unique.values()),
            informative_observations=len(informative),
            residual_order_information=sum(r['evidence_after_action']['exclusion_reasons']['residual_native_order']>0 for r in informative),
            terminal_utilities=[e['utilities'] for e in eps])
        summaries.append(summary)
        if i==4:
            example=next(r for r in unique.values() if r['P']['prosocial_tie_resolved'] and len(r['P']['actions'])==2)
    horizons={}
    for i in (2,3):
        d=root/f'horizon3-game-{i}'
        if not (d/'result.json').exists():continue
        r=json.loads((d/'result.json').read_text());eps=[json.loads(f.read_text()) for f in sorted(d.glob('episode-*.json'))]
        horizons[str(i)]=dict(verification=verify_traces(r['fixture'],eps),seconds=r['seconds'],
            utilities=[e['utilities'] for e in eps],window_proposal_turns=3)
    (root/'horizon_verification.json').write_text(json.dumps(horizons,indent=2)+'\n')
    (root/'verification.json').write_text(json.dumps(checks,indent=2)+'\n')
    (root/'example.json').write_text(json.dumps(example,indent=2)+'\n')
    data=dict(teacher=specification(),games=summaries,complete=True,training_ready=False,
        scope='Teacher mechanism validation only. Window values are not full-game optimal values. No LM training/transfer claim.')
    (root/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    lines=['# 同机制社会推理教师：四局复验','',
        '机制说明见 [README.md](../../../training/b_sft/README.md#teacher-and-supervision)。所有玩家使用同一有限窗口策略。先最大化自己的预期窗口收益，同分时最大化其他玩家预期收益合计。所有数值与证书都是教师侧信息。','',
        '| 游戏 | 隐藏世界组合 | 全部到终局 | 最大窗口树节点 | 旧前缀 | 新轨迹中的偏好区分 |','|---|---:|---|---:|---|---|']
    for s in summaries:
        lines.append(f"| {s['game']} | {s['worlds']} | 是 | {s['max_nodes']} | {s['old_history']} | {'有' if s['informative_observations'] else '未观察到'} |")
    lines+=['','四局均从原游戏开局重新运行，没有缩减 commitment、修改目标或沿用旧标签。旧前缀不符合新策略的情况明确报 incompatible，不是把它们强行解释为新教师的数据。','',
        '[独立验证明细](verification.json) · [机制与统计](summary.json) · [第四局真实决策例子](example.json)','',
        '独立验证用全部隐藏世界的完整轨迹重建每个行动者的信息集，核对 B 标签，以及实际执行到窗口末端的条件期望是否与 P 的预测一致。','',
        '## 第四局例子','',
        'P0 的 B：P3.G5 ∈ {want, neutral}，favored=undetermined。面对报价：','',
        '| 动作 | 自身预期窗口收益 | 其他玩家预期窗口收益合计 |','|---|---:|---:|',
        '| REJECT | 1 | 2 |','| ACCEPT | 1 | 3.5 |','',
        '因此选择 ACCEPT：没有牺牲自身收益，次级目标有严格改善。这里仍有偏好不确定性，没有用隐藏真值替代预期。','',
        '## 边界','',
        '- 默认两轮公共规划窗口，并在窗口内执行固定策略；窗口外继续同一规则重新求解。非终局窗口评分不是整局最优 Q。',
        '- 各窗口通过私有类型条件下的完整单方最佳响应检查，并要求策略表稳定；general-sum 并不保证总能找到这样的纯策略解，失败时不出标签。',
        '- 帮助其他玩家是本研究选定的同分规则，不是 general-sum 的定义。自身与其他玩家收益都同分时仍存在原生排序约定。',
        '- 第四局的已观察偏好收缩没有排除仅由残余原生排序区分的世界；这只适用于本次轨迹，不能推广到所有游戏。',
        '- 前三局的新自然轨迹未区分所隐藏偏好；不能继续沿用旧的“高价值”标签。第三局全 PASS，说明通过计算检查也不等于形成了丰富的训练样本。',
        '- 尚未证明严格匹配状态的 B→P 必要行动切换、主动探测净收益、或 LM 可学会/迁移。']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    (root/'checksums.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and p.name!='checksums.json'},indent=2)+'\n')
    return data


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();report(a.root)
