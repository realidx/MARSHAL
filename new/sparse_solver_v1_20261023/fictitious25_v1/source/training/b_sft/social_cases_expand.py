"""Expand curated cases with useful feedback, compensating benefits and delay.

Small authored goal structures, bounded same-policy verification, full legal
continuations. No changes to the old teacher algorithm or existing training data.
"""
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import hashlib
import json
import shutil
import numpy as np

from training.b_sft.social_cases import (
    P_INSTRUCTION, bundle_fixture, collect, decision, key, verify_conditioned,
)
from training.b_sft.shared_teacher import SharedGame, SharedWindow, native
from benac_p.endgame_diagnose import decode_action


def information_fixture(mode='two_types'):
    if mode not in ('two_types', 'independent', 'multi_partner', 'wait_for_better'):
        raise ValueError('Unknown information case')
    reqs = [[(0, 0), (1, 0)], [(1, 0), (2, 1)], [(0, 1), (2, 0)],
            [(1, 0), (0, 1)], [(1, 0), (0, 1), (2, 0)], [(0, 0), (2, 1)]]
    own = [1, 1, 1, -1, -1, 0]
    p1 = [[x, x, -1, 1, -1, 1] for x in (1, -1)]
    p2 = [[-1, 1, 1, 1, 0, 0]]
    if mode in ('independent', 'multi_partner'):
        p1 = [[x, y, -1, 1, -1, 1] for x in (1, 0, -1) for y in (1, 0, -1)]
    if mode == 'multi_partner': p2 = [[x, 1, 1, 1, 0, 0] for x in (1, 0, -1)]
    if mode == 'wait_for_better':
        p1 = [[x, x, 1, 0, 0, 1] for x in (1, -1)]
        p2 = [[0, 0, 1, 0, 0, 0]]
    raw = dict(id='information-'+mode, ego=0, own_preferences=own, history=[],
               type_catalogues={'0': [own], '1': p1, '2': p2},
               game=dict(n_players=3, n_actions_per_player=[2, 1, 2], max_changes=1,
                         round_robin=[2, 1, 0, 0, 2, 1], menu_enabled=False,
                         goals=[dict(goal_id=i, binary=True, required_actions=[dict(player_id=p, action_id=a)
                                for p, a in req]) for i, req in enumerate(reqs)]))
    prefix = [dict(action='OFFER', partner_id=0, proposer_action=[0, 1], partner_action=[1, 0]),
              dict(response='ACCEPT'), dict(action='PASS'), dict(action='PASS')]
    if mode == 'wait_for_better': prefix.append(probe_action())
    return raw, prefix


def probe_action():
    return dict(action='OFFER', partner_id=1, proposer_action=[1, 0], partner_action=[1])


def compensated_fixture():
    raw, prefix = bundle_fixture()
    raw['id'] = 'compensated-acceptance'
    raw['type_catalogues']['1'] = [[x, 1, 1, 1] for x in (1, 0, -1)]
    return raw, prefix


def solve_conditioned(raw, prefix, turns=3):
    game = SharedGame(raw, turns=turns); node = game.rules.initial()
    for action in prefix: node = game.rules._apply(node, decode_action(action))
    tree = SharedWindow(game.rules, node, game.worlds, turns=turns,
                        max_nodes=5000, max_sweeps=16, seconds=10).solve()
    if tree.end != len(raw['game']['round_robin']):
        raise ValueError('Only full-to-terminal labels are exported by this expansion')
    episodes = []
    for world in game.worlds:
        pos = tree, 0, tuple(range(len(game.worlds))); history = deepcopy(prefix); records = []
        while tree.entries[pos[1]].actor is not None:
            _, i, possible = pos; entry = tree.entries[i]; player = entry.actor; own = world[player]
            inp = game.payload(pos, player, own, history[:])
            inp['public_setup'] = dict(intervention_prefix=prefix, semantics=(
                'This initial public scenario setup is fixed independently of private preferences. '
                'Infer preferences only from subsequent common-policy actions, not from setup choices.'))
            action = tree.action(i, own)
            records.append(dict(input=inp, B=game.belief(pos, player, own),
                                P=tree.labels(i, possible, player, own),
                                evidence_after_action=game.evidence(pos, action)))
            history.append(action.to_dict()); pos = game.advance(pos, action)
        end = tree.entries[pos[1]].node
        if not end.state.is_terminal: raise ValueError('Incomplete continuation')
        episodes.append(dict(environment_world=world, history=history, records=records,
                             utilities=(np.array(world) @ end.state.goal_satisfaction()).tolist(),
                             status='terminal', prefix_kind='public_intervention'))
    checked = verify_conditioned(raw, prefix, episodes)
    # Independently execute each forced first action followed by the fixed
    # contingent policy. Do not trust cached Q values for the premium comparison.
    counterfactuals = []
    root = tree.entries[0]; actor = root.actor
    for ai, action in enumerate(root.actions):
        payoffs = []
        for world in game.worlds:
            index = root.children[ai]; actual_node = game.rules._apply(node, action)
            while tree.entries[index].actor is not None:
                entry = tree.entries[index]
                chosen = tree.action(index, world[entry.actor])
                actual_node = game.rules._apply(actual_node, chosen)
                index = entry.children[entry.actions.index(chosen)]
            if not actual_node.state.is_terminal: raise ValueError('Counterfactual did not finish')
            payoffs.append((np.array(world) @ actual_node.state.goal_satisfaction()).tolist())
        for own in dict.fromkeys(w[actor] for w in game.worlds):
            ids = [i for i, w in enumerate(game.worlds) if w[actor] == own]
            means = np.array(payoffs)[ids].mean(axis=0)
            label = tree.labels(0, tuple(range(len(game.worlds))), actor, own)['actions'][ai]
            if not np.allclose([label['own'], label['others']], [means[actor], means.sum()-means[actor]]):
                raise ValueError('Counterfactual Q differs from direct native policy execution')
        counterfactuals.append(dict(action=action.to_dict(), terminal_payoffs_by_world=payoffs))
    return dict(fixture=raw, prefix=prefix, episodes=episodes,
                verification=dict(certificate=tree.certificate, independent_check=checked,
                                  root_counterfactuals=counterfactuals,
                                  counterfactual_scope='Forced first action, then the same frozen common policy. '
                                                      'No re-solving or oracle private-truth action choice.'))


def information_audit(case):
    eps = case['episodes']; root = eps[0]['records'][0]['P']
    action = probe_action()
    probe = next(a for a in root['actions'] if a['action'] == action)
    others = [a['own'] for a in root['actions'] if a['action'] != action]
    # Independent root return: every world follows the selected same-info action.
    if any(e['records'][0]['P']['selected'] != action for e in eps):
        raise ValueError('Information attempt is not selected in every compatible world')
    actual = float(np.mean([e['utilities'][0] for e in eps]))
    if abs(actual-probe['own']) > 1e-9: raise ValueError('Root expectation differs from full actual continuations')
    if probe['own'] <= max(others)+1e-9: raise ValueError('Missing useful-feedback action premium')
    response_groups = {}
    for e in eps:
        response = e['records'][1]['P']['selected']
        response_groups.setdefault(key(response), []).append(e)
    if len(response_groups) < 2: raise ValueError('Feedback does not discriminate')
    branches = []
    for es in response_groups.values():
        observer = next((r for r in es[0]['records'][2:] if r['input']['player'] == 0), None)
        branches.append(dict(response=es[0]['records'][1]['P']['selected'], worlds=len(es),
                             own_outcomes=[e['utilities'][0] for e in es],
                             next_ego_decision=None if observer is None else dict(
                                 history=observer['input']['history'], B=observer['B'], action=observer['P']['selected'])))
    return dict(probe_terminal_value=actual, best_other_first_action_value=max(others),
                policy_contingent_premium=actual-max(others), branches=branches,
                scope='Combined payoff of trying cooperation, observing its response, and following the common continuation. '
                      'The offer also changes commitments; this premium is NOT isolated pure information value.')


def second_long_route():
    all_bits = list(product(range(3), range(3)))
    reqs = [[(0, 0), (1, 0)], all_bits,
            [x for x in all_bits if x != (1, 0)], [x for x in all_bits if x != (2, 0)]]
    raw = dict(id='three-player-delayed-cooperation', ego=0, own_preferences=[-1, 1, 1, 1], history=[],
               type_catalogues={'0': [[-1, 1, 1, 1]], '1': [[1, 1, 1, 0]],
                                '2': [[0, 1, x, 1] for x in (1, 0, -1)]},
               game=dict(n_players=3, n_actions_per_player=[3]*3, max_changes=1,
                         round_robin=[0, 1, 2, 0, 1, 2], menu_enabled=False,
                         goals=[dict(goal_id=i, binary=True, required_actions=[dict(player_id=p, action_id=a)
                                for p, a in req]) for i, req in enumerate(reqs)]))
    offers = [(1, [1, 0, 0], [1, 0, 0]), (2, [1, 1, 0], [1, 0, 0]),
              (0, [1, 1, 0], [1, 1, 0]), (1, [1, 1, 1], [1, 1, 1]),
              (2, [1, 1, 1], [1, 1, 1])]
    history = []
    for partner, own, other in offers:
        history.extend([dict(action='OFFER', partner_id=partner, proposer_action=own, partner_action=other),
                        dict(response='ACCEPT')])
    history.append(dict(action='PASS'))
    rules, worlds, _ = native(raw); node = rules.initial(); timeline = []
    for action in history:
        p = rules.actor(node); node = rules._apply(node, decode_action(action))
        timeline.append(dict(actor=p, action=action, turn=node.state.turn_index,
                             commitments=node.state.snapshot_commitments(),
                             own_utility=float(np.dot(raw['own_preferences'], node.state.goal_satisfaction()))))
    if not node.state.is_terminal: raise ValueError('Incomplete delayed route')
    assignments = np.array(list(product((0, 1), repeat=9))).reshape(-1, 3, 3)
    sat = np.array([[int(all(c[p, a] for p, a in req)) for req in reqs] for c in assignments])
    utility = [np.array(w) @ node.state.goal_satisfaction() for w in worlds]
    upper = [(sat @ np.array(w).T).max(axis=0) for w in worlds]
    if any(not np.array_equal(x, y) for x, y in zip(utility, upper)):
        raise ValueError('Delayed route does not attain all players bounds')
    wasted_upper = float((sat[assignments.sum(axis=(1, 2)) <= 8] @ np.array(raw['own_preferences'])).max())
    if wasted_upper >= utility[0][0]: raise ValueError('Missing missed-opportunity contrast')
    return dict(fixture=raw, history=history, timeline=timeline, categories=['long_horizon'],
                status='feasible_payoff_verified_route', B_supervision=False, P_action_ranking_supervision=False,
                audit=dict(terminal_utilities=[u.tolist() for u in utility],
                           static_utility_upper_bounds=[u.tolist() for u in upper],
                           first_two_passes_terminal_upper_bound=wasted_upper, assignments_checked=512,
                           substantive_proposal_turns=5, total_proposal_turns=6),
                limitation='Five productive negotiations, not six steps of claimed reasoning: the final PASS is bookkeeping. '
                           'Only route legality and static payoff/capacity bounds verified; autonomous continuation remains pending.')


def annotated_records(case, source, kind):
    records, pairs = collect(case['episodes'], source)
    by_id = {r['id']: r for r in records}; residual_ids = set()
    # An exact deterministic likelihood can be fragile to arbitrary action order.
    # Flag such histories and do not treat them as clean local B supervision.
    for e in case['episodes']:
        fragile = False
        for original in e['records']:
            rid = decision(original, source)['id']
            if fragile: residual_ids.add(rid)
            fragile |= original['evidence_after_action']['exclusion_reasons']['residual_native_order'] > 0
    for rid, r in by_id.items():
        r['teacher']['B_aux_mask'] = bool(r['teacher']['B_by_target']) and rid not in residual_ids
        r['teacher']['residual_order_evidence_in_prefix'] = rid in residual_ids
        if kind == 'information' and r['input']['player'] == 0:
            r['categories'].append('information_and_cost')
        if r['teacher']['B_by_target'] and r['teacher']['P_primary_mask'] and any(
                len(b['answer']['possible_preferences']) > 1 for b in r['teacher']['B_by_target']):
            r['categories'].append('uncertain_planning')
        if kind == 'constraints' and r['input']['player'] == 0:
            r['categories'] += ['behavior_constraints', 'maintain']
        r['categories'] = sorted(set(r['categories']))
    return records, pairs


def select_case(records, pairs, limit):
    """Keep useful temporal endpoints, then diversify belief answers and actions."""
    by_id = {r['id']: r for r in records}; chosen = {}
    for kind in ('update', 'maintain'):
        for pair in [p for p in pairs if p['category'] == kind][:2]:
            if len(set(chosen) | {pair['before'], pair['after']}) <= limit:
                for k in ('before', 'after'): chosen[pair[k]] = by_id[pair[k]]
    def features(r):
        bs = r['teacher']['B_by_target']; p = r['teacher']['P']
        return {('actor', r['input']['player']), ('turn', r['input']['public_state']['turn_index']),
                ('action', json.dumps(p['selected'], sort_keys=True)),
                ('belief', json.dumps([(b['player'], b['goal'], b['answer']) for b in bs], sort_keys=True)),
                ('masks', r['teacher']['P_primary_mask'], r['teacher']['P_social_tie_mask'])}
    seen = set().union(*(features(r) for r in chosen.values())) if chosen else set()
    rest = [r for r in records if r['id'] not in chosen]
    while rest and len(chosen) < limit:
        # Retain contrasting own-type responses too; do not make B the only gate.
        r = max(rest, key=lambda x: (len(features(x)-seen), bool(x['teacher']['B_by_target']),
                                    x['teacher']['P_primary_mask']))
        chosen[r['id']] = r; seen.update(features(r)); rest.remove(r)
    return list(chosen.values())


def expand(source, out):
    if out.exists(): raise ValueError('Use a new output directory')
    # Verify source integrity before carrying previous material forward.
    for name, expected in json.loads((source/'checksums.json').read_text()).items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source checksum mismatch: '+name)
    out.mkdir(parents=True); shutil.copytree(source/'games', out/'games')
    shutil.copyfile(source/'REVIEW.md', out/'PREVIOUS_REVIEW.md')
    read = lambda name: [json.loads(s) for s in (source/name).read_text().splitlines()]
    selected = read('decisions.jsonl'); candidates = read('all_candidates.jsonl'); pairs = read('pairs.jsonl')
    original = json.loads((source/'summary.json').read_text()); cases = original['cases']
    checks = json.loads((source/'verification.json').read_text()); additions = []
    families = {f'existing-{i}': f'existing-{i}' for i in range(1, 5)}
    families.update({'bundled-refusal': 'bundle', 'deadline-cost': 'bundle', 'delayed-cooperation': 'long-four'})
    for mode, limit in [('two_types', 12), ('independent', 14), ('multi_partner', 20), ('wait_for_better', 10)]:
        raw, prefix = information_fixture(mode); case = solve_conditioned(raw, prefix)
        if mode != 'wait_for_better': case['feedback_audit'] = information_audit(case)
        kind = 'constraints' if mode == 'wait_for_better' else 'information'
        name = raw['id']; records, links = annotated_records(case, name, kind)
        keep = select_case(records, links, limit)
        additions.append(dict(id=name, candidate_decisions=len(records), selected_decisions=len(keep),
                              worlds=len(case['episodes']), nodes=case['verification']['certificate']['nodes'],
                              feedback_audit=case.get('feedback_audit')))
        selected.extend(keep); candidates.extend(records); pairs.extend(links); checks[name] = case['verification']
        cases.append(dict(id=name, status='constructed_conditional_subgame_verified'))
        families[name] = 'feedback-opportunity'
        (out/'games'/f'{name}.json').write_text(json.dumps(case, ensure_ascii=False)+'\n')
    raw, prefix = compensated_fixture(); case = solve_conditioned(raw, prefix, turns=2)
    name = raw['id']; records, links = annotated_records(case, name, 'constraints')
    selected.extend(records); candidates.extend(records); pairs.extend(links); checks[name] = case['verification']
    cases.append(dict(id=name, status='constructed_conditional_subgame_verified')); families[name] = 'bundle'
    additions.append(dict(id=name, candidate_decisions=len(records), selected_decisions=len(records), worlds=3,
                          nodes=case['verification']['certificate']['nodes']))
    (out/'games'/f'{name}.json').write_text(json.dumps(case, ensure_ascii=False)+'\n')
    long = second_long_route(); name = long['fixture']['id']; families[name] = 'long-three'
    cases.append(dict(id=name, status=long['status']))
    (out/'games'/f'{name}.json').write_text(json.dumps(long, ensure_ascii=False, indent=2)+'\n')
    by_id = {r['id']: r for r in selected}
    if len(by_id) != len(selected): raise ValueError('Duplicate selected observation')
    pairs = list({key(p): p for p in pairs if p['before'] in by_id and p['after'] in by_id}.values())
    for rows in (selected, candidates):
        for r in rows:
            r['split_group'] = families[r['source']]
            r['teacher'].setdefault('B_aux_mask', bool(r['teacher']['B_by_target']))
            r['teacher'].setdefault('residual_order_evidence_in_prefix', False)
    for c in cases:
        c['split_group'] = families[c['id']]
        c['selected_decisions'] = sum(r['source'] == c['id'] for r in selected)
    summary = dict(selected_decisions=len(selected), candidate_decisions=len(candidates),
                   cases=cases, split_groups=len(set(families.values())),
                   decision_split_groups=len({r['split_group'] for r in selected}), additions=additions,
                   verified_teacher_episodes=sum(v.get('independent_check', v)['episodes'] for v in checks.values()),
                   temporal_pairs=dict(Counter(p['category'] for p in pairs)),
                   selected_category_counts=dict(Counter(c for r in selected for c in r['categories'])),
                   residual_order_flagged_B=sum(bool(r['teacher']['B_by_target']) and r['teacher'].get(
                       'residual_order_evidence_in_prefix', False) for r in selected),
                   long_routes=2, training_ready=False, split='development',
                   limits=['Related preference, scheduling and deadline variants share one split group.',
                           'Positive premium is useful cooperative attempt plus feedback, not isolated pure information value.',
                           'Full old and new conditional teacher trajectories verified; long authored routes still await autonomous partner validation.',
                           'No independent held-out generalization set created in this development expansion.'])
    for name, rows in [('decisions.jsonl', selected), ('all_candidates.jsonl', candidates), ('pairs.jsonl', pairs),
                       ('B_inputs.jsonl', [dict(id=r['id'], input=r['input']) for r in selected if r['teacher']['B_by_target']]),
                       ('P_contexts.jsonl', [dict(id=r['id'], context=dict(r['input'], instruction=P_INSTRUCTION),
                                                belief_source='actual model B output required at runtime') for r in selected])]:
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    (out/'verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2)+'\n')
    report(out, summary, selected)
    (out/'checksums.json').write_text(json.dumps({str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(out.rglob('*')) if p.is_file()}, indent=2)+'\n')
    return summary


def report(out, summary, selected):
    lines = ['# 社会判断样本：第二批补充', '',
             f"当前 {summary['selected_decisions']} 个精选决策点，来自 {summary['decision_split_groups']} 个分组；另有两组长程合作路线，共 {summary['split_groups']} 组材料。偏好和时限变体不算独立游戏结构。", '',
             '[首批例子与规则](PREVIOUS_REVIEW.md) · [完整统计](summary.json) · [独立验证](verification.json)', '',
             '## 新正例：先尝试合作，再根据反馈使用备用方案', '',
             '三人，commitment 数 2/1/2，6 个二元目标。当前 P0.A0 和 P2.A1 已公开承诺。P0 喜欢 G0/G1/G2，讨厌 G3/G4。', '',
             '| goal | 要求 | P1 偏好 | P2 偏好 |', '|---|---|---|---|',
             '| G0 | P0.A0、P1.A0 | 隐藏 x | avoid |',
             '| G1 | P1.A0、P2.A1 | 隐藏 x | want |',
             '| G2 | P0.A1、P2.A0 | avoid | want |',
             '| G3 | P1.A0、P0.A1 | want | want |',
             '| G4 | P1.A0、P0.A1、P2.A0 | avoid | neutral |',
             '| G5 | P0.A0、P2.A1 | want | neutral |', '',
             '最简单版本公开目录中 x 只有 want/avoid，G0/G1 同向；这是显式目录约束，不是让教师偷看两项真值。', '',
             'P0 先请求 P1.A0，自己保持 [1,0]。喜欢的类型接受，完成 G0/G1，P0 收益 2。讨厌的类型拒绝，P0 的判断更新；随后 P2 提出备用合作，P0 接受，完成 G2，收益 1。两种响应的类型排除都来自严格自身价值差异。', '',
             '| 首步策略 | 共同机制下的预期终局收益 |', '|---|---:|',
             '| 先向 P1 尝试合作，再按反馈继续 | 1.5 |', '| 其他任一首步动作 | 1.0 |', '',
             '这是有后续利用机会的合作尝试；成功时直接实现目标，失败时利用反馈切换伙伴。**0.5 是这套行动与反馈组合的收益优势，不是剥离 commitment 效果后的纯信息价值。**没有额外加“获得信息就给分”的奖励。', '',
             '[两类型完整实例](games/information-two_types.json)', '',
             '## 放开隐藏信息后的两个变体', '',
             '- [两项偏好独立隐藏](games/information-independent.json)：P1.G0/G1 各取三种偏好，9 个组合；不再依赖同向约束。',
             '- [两个伙伴隐藏](games/information-multi_partner.json)：再隐藏 P2.G0，27 个组合。B 仍自行选择关注对象，教师查表覆盖全部隐藏维度。', '',
             '| 版本 | 世界数 | 合作尝试的预期收益 | 其他首步最高收益 |', '|---|---:|---:|---:|']
    for item in summary['additions']:
        if item.get('feedback_audit'):
            a = item['feedback_audit']; lines.append(f"| {item['id']} | {item['worlds']} | {a['probe_terminal_value']:.4f} | {a['best_other_first_action_value']:.4f} |")
    lines += ['', '三个版本都是同一目标结构的难度变体，不能拆到训练和测试两边。每个验证树 1,835 节点，窗口一直到真正终局；全部隐藏世界的执行结果独立核对。所有首步反事实也以固定共同策略逐动作重放到终局，核对缓存价值。', '',
              '## 两种新的行为约束', '',
              '**接受不等于喜欢其中每个目标。**在原先捆绑报价结构中，改为附带两个正面目标，即使伙伴讨厌 G0，也会因为整体收益为正而接受。观察到接受后仍保留三种 G0 偏好。', '',
              '[补偿性接受](games/compensated-acceptance.json)', '',
              '**拒绝眼前正收益，也可能是在保留更好的后续机会。**在同一信息机会结构中改变公开偏好配置，喜欢 G0/G1 的伙伴仍拒绝眼前报价，以便后面获得更多目标收益。不要直接将拒绝解释成 avoid。', '',
              '[等待更好机会](games/information-wait_for_better.json)', '',
              '## 第二条延迟收益路线', '',
              '三人每人 3 个 commitment，五次实质合作后才实现收益；完整原生游戏有六个提案轮，最后一个 PASS 只是结束流程。P0 的已实现收益在前四次合作后都为 −1，第五次升至 2。', '',
              '三个隐藏类型下均达到各玩家终局效用上界。如果前两次机会都 PASS，剩余新增 commitment 容量不足，P0 的终局收益上界降到 1。512 个静态配置核对该界，不展开游戏行动树。', '',
              '[三人长程路线](games/three-player-delayed-cooperation.json)', '',
              '两条长程路线仍只有合法性、收益与机会约束证据；尚未假称共同自主伙伴已经实现这些路线，因此不输出伪造的 B/P 局部标签。', '',
              '## 样本、输入与边界', '',
              f"精选配对：{summary['temporal_pairs']}。分类允许重叠，普通形成/维持样本继续保留。", '',
              f"本轮精选中 {summary['residual_order_flagged_B']} 个带 B 的记录受到历史原生同分排序证据标记；其 B_aux_mask 关闭，不能将这种收缩当成干净的局部监督。", '',
              'B_inputs.jsonl 不给定教师挑选的目标，P_contexts.jsonl 必须注入真实模型 B。审查说明、真实世界和数值均留在教师侧。没有理由监督、没有修改训练入口或旧训练/测试数据。', '',
              '本轮全部是 development。还需要为泛化检查单独准备新结构，以及验证长程路线的自主伙伴响应。', '',
              '## 精选索引', '', '| ID | 组 | 玩家 / 提案轮 | 类别 |', '|---|---|---|---|']
    for r in selected:
        lines.append(f"| {r['id']} | {r['split_group']} | P{r['input']['player']} / {r['input']['public_state']['turn_index']} | {', '.join(r['categories'])} |")
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', type=Path, default=Path('new/local_data/social_cases_v1'))
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    result = expand(args.source_root, args.output_dir)
    print(json.dumps({k: v for k, v in result.items() if k not in ('cases', 'additions')}, ensure_ascii=False, indent=2))
