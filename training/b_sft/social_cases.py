"""Small, reviewable social-reasoning cases; construction first, bounded audit second.

The seven coverage tags are NOT seven mandatory gates for every record. Existing
teacher traces retain their explicit policy assumptions. Constructed prefixes are
public interventions, never secretly inverted as teacher-generated evidence.
No rationale targets, probability outputs, or fixed teacher-selected B targets.
"""
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import hashlib
import json
import numpy as np

from training.b_sft.shared_teacher import SharedGame, SharedWindow, native
from training.b_sft.shared_teacher_report import verify_traces
from benac_p.endgame_diagnose import decode_action

CATEGORIES = ('formation', 'maintain', 'update', 'uncertain_planning',
              'information_and_cost', 'long_horizon', 'behavior_constraints')
B_INSTRUCTION = (
    '根据自己的目标、当前局面和公开历史，选择对下一步决策最有用的伙伴偏好进行判断。'
    '自行选择 player 和 goal，可以选择多个；证据不足时保留不确定性。'
    '已公开确定的偏好可直接用于规划，无需作为本次待判断项。'
    '每项输出 player、goal、possible_preferences，以及 favored（或 undetermined）。'
    '不需要输出概率或固定格式的推理步骤。')
P_INSTRUCTION = (
    '根据自己的目标、公开历史和你刚才给出的伙伴判断，选择一个合法行动。'
    '考虑尚未消除的不确定性、剩余机会及行动的后续影响。')


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def b_input(original):
    result = deepcopy(original)
    result.pop('queries', None)
    result['instruction'] = B_INSTRUCTION
    return result


def p_input(context, model_b):
    """Pass actual model beliefs through, with no oracle replacement or repair."""
    result = deepcopy(context)
    result.pop('queries', None)
    result['instruction'] = P_INSTRUCTION
    result['model_beliefs'] = deepcopy(model_b)
    return result


def decision(record, source):
    inp = b_input(record['input'])
    label = record['P']
    return dict(id=source + '-' + key(inp), source=source, input=inp,
                teacher=dict(B_by_target=record['B'], P=label,
                             P_primary_mask=len(label['own_optimal_actions']) < len(label['actions']),
                             P_social_tie_mask=label['prosocial_tie_resolved'],
                             P_acceptable_actions=label['social_optimal_actions'],
                             note='Do not supervise an arbitrary native-order winner when multiple actions tie.'),
                categories=['formation'] if record['B'] else [],
                evidence_after_action=record['evidence_after_action'])


def collect(episodes, source):
    """Deduplicate observations, preserving same-observer temporal pairs."""
    records = {}; pairs = {}
    for episode in episodes:
        previous = {}
        for r in episode['records']:
            d = decision(r, source); records.setdefault(d['id'], d)
            d = records[d['id']]; p = d['input']['player']
            if r['B'] and p in previous:
                before = previous[p]
                old_h = before['input']['history']; h = d['input']['history']
                intervening = [x for x in episode['records']
                               if len(old_h) <= len(x['input']['history']) < len(h)]
                # An own move alone is not a new-partner-evidence maintain pair.
                if any(x['input']['player'] != p for x in intervening):
                    def answers(x):
                        return {(b['player'], b['goal']): b['answer']
                                for b in x['teacher']['B_by_target']}
                    kind = 'maintain' if answers(before) == answers(d) else 'update'
                    pair = dict(before=before['id'], after=d['id'], category=kind)
                    pairs[key(pair)] = pair
                    if kind not in d['categories']: d['categories'].append(kind)
            if r['B']: previous[p] = d
    return list(records.values()), list(pairs.values())


def bundle_fixture(late=False):
    """A bundled refusal is compatible with all three target preferences."""
    requirements = [[(2, 0), (1, 0)], [(2, 1), (1, 0)],
                    [(2, 0), (2, 1), (1, 0)], [(0, 0), (1, 0)]]
    types = {'0': [[1, 0, 0, -1]],
             '1': [[x, -1, -1, 1] for x in (1, 0, -1)], '2': [[1, 0, 0, 0]]}
    ego = 2 if late else 0
    raw = dict(id='deadline-cost' if late else 'bundled-refusal', ego=ego,
               own_preferences=types[str(ego)][0], type_catalogues=types, history=[],
               game=dict(n_players=3, n_actions_per_player=[1, 1, 2],
                         goals=[dict(goal_id=i, binary=True, required_actions=[
                             dict(player_id=p, action_id=a) for p, a in req])
                             for i, req in enumerate(requirements)],
                         round_robin=[0, 1, 2] if late else [1, 2, 0],
                         max_changes=1, menu_enabled=False))
    prefix = [dict(action='OFFER', partner_id=2, proposer_action=[0], partner_action=[1, 0]),
              dict(response='ACCEPT')]
    prefix.append(dict(action='PASS') if late else dict(
        action='OFFER', partner_id=1, proposer_action=[1, 1], partner_action=[1]))
    return raw, prefix


def verify_conditioned(raw, prefix, episodes):
    """Independent native replay, prefix likelihood B, and terminal chosen P checks."""
    rules, worlds, _ = native(raw)
    actual = [tuple(map(tuple, e['environment_world'])) for e in episodes]
    if len(actual) != len(worlds) or set(actual) != set(worlds):
        raise ValueError('Exactly one episode per public world is required')
    from training.b_sft.favored_belief import marginal
    from training.b_sft.social_rollout import queries_for
    queries = {p: queries_for({int(k): v for k, v in raw['type_catalogues'].items()}, p)
               for p in range(raw['game']['n_players'])}
    checks = 0
    for e, world in zip(episodes, actual):
        if e['history'][:len(prefix)] != prefix: raise ValueError('Intervention changed')
        if len(e['records']) != len(e['history']) - len(prefix): raise ValueError('Missing record')
        node = rules.initial()
        for i, action in enumerate(e['history']):
            if i >= len(prefix):
                r = e['records'][i-len(prefix)]; inp = r['input']; p = rules.actor(node)
                if inp['history'] != e['history'][:i] or inp['player'] != p:
                    raise ValueError('Chronology mismatch')
                if inp['public_state'] != node.state.public_state() or tuple(inp['own_preferences']) != world[p]:
                    raise ValueError('State or private observation mismatch')
                if inp['pending_offer'] != (None if node.pending is None else node.pending.to_dict()):
                    raise ValueError('Pending offer mismatch')
                if r['P']['selected'] != action: raise ValueError('Execution mismatch')
                compatible = [j for j, other in enumerate(episodes)
                              if other['history'][:i] == e['history'][:i] and actual[j][p] == world[p]]
                expected = [dict(**q, **marginal(tuple(actual[j] for j in compatible), q['player'], q['goal']))
                            for q in queries[p]]
                if r['B'] != expected: raise ValueError('B differs from whole-world trace likelihood')
                if any(episodes[j]['history'][i] != action for j in compatible):
                    raise ValueError('Same information produced different actions')
                means = np.mean([episodes[j]['utilities'] for j in compatible], axis=0)
                chosen = next(x for x in r['P']['actions'] if x['action'] == action)
                if not r['P']['terminal_value'] or not np.allclose(
                        [chosen['own'], chosen['others']], [means[p], means.sum()-means[p]]):
                    raise ValueError('Chosen P differs from actual terminal outcomes')
                checks += 1
            node = rules._apply(node, decode_action(action))
        if not node.state.is_terminal: raise ValueError('Incomplete outcome')
        if (np.array(world) @ node.state.goal_satisfaction()).tolist() != e['utilities']:
            raise ValueError('Wrong terminal utility')
    return dict(episodes=len(episodes), decisions_checked=checks)


def construct_bundle(late=False):
    raw, prefix = bundle_fixture(late); game = SharedGame(raw, turns=2)
    node = game.rules.initial()
    for a in prefix: node = game.rules._apply(node, decode_action(a))
    tree = SharedWindow(game.rules, node, game.worlds, turns=2, max_nodes=2000, seconds=5).solve()
    episodes = []
    for world in game.worlds:
        position = tree, 0, tuple(range(len(game.worlds))); history = deepcopy(prefix); records = []
        while True:
            t, i, possible = position; entry = t.entries[i]
            if entry.actor is None:
                if not entry.node.state.is_terminal: raise ValueError('Construction must reach real terminal')
                break
            p = entry.actor; own = world[p]
            inp = game.payload(position, p, own, history[:])
            inp['public_setup'] = dict(
                intervention_prefix=prefix,
                semantics='The initial prefix is a publicly fixed scenario setup independent of private types. '
                          'Do not infer preferences from these setup actions. Subsequent actions use the stated common policy.')
            action = t.action(i, own)
            records.append(dict(input=inp, B=game.belief(position, p, own),
                                P=t.labels(i, possible, p, own),
                                evidence_after_action=game.evidence(position, action)))
            history.append(action.to_dict()); position = game.advance(position, action)
        episodes.append(dict(environment_world=world, records=records, history=history,
                             utilities=(np.array(world) @ entry.node.state.goal_satisfaction()).tolist(),
                             status='terminal', prefix_kind='public_intervention'))
    verification = verify_conditioned(raw, prefix, episodes)
    audit = dict(certificate=tree.certificate, independent_check=verification)
    if late:
        # Compare nominated actions; no tree search to discover a scenario.
        names = dict(bundled=dict(action='OFFER', partner_id=1, proposer_action=[1, 1], partner_action=[1]),
                     clean=dict(action='OFFER', partner_id=1, proposer_action=[1, 0], partner_action=[1]))
        comparisons = {}
        for name, action in names.items():
            a = decode_action(action); child = tree.entries[0].children[tree.entries[0].actions.index(a)]
            responses = [tree.action(child, w[1]).to_dict() for w in game.worlds]
            value = tree.values[child][:, raw['ego']].mean()
            comparisons[name] = dict(action=action, responses_by_catalogue_type=responses,
                                     own_terminal_value=float(value),
                                     observable_response_groups=len({key(x) for x in responses}))
        audit['nominated_action_comparison'] = comparisons
    return dict(fixture=raw, prefix=prefix, episodes=episodes, verification=audit)


def long_horizon_case():
    """Construct a delayed-cost cooperation route, audit static bounds, not a search policy."""
    reqs = [[(0, 0), (1, 0)], list(product(range(4), range(2))),
            [(0, 1), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)],
            [(0, 0), (0, 1), (2, 0), (2, 1), (3, 0), (3, 1)]]
    raw = dict(id='delayed-cooperation', ego=0, own_preferences=[-1, 1, 1, 1], history=[],
               type_catalogues={'0': [[-1, 1, 1, 1]], '1': [[1, 1, 1, 0]],
                                '2': [[0, 1, 1, 1]], '3': [[0, 1, x, 1] for x in (1, 0, -1)]},
               game=dict(n_players=4, n_actions_per_player=[2]*4, max_changes=1,
                         round_robin=[0, 1, 2, 3], menu_enabled=False,
                         goals=[dict(goal_id=i, binary=True, required_actions=[dict(player_id=p, action_id=a)
                                for p, a in req]) for i, req in enumerate(reqs)]))
    actions = []
    for partner, row in [(1, [1, 0]), (0, [1, 1]), (3, [1, 0]), (2, [1, 1])]:
        actions.extend([dict(action='OFFER', partner_id=partner, proposer_action=row, partner_action=row),
                        dict(response='ACCEPT')])
    rules, worlds, _ = native(raw); node = rules.initial(); timeline = []
    for action in actions:
        p = rules.actor(node); node = rules._apply(node, decode_action(action))
        timeline.append(dict(actor=p, action=action, turn=node.state.turn_index,
                             commitments=node.state.snapshot_commitments(),
                             completed=node.state.goal_satisfaction().tolist(),
                             own_utility=float(np.dot(raw['own_preferences'], node.state.goal_satisfaction()))))
    if not node.state.is_terminal: raise ValueError('Long route incomplete')
    # Only 256 commitment assignments, not game-tree traversal or behavior labels.
    assignments = np.array(list(product((0, 1), repeat=8))).reshape(-1, 4, 2)
    satisfaction = np.array([[int(all(c[p, a] for p, a in req)) for req in reqs] for c in assignments])
    outcomes = [np.array(w) @ node.state.goal_satisfaction() for w in worlds]
    upper = [(satisfaction @ np.array(w).T).max(axis=0) for w in worlds]
    if not all(np.array_equal(a, b) for a, b in zip(outcomes, upper)):
        raise ValueError('Constructed route must attain every player private-type utility upper bound')
    # After an initial PASS, three offers can add at most six bits in total.
    pass_upper = float((satisfaction[assignments.sum(axis=(1, 2)) <= 6] @ np.array(raw['own_preferences'])).max())
    return dict(fixture=raw, history=actions, timeline=timeline,
                categories=['long_horizon'], status='feasible_payoff_verified_route',
                audit=dict(terminal_utilities=[x.tolist() for x in outcomes],
                           static_utility_upper_bounds=[x.tolist() for x in upper],
                           first_accept_own_utility=-1, terminal_own_utility=2,
                           first_pass_terminal_upper_bound=pass_upper,
                           assignments_checked=len(assignments),
                           scope='Legal full trajectory reaches each player utility upper bound in every private world. '
                                 'PASS bound uses remaining commitment capacity. This is not a verified autonomous partner policy.'),
                B_supervision=False, P_action_ranking_supervision=False,
                limitation='Constructed cooperative continuation. B likelihoods and autonomous continuation after arbitrary LM actions remain unverified; no invented local reward or rationale target.')


def build_pack(source_root, out):
    if out.exists(): raise ValueError('Use a new output directory')
    out.mkdir(parents=True); (out/'games').mkdir()
    candidates = []; links = []; audits = {}; cases = []
    for i in range(1, 5):
        folder = source_root/f'game-{i}'
        raw = json.loads((folder/'result.json').read_text())['fixture']
        eps = [json.loads(p.read_text()) for p in sorted(folder.glob('episode-*.json'))]
        source = f'existing-{i}'; audits[source] = verify_traces(raw, eps)
        (out/'games'/f'{source}.json').write_text(json.dumps(dict(
            fixture=raw, episodes=eps, provenance=str(folder)), ensure_ascii=False)+'\n')
        records, pairs = collect(eps, source); candidates.extend(records); links.extend(pairs)
        cases.append(dict(id=source, provenance=str(folder), categories=sorted({c for r in records for c in r['categories']}),
                          status='existing_teacher_trace_verified'))
    for late in (False, True):
        constructed = construct_bundle(late); source = constructed['fixture']['id']
        (out/'games'/f'{source}.json').write_text(json.dumps(constructed, ensure_ascii=False, indent=2)+'\n')
        audits[source] = constructed['verification']
        records, pairs = collect(constructed['episodes'], source)
        for r in records:
            if r['input']['player'] == constructed['fixture']['ego']:
                r['categories'] += ['uncertain_planning']
                r['categories'] += ['information_and_cost'] if late else ['behavior_constraints', 'maintain']
                r['review_scope'] = ('Negative control: informative and uninformative proposals compete for the last turn; '
                                     'feedback cannot be used for later action.' if late else
                                     'All types strictly reject the bundle. Preserve the prior at the next P decision; '
                                     'the revised offer has terminal own payoffs 1,1,0 across the three hidden types.')
        candidates.extend(records); links.extend(pairs)
        cases.append(dict(id=source, categories=sorted({c for r in records for c in r['categories']}),
                          status='constructed_conditional_subgame_verified'))
    long = long_horizon_case(); (out/'games'/'delayed-cooperation.json').write_text(json.dumps(long, ensure_ascii=False, indent=2)+'\n')
    cases.append(dict(id='delayed-cooperation', categories=['long_horizon'], status=long['status']))
    # Small review selection: one formation observation per old game, two temporal
    # pairs of each kind per source, and all new constructed decisions.
    by_id = {r['id']: r for r in candidates}; chosen = {}
    for source in (f'existing-{i}' for i in range(1, 5)):
        eligible = [r for r in candidates if r['source'] == source and r['teacher']['B_by_target']]
        if eligible: chosen[eligible[0]['id']] = eligible[0]
        for kind in ('maintain', 'update'):
            for pair in [p for p in links if p['category'] == kind and by_id[p['before']]['source'] == source][:2]:
                for k in ('before', 'after'): chosen[pair[k]] = by_id[pair[k]]
    for r in candidates:
        if not r['source'].startswith('existing-'): chosen[r['id']] = r
    selected = list(chosen.values()); selected_links = [p for p in links if p['before'] in chosen and p['after'] in chosen]
    for name, rows in [('decisions.jsonl', selected), ('all_candidates.jsonl', candidates), ('pairs.jsonl', selected_links),
                       ('B_inputs.jsonl', [dict(id=r['id'], input=r['input']) for r in selected if r['teacher']['B_by_target']]),
                       ('P_contexts.jsonl', [dict(id=r['id'], context=dict(r['input'], instruction=P_INSTRUCTION),
                                                belief_source='actual model B output required at runtime') for r in selected])]:
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    summary = dict(cases=cases, selected_decisions=len(selected), candidate_decisions=len(candidates),
                   temporal_pairs=dict(Counter(p['category'] for p in selected_links)),
                   selected_category_counts=dict(Counter(c for r in selected for c in r['categories'])),
                   coverage=dict(formation='verified conditional B labels', maintain='verified, including bundled refusal',
                                 update='verified in existing game 4', uncertain_planning='verified terminal values 1/1/0',
                                 information_and_cost='verified last-turn negative control; positive useful probing still missing',
                                 long_horizon='legal delayed-cost route and utility bounds verified; autonomous partner rollout pending',
                                 behavior_constraints='verified 29-node bundled-refusal construction'),
                   training_ready=False, split='development',
                   limitations=['Conditional policy labels, not unknown-strategy universal truth.',
                                'Teacher lookup covers public hidden catalogue dimensions; self-selected attention usefulness has no unique gold target.',
                                'No rationale supervision. No LM training or existing train/test changes.'])
    summary['P_masks'] = dict(primary=sum(r['teacher']['P_primary_mask'] for r in selected),
                             social_tie=sum(r['teacher']['P_social_tie_mask'] for r in selected))
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    (out/'verification.json').write_text(json.dumps(audits, ensure_ascii=False, indent=2)+'\n')
    write_report(out, summary, selected, selected_links, long)
    (out/'checksums.json').write_text(json.dumps({str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(out.rglob('*')) if p.is_file()}, indent=2)+'\n')
    return summary


def write_report(out, summary, selected, pairs, long):
    lines = ['# 七类社会判断：首批小规模审查包', '',
             '保留形成、维持、更新，不要求每个 B 样本都改变 P。人工构造缺口，再用有限验证检查；不生成理由监督。', '',
             f"四个旧结构 + 两个三人构造情境 + 一个四人长程构造。精选 {len(selected)} 个去重决策点；长程路线单独保存，不冒充已验证的教师轨迹。", '',
             '## 覆盖情况', '', '| 能力 | 当前证据 |', '|---|---|']
    for category, status in summary['coverage'].items(): lines.append(f'| {category} | {status} |')
    lines += ['', '## 从旧对局保留什么', '',
              '| 对局 | 保留用途 | 完整数据 |', '|---|---|---|',
              '| 1：三人、7 goals | 有其他玩家的新 commitment，但对隐藏偏好仍无区分：形成 / 维持 | [游戏 1](games/existing-1.json) |',
              '| 2：四人、6 goals | 两个伙伴各有一个隐藏偏好；合作发生后仍保持不确定性，模型可自行选择关注对象 | [游戏 2](games/existing-2.json) |',
              '| 3：三人、4 goals | 两个伙伴隐藏；PASS 历史不被强行解释为偏好证据，少量普通对照 | [游戏 3](games/existing-3.json) |',
              '| 4：四人、8 goals | P3.G5 从三项收缩到 want/neutral 或 avoid，以及后续维持 | [游戏 4](games/existing-4.json) |',
              '', '这些 B 标签仍条件于各自公开声明的共同伙伴机制；没有换成未知策略下的“普遍真值”。',
              '', '## 新例子 1：拒绝不等于不喜欢', '',
              '三人，commitment 数为 1/1/2，4 个二元 goal。P1 对 G0 为 want/neutral/avoid；对 G1、G2 都是 avoid，对 G3 是 want。P0 喜欢 G0、讨厌 G3。', '',
              '| goal | 完成要求 |', '|---|---|',
              '| G0 | P2.A0、P1.A0 |', '| G1 | P2.A1、P1.A0 |',
              '| G2 | P2.A0、P2.A1、P1.A0 |', '| G3 | P0.A0、P1.A0 |', '',
              '公开设置先令 P2.A0=1，然后 P2 向 P1 提议增加 P2.A1 和 P1.A0。这同时触发 G0/G1/G2。三个隐藏类型都会严格拒绝；喜欢 G0 的类型也会拒绝。', '',
              '下一步 P0 做决策时，B 应保持 G0={want,neutral,avoid}、favored=undetermined。P0 可以只请求 P1.A0，不附加 P2.A1，也不添加自己讨厌的 G3。三种类型下 P0 最终收益为 1/1/0；未知偏好并不意味着无法规划。', '',
              '**前缀是公开构造的固定设置，不是新教师自然生成的历史。**不从设置动作反推偏好；从 P1 对坏报价的响应开始，所有玩家执行同一已验证残局机制。29 个树节点，三个世界全部到终局。', '',
              '[完整规则、轨迹和教师标签](games/bundled-refusal.json)', '',
              '## 新例子 2：没有时间再利用信息', '',
              '保持目标结构，改为 P2 最后一次报价。坏报价所有类型都拒绝：自身收益 0，只有一种响应，不提供区分。干净报价产生 ACCEPT/REJECT 两种响应，预期自身收益 2/3。', '',
              '这里坏报价浪费了最后一次收益机会；干净报价虽然有信息，响应后已经终局，不能额外奖励“获得了可用于后续规划的信息”。这是信息与成本的负对照，不是假称正的信息价值样本。', '',
              '[两种报价的响应与终局价值](games/deadline-cost.json)', '',
              '## 新例子 3：先付代价、之后合作完成', '',
              '四人、每人两个 commitment、每次最多新增一个；四次报价、八次动作。P0 第一次合作后收益降到 −1，经过后续三次合作才升到 2。P3 有一项隐藏偏好。', '',
              '| 已完成报价数 | P0 当前收益 |', '|---|---:|']
    for row in long['timeline']:
        if 'response' in row['action']: lines.append(f"| {row['turn']} | {row['own_utility']} |")
    lines += ['', '所有隐藏类型下，这条路线都达到每个玩家各自的终局收益上界。若首轮 PASS，剩余三次报价最多新增六个 commitment，P0 的终局收益上界只有 1。验证用 256 个静态 commitment 配置核对上界，没有搜索行动树来找路线。', '',
              '**已证实合法、延迟收益和上界；尚未验证一个自主伙伴机制会从所有偏离路径继续执行。**因此它是长程训练情境候选，不输出伪造的 B 标签或全动作排名。', '',
              '[完整长程路线和验证](games/delayed-cooperation.json)', '',
              '## B/P 输入', '', B_INSTRUCTION, '',
              'B_inputs.jsonl 不指定某个教师选中的 player/goal。P_contexts.jsonl 是等待模型 B 的上下文；运行时 p_input(context, model_b) 原样传入模型判断，不把 teacher.B_by_target 填给 P。教师表仅用于评分已选择的隐藏偏好；关注对象是否有用尚无唯一正确目标。', '',
              '构造前缀说明和旧轨迹的教师假设保留在公开输入里。标签、数值、分类、审查说明在教师侧；不作为推理文本目标。', '',
              '## 精选决策索引', '', '| ID | 来源 | 玩家 / 提案轮 | 类别 |', '|---|---|---|---|']
    for r in selected:
        lines.append(f"| {r['id']} | {r['source']} | P{r['input']['player']} / {r['input']['public_state']['turn_index']} | {', '.join(r['categories'])} |")
    lines += ['', f"同一观察者的配对：{dict(Counter(p['category'] for p in pairs))}。形成表示可独立作答的 B 快照；它可以与维持/更新标签重叠。", '',
              '下一项明确缺口：有后续利用机会、值得付出代价的主动信息获取。长程路线还需要接入共同伙伴机制的响应验证。本包是开发审查数据，没有混入旧 SFT 文件，也未开始训练。']
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=Path('new/local_data/shared_teacher_v2'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_pack(args.source_root, args.output_dir), ensure_ascii=False, indent=2))
