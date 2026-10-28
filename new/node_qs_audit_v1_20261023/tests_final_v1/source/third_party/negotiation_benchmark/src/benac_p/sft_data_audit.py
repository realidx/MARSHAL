"""Generate a replayable development-only corpus, not a held-out benchmark.

No model calls, training, approximate oracle labels, or diagnostic opportunity
gates. Each source game is saved, including failures. Run with --help.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import random
import time

import numpy as np

from benac_p.diagnose_protocol import submission_tool
from benac_p.endgame import Endgame, Node, SearchLimit
from benac_p.endgame_diagnose import SYSTEM, decode_action, render_action
from benac_p.endgame_partner import RationalPartner, transcript_actions
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.schema import MenuOffer, OfferProposal, PassProposal, ResponseAction


VERSION = 'bp-sft-development-audit-v1'
LABELS = {1: 'want', 0: 'neutral', -1: 'avoid'}
OPTIONS = ['want', 'neutral', 'avoid']
SYSTEM_SFT = SYSTEM.replace(
    'Briefly reason about the requested partner judgment or native action, then submit the requested tool call.',
    'You may reason briefly or submit directly. Submit exactly one requested tool call, with no text after it.'
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def rng_for(*keys):
    return random.Random(int(digest(keys), 16))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def write_jsonl(path, rows):
    path.write_text(''.join(canonical(row) + '\n' for row in rows))


def action_kind(action):
    if isinstance(action, ResponseAction):
        return action.value
    if isinstance(action, PassProposal):
        return 'PASS'
    return 'MENU' if isinstance(action.offer, MenuOffer) else 'OFFER'


def choose_by_kind(actions, rng):
    groups = defaultdict(list)
    for action in actions:
        groups[action_kind(action)].append(action)
    return rng.choice(groups[rng.choice(sorted(groups))])


def topology_hash(spec):
    """Ignore player/action/goal labels, retain public requirement structure."""
    candidates = []
    for players in permutations(range(spec.n_players)):
        for actions in product(*(list(permutations(range(k))) for k in spec.n_actions_per_player)):
            edges = sorted(tuple(sorted((players[a.player_id], actions[a.player_id][a.action_id])
                                        for a in g.required_actions)) for g in spec.goals)
            candidates.append(canonical(edges))
    return digest(min(candidates))


def independent_q(search, node, budget=10000):
    """Uncached information-set recursion; does not call value/q_values/advance.

    Shares the game transition and declared partner kernel, so this validates
    ego search/branch accounting, NOT an independent proof of partner optimality.
    """
    count = 0

    def utility(n):
        commitments = n.state.snapshot_commitments()
        return sum(v for v, g in zip(search.own, search.spec.goals)
                   if all(commitments[a.player_id][a.action_id] for a in g.required_actions))

    def value(n):
        nonlocal count
        count += 1
        if count > budget:
            raise SearchLimit('Independent verification node budget exceeded.')
        actor = search.actor(n)
        if actor is None:
            return Fraction(utility(n))
        if actor == search.ego:
            return max(value(search._apply(n, a)) for a in search.actions(n))
        groups = defaultdict(list)
        for world in n.worlds:
            groups[search._partner_action(n, world)].append(world)
        return sum(Fraction(len(worlds), len(n.worlds)) * value(
            search._apply(Node(n.state, tuple(worlds), n.pending), action))
            for action, worlds in groups.items())

    return [(a, float(value(search._apply(node, a)))) for a in search.actions(node)], count


class Audit:
    def __init__(self, seed, max_nodes=20000, max_remaining=3, branch_roots=1):
        self.seed, self.max_nodes, self.max_remaining = seed, max_nodes, max_remaining
        self.branch_roots = branch_roots
        self.spec = replace(generate_game(seed, GeneratorConfig(
            n_players=3, actions_per_player=2, n_goals=8, n_rounds=2)), menu_enabled=True)
        self.rows = [tuple(map(int, row)) for row in self.spec.private_preferences]
        self.ego = seed % 3
        # Target and query selection use no learner performance or action values.
        choices = [(p, g) for p in range(3) if p != self.ego for g in range(8)
                   if any(v == 1 for j, v in enumerate(self.rows[p]) if j != g)
                   and any(self.rows[q][g] != 0 for q in range(3) if q != p)]
        if not choices:
            raise ValueError('No query with all three valid independent candidate types.')
        self.target, self.goal = rng_for(seed, 'query').choice(choices)
        self.types = {p: (row,) for p, row in enumerate(self.rows)}
        self.types[self.target] = tuple(tuple(v if j == self.goal else old for j, old in enumerate(
            self.rows[self.target])) for v in (1, 0, -1))
        self.partner = RationalPartner(self.spec, self.types, self.ego, max_nodes)
        self.search = Endgame(self.spec, self.ego, self.rows[self.ego],
                              {p: r for p, r in self.types.items() if p != self.ego}, self.partner,
                              max_nodes=max_nodes, max_remaining_turns=max_remaining)
        self.samples, self.cases, self.failures, self.trajectories, self.interventions = {}, {}, [], [], []
        self.independent_checked = False
        self.role = dict(you_control=f'P{self.ego}', partner_under_assessment=f'P{self.target}',
                         assessed_goals=[f'G{self.goal}'])

    def public(self):
        return dict(
            n_players=3, n_actions_per_player=[2, 2, 2], max_changes=1,
            goals={f'G{g.goal_id}': ' AND '.join(f'P{a.player_id}.A{a.action_id}' for a in g.required_actions)
                   for g in self.spec.goals}, round_robin=list(self.spec.round_robin), ego=f'P{self.ego}',
            ego_preferences=dict(player=f'P{self.ego}', by_goal={f'G{g}': LABELS[v]
                                 for g, v in enumerate(self.rows[self.ego])}),
            type_catalogues={f'P{p}': [{f'G{g}': LABELS[v] for g, v in enumerate(row)} for row in rows]
                             for p, rows in self.types.items()},
            catalogue_scope='Each named player owns its preference rows. The episode initial possibilities condition this catalogue before history.',
            partner=self.partner.specification(),
            rules='ALL_OF goals contribute only when every required commitment is bound. Terminal utility counts own want goals minus own avoid goals. Commitments are irreversible. Offers bind only on acceptance; menus bind only the chosen option. PASS and rejection consume a proposal turn. All native actions remain available.')

    def history(self, node):
        actions = transcript_actions(node.state.public_state()['transcript'])
        if node.pending is not None:
            actions.append(OfferProposal(node.pending))
        current, result = self.search.initial(), []
        for action in actions:
            result.append(dict(turn=current.state.turn_index, player=f'P{self.search.actor(current)}',
                               action=render_action(current, action)))
            current = self.search._apply(current, action)
        return actions, result

    def support(self, node):
        return [LABELS[v] for v in (1, 0, -1) if any(w[self.target][self.goal] == v for w in node.worlds)]

    def failure(self, stage, error, **context):
        self.failures.append(dict(stage=stage, error_type=type(error).__name__, reason=str(error), **context))

    def save_sample(self, kind, payload, answer, case_id, origin):
        key = digest(dict(kind=kind, input=payload))
        sid = f's{self.seed}-{kind}-{key[:16]}'
        if sid in self.samples:
            assert self.samples[sid]['answer'] == answer
            self.samples[sid]['origins'].append(origin)
            return sid
        task = dict(kind=kind, input=payload, belief_options=OPTIONS)
        tool = submission_tool(task)
        # The schema always lists the full semantic universe, never the answer.
        arguments = deepcopy(answer)
        assert json.loads(json.dumps(arguments)) == answer
        self.samples[sid] = dict(id=sid, source_game=f's{self.seed}', case_id=case_id,
                                kind=kind, input=payload, answer=answer, tools=[tool], origins=[origin])
        return sid

    def save_b(self, node, origin, initial=None):
        actions, history = self.history(node)
        support = self.support(node)
        if initial is not None:
            assert not history
            support = list(initial)
        initial = OPTIONS if initial is None else initial
        case_id = f's{self.seed}-' + digest([a.to_dict() for a in actions])[:16]
        payload = dict(role_context=self.role, query=dict(player=f'P{self.target}', goals=[f'G{self.goal}']),
                       initially_possible_preferences=list(initial), history=history, game=self.public(),
                       question="Report every preference still possible for the named partner. With empty history retain the initial set unchanged. Ego actions are interventions; use observed partner actions as evidence. A player's utility preference is distinct from goal achievement.")
        return self.save_sample('semantic_belief', payload, dict(possible_preferences=support), case_id, origin)

    def record_case(self, node, origin):
        self.save_b(node, origin)
        actions, history = self.history(node)
        cid = f's{self.seed}-' + digest([a.to_dict() for a in actions])[:16]
        if cid in self.cases:
            self.cases[cid]['origins'].append(origin)
            return self.cases[cid]
        # Independent prefix replay includes pending proposals, not just events.
        replay = self.search.replay(actions)
        assert replay.worlds == node.worlds and replay.pending == node.pending
        assert replay.state.snapshot_commitments() == node.state.snapshot_commitments()
        remaining = len(self.spec.round_robin) - node.state.turn_index
        case = dict(id=cid, origins=[origin], history=[a.to_dict() for a in actions],
                    state=node.state.public_state(), pending_offer=None if node.pending is None else node.pending.to_dict(),
                    worlds=[[list(r) for r in w] for w in node.worlds], support=self.support(node),
                    remaining_proposal_turns=remaining, phase='proposal' if node.pending is None else 'response',
                    prefix_replay_verified=True, planning_status='outside_remaining_turn_budget')
        self.cases[cid] = case
        if remaining > self.max_remaining:
            return case
        start = time.monotonic()
        try:
            q = self.search.q_values(node)
        except SearchLimit as exc:
            case.update(planning_status='search_limit', planning_seconds=time.monotonic() - start)
            self.failure('planning', exc, case_id=cid)
            return case
        best = max(v for _, v in q)
        optimal = [a for a, v in q if best - v < 1e-9]
        # Stable labels; demonstration sampling and presentation have separate RNGs.
        chosen = choose_by_kind(optimal, rng_for(self.seed, cid, 'optimal-demonstration'))
        displayed = list(q)
        rng_for(self.seed, cid, 'display').shuffle(displayed)
        chosen_index = next(i for i, (a, _) in enumerate(displayed) if a == chosen)
        case.update(planning_status='exact', planning_seconds=time.monotonic() - start,
                    actions=[a.to_dict() for a, _ in displayed], q=[v for _, v in displayed],
                    optimal_indices=[i for i, (_, v) in enumerate(displayed) if best - v < 1e-9],
                    demonstration_index=chosen_index, demonstration_kind=action_kind(chosen),
                    optimal_kinds=sorted({action_kind(a) for a in optimal}),
                    action_value_span=best - min(v for _, v in q),
                    uniform_legal_expected_regret=best - sum(v for _, v in q) / len(q),
                    reference_continuation='Optimal future ego decisions; actual RationalPartner kernel for other players, through the true terminal turn.')
        branches = self.search.step(node, chosen)
        assert abs(sum(b.weight for b in branches) - 1) < 1e-9
        assert abs(sum(b.weight * self.search.value(b.node) for b in branches) - dict(q)[chosen]) < 1e-9
        case['selected_action_branch_accounting_verified'] = True
        if not self.independent_checked and remaining <= 2:
            try:
                checked, count = independent_q(self.search, node)
                assert all(abs(dict(q)[a] - v) < 1e-9 for a, v in checked)
                case['independent_search_check'] = dict(status='passed', nodes=count)
                self.independent_checked = True
            except SearchLimit as exc:
                case['independent_search_check'] = dict(status='budget_exceeded', reason=str(exc))
        payload = dict(role_context=self.role, game=self.public(), history=history,
                       initially_possible_preferences=OPTIONS,
                       state=dict(turn=node.state.turn_index, current_proposer=node.state.current_proposer(),
                                  commitments={f'P{p}': [f'A{i}' for i, v in enumerate(row) if v]
                                               for p, row in enumerate(node.state.snapshot_commitments())},
                                  remaining_proposers=list(self.spec.round_robin[node.state.turn_index:])),
                       pending_offer=None if node.pending is None else render_action(node, OfferProposal(node.pending)),
                       partner_judgment=dict(player=f'P{self.target}', goals=[f'G{self.goal}'], possible_preferences=self.support(node)),
                       legal_actions=[dict(action_index=i, action=render_action(node, a)) for i, (a, _) in enumerate(displayed)],
                       instruction='Select an action with best expected terminal outcome. Use the public history, current state and supplied partner judgment; consider future partner actions and new evidence. If actions tie, choose any one.')
        self.save_sample('planning', payload, dict(action_index=chosen_index), cid, origin)
        return case

    def explore(self, node, case):
        q = [(decode_action(a), v) for a, v in zip(case['actions'], case['q'])]
        best = max(v for _, v in q)
        selected = [choose_by_kind([a for a, v in q if best - v < 1e-9], rng_for(self.seed, case['id'], 'expert-branch'))]
        for kind in ('OFFER', 'MENU'):
            pool = [a for a, _ in q if action_kind(a) == kind]
            if pool:
                selected.append(rng_for(self.seed, case['id'], kind, 'branch').choice(pool))
        for action in dict.fromkeys(selected):
            aid = digest(action.to_dict())[:12]
            branches = self.search.step(node, action)
            assert abs(sum(b.weight for b in branches) - 1) < 1e-9
            record = dict(root=case['id'], action=action.to_dict(), branches=[])
            self.interventions.append(record)
            for i, b in enumerate(branches):
                origin = dict(mode='intervention', root=case['id'], action_id=aid, branch=i, weight=b.weight)
                child = None
                if not b.node.state.is_terminal:
                    child = self.record_case(b.node, origin)['id']
                record['branches'].append(dict(weight=b.weight, evidence=list(b.evidence),
                                               support=self.support(b.node), case_id=child,
                                               terminal=b.node.state.is_terminal,
                                               terminal_utility=self.search.utility(b.node) if b.node.state.is_terminal else None))

    def run(self):
        start = time.monotonic()
        for possible in [OPTIONS, ['want'], ['neutral'], ['avoid']]:
            self.save_b(self.search.initial(), dict(mode='empty_history_control'), initial=possible)
        explored = 0
        for mode in ('category_balanced', 'uniform_legal'):
            rng = rng_for(self.seed, mode, 'actions')
            world = rng_for(self.seed, mode, 'world').choice(self.search.worlds)
            node, prefix, updates = self.search.initial(), [], []
            trajectory = dict(mode=mode, realized_world=[list(r) for r in world], prior='uniform over 3 public worlds',
                              actions=prefix, evidence_updates=updates, completed=False)
            self.trajectories.append(trajectory)
            try:
                while not node.state.is_terminal:
                    actor = self.search.actor(node)
                    if actor == self.ego:
                        case = self.record_case(node, dict(mode=mode, decision=len(prefix)))
                        if (explored < self.branch_roots and case['planning_status'] == 'exact'
                                and node.pending is None):
                            self.explore(node, case)
                            explored += 1
                        legal = self.search.actions(node)
                        action = choose_by_kind(legal, rng) if mode == 'category_balanced' else rng.choice(legal)
                    else:
                        action = self.search._partner_action(node, world)
                        predictions = [(w, self.search._partner_action(node, w)) for w in node.worlds]
                        worlds = tuple(w for w, a in predictions if a == action)
                        assert world in worlds and worlds
                        updates.append(dict(decision=len(prefix), actor=actor, action=action.to_dict(),
                                            predictions=[dict(preference=LABELS[w[self.target][self.goal]], action=a.to_dict())
                                                         for w, a in predictions],
                                            before=self.support(node), after=[LABELS[v] for v in (1, 0, -1)
                                                if any(w[self.target][self.goal] == v for w in worlds)]))
                        node = Node(node.state, worlds, node.pending)
                    prefix.append(action.to_dict())
                    before = node.state.snapshot_commitments()
                    node = self.search._apply(node, action)
                    after = node.state.snapshot_commitments()
                    assert all(old <= new for r, s in zip(before, after) for old, new in zip(r, s))
                trajectory.update(completed=True, terminal_utility=self.search.utility(node),
                                  final_commitments=node.state.snapshot_commitments())
            except SearchLimit as exc:
                self.failure('trajectory', exc, mode=mode, completed_actions=len(prefix))
        return dict(version=VERSION, source_game=f's{self.seed}', seed=self.seed, split='development_audit_only',
                    source_spec=self.spec.to_dict(include_private=True), topology_hash=topology_hash(self.spec),
                    ego=self.ego, target=self.target, goal=self.goal,
                    type_catalogues={str(p): [list(r) for r in rows] for p, rows in self.types.items()},
                    trajectories=self.trajectories, cases=list(self.cases.values()), samples=list(self.samples.values()),
                    interventions=self.interventions, failures=self.failures,
                    elapsed_seconds=time.monotonic() - start, partner_version=RationalPartner.VERSION,
                    independent_search_checked=self.independent_checked)


def generate_one(seed, max_nodes, max_remaining, branch_roots):
    return Audit(seed, max_nodes, max_remaining, branch_roots).run()


def summarize(games):
    cases = [c for g in games for c in g['cases']]
    samples = [s for g in games for s in g['samples']]
    planning = [c for c in cases if c['planning_status'] == 'exact']
    beliefs = [s for s in samples if s['kind'] == 'semantic_belief']
    counter = lambda values: dict(sorted(Counter(values).items()))
    by_topology = defaultdict(list)
    for g in games:
        by_topology[g['topology_hash']].append(g['source_game'])
    seconds = sorted(g['elapsed_seconds'] for g in games)
    return dict(
        source_games=len(games), sources_with_planning=sum(any(c['planning_status'] == 'exact' for c in g['cases']) for g in games),
        information_states=len(cases), examples=len(samples), sample_kinds=counter(s['kind'] for s in samples),
        belief_supports=counter('|'.join(s['answer']['possible_preferences']) for s in beliefs),
        empty_history_beliefs=sum(not s['input']['history'] for s in beliefs),
        planning_status=counter(c['planning_status'] for c in cases),
        planning_phases=counter(c['phase'] for c in planning),
        demonstrations=counter(c['demonstration_kind'] for c in planning),
        optimal_kind_sets=counter('|'.join(c['optimal_kinds']) for c in planning),
        tie_sizes=counter(str(len(c['optimal_indices'])) for c in planning),
        all_actions_tied=sum(len(c['optimal_indices']) == len(c['actions']) for c in planning),
        sources_independently_checked=sum(g['independent_search_checked'] for g in games),
        completed_trajectories=sum(t['completed'] for g in games for t in g['trajectories']),
        attempted_trajectories=sum(len(g['trajectories']) for g in games),
        interventions=sum(len(g['interventions']) for g in games),
        failures=counter(f['stage'] + ': ' + f['error_type'] for g in games for f in g['failures']),
        distinct_topologies=len(by_topology), duplicate_topology_groups=[v for v in by_topology.values() if len(v) > 1],
        sampled_hidden_preferences=counter(LABELS[t['realized_world'][g['target']][g['goal']]]
                                            for g in games for t in g['trajectories']),
        role_pairs=counter(f"P{g['ego']}->P{g['target']}" for g in games),
        input_characters={kind: dict(min=min(values), median=sorted(values)[len(values)//2], max=max(values))
                          for kind in ('semantic_belief', 'planning')
                          if (values := [len(canonical(s['input'])) for s in samples if s['kind'] == kind])},
        per_source_seconds=dict(median=seconds[len(seconds)//2], max=max(seconds), sum=sum(seconds)),
        per_source_examples=counter(str(len(g['samples'])) for g in games),
        tokenizer_status='not_measured', model_results=False, training_started=False)


def export(output, games, manifest):
    summary = summarize(games)
    write_json(output / 'summary.json', summary)
    samples = [s for g in games for s in g['samples']]
    records = []
    for s in samples:
        tool = s['tools'][0]['function']['name']
        records.append(dict(id=s['id'], source_game=s['source_game'], case_id=s['case_id'], kind=s['kind'],
                            split='development_audit_only', tools=s['tools'], messages=[
                                dict(role='system', content=SYSTEM_SFT),
                                dict(role='user', content=canonical(s['input'])),
                                dict(role='assistant', content='', tool_calls=[dict(type='function', function=dict(
                                    name=tool, arguments=s['answer']))])]))
    write_jsonl(output / 'examples.jsonl', records)
    write_jsonl(output / 'labels.jsonl', [dict(id=s['id'], source_game=s['source_game'], case_id=s['case_id'],
                                             answer=s['answer'], origins=s['origins']) for s in samples])
    write_jsonl(output / 'planning_cases.jsonl', [dict(source_game=g['source_game'], **c) for g in games
                                                  for c in g['cases'] if c['planning_status'] == 'exact'])
    write_jsonl(output / 'failures.jsonl', [dict(source_game=g['source_game'], **f) for g in games for f in g['failures']])
    write_json(output / 'source_games.json', [dict(source_game=g['source_game'], split=g['split'], seed=g['seed'],
                                                 topology_hash=g['topology_hash'], game=g['source_spec'],
                                                 ego=g['ego'], target=g['target'], goal=g['goal'],
                                                 type_catalogues=g['type_catalogues']) for g in games])
    write_json(output / 'checksums.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in output.iterdir() if p.is_file() and p.name not in ('checksums.json', 'report.md')})
    lines = ['# B/P SFT 数据生成审计（开发集）', '',
             '**不是最终测试集；没有模型调用或训练结果。**', '',
             f"生成 {summary['source_games']} 个源游戏，{summary['information_states']} 个不同决策信息状态，{summary['examples']} 条去重 B/P 示例。", '',
             '| 项目 | 数量 |', '|---|---:|']
    for key in ('sources_with_planning', 'completed_trajectories', 'attempted_trajectories', 'empty_history_beliefs',
                'all_actions_tied', 'interventions', 'sources_independently_checked', 'distinct_topologies'):
        lines.append(f'| {key} | {summary[key]} |')
    for key in ('sample_kinds', 'belief_supports', 'planning_status', 'planning_phases', 'demonstrations',
                'optimal_kind_sets', 'failures', 'input_characters', 'per_source_seconds'):
        lines += ['', f'## {key}', '', '```json', json.dumps(summary[key], indent=2, ensure_ascii=False), '```']
    lines += ['', '## 生成与解释边界', '',
              '- 固定 3 人、每人 2 commitments、8 goals、2 rounds、menu enabled；一个伙伴的一个未知偏好，其余行公开。',
              '- 源游戏先固定；query 在保证三个类型均合法的候选中采样，不按模型错误或策略机会筛选。',
              '- 每个源游戏两条采集轨迹：动作类别均衡和合法动作均匀；隐藏世界从声明的等权目录独立采样。',
              '- 主轨迹中的 ego 决策全部保留 B；剩余原始 proposer turns <=3 时尝试精确 P 标签。',
              '- 每游戏最多一个 proposal root 扩展 expert/普通 offer/menu 分支，不要求它有正信息收益；保留全部证据分支与原始权重。',
              '- 四条空历史 B controls 是独立题目，不把观察后的标签伪装成初始信息；其中 singleton controls 没有延续轨迹。',
              '- 完整 Q 与最优集合留在审计层。示范先在最优动作类别间采样，再在类别内部采样；展示顺序独立打乱。',
              '- 输入使用白名单，不包含源 seed、实际隐藏世界、Q、标签证书；P 的正确显式判断是设计内 oracle assistance。',
              '- 所有样本 development_audit_only，不划正式 train/test；同源及同构变体未来必须归入相同源家族。',
              '- 未进行 tokenizer/Hermes 运行时验证时不得称为可直接开训。字符数不是 token 数。',
              '- 独立搜索验证复用环境转换和伙伴 kernel，验证 ego 搜索及分支加权，不是独立的伙伴理性证明。',
              '- 未按信息机会挑选；B/P 标签和动作分布仅描述本采集策略。复制和分支数不增加独立游戏数。',
              '', '## 复现', '', '```bash',
              'PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.sft_data_audit ' +
              f"--output-dir {output} --seed {manifest['seed']} --games {manifest['games']} --workers 4 --resume",
              '```', '']
    (output / 'report.md').write_text('\n'.join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=50000)
    parser.add_argument('--games', type=int, default=100)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-nodes', type=int, default=20000)
    parser.add_argument('--max-remaining', type=int, default=3)
    parser.add_argument('--branch-roots', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    if min(args.games, args.workers, args.max_nodes, args.max_remaining) < 1:
        parser.error('Positive budgets required.')
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), *[Path(__file__).with_name(n) for n in
               ('generator.py', 'endgame.py', 'endgame_partner.py', 'endgame_diagnose.py', 'diagnose_protocol.py', 'state.py', 'schema.py')]]
    manifest = dict(version=VERSION, purpose='development_audit_only', seed=args.seed, games=args.games,
                    max_nodes=args.max_nodes, max_remaining=args.max_remaining, branch_roots=args.branch_roots,
                    partner_version=RationalPartner.VERSION,
                    source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                    initial_world_sampling='uniform catalogue; separate deterministic RNG streams',
                    system=SYSTEM_SFT, model_calls=False, training=False)
    manifest_path = output / 'manifest.json'
    if manifest_path.exists():
        if not args.resume or json.loads(manifest_path.read_text()) != manifest:
            parser.error('Existing directory requires --resume and identical manifest.')
    else:
        write_json(manifest_path, manifest)
    games = []
    pending = []
    for seed in range(args.seed, args.seed + args.games):
        path = output / 'games' / f'{seed}.json'
        if path.exists():
            games.append(json.loads(path.read_text()))
        else:
            pending.append(seed)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(generate_one, s, args.max_nodes, args.max_remaining, args.branch_roots): s for s in pending}
        for future in as_completed(futures):
            seed = futures[future]
            game = future.result()  # Unexpected errors stop; never silently replace a source seed.
            write_json(output / 'games' / f'{seed}.json', game)
            games.append(game)
            print(f"[{len(games)}/{args.games}] seed={seed} examples={len(game['samples'])} "
                  f"exact_P={sum(c['planning_status']=='exact' for c in game['cases'])} "
                  f"seconds={game['elapsed_seconds']:.1f} failures={len(game['failures'])}", flush=True)
    games.sort(key=lambda g: g['seed'])
    export(output, games, manifest)
    print(json.dumps(summarize(games), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
