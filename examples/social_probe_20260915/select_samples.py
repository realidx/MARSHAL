"""Freeze a small diagnostic selection. No model results, solver filtering or HTTP."""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260915
BP = 'examples/social_bp/data/tasks.jsonl'
BRIDGES = 'examples/social_bp/b_response_bridges_v1/tasks.jsonl'
CURRICULUM = 'runs/outcome_selfplay_screen/curriculum.json'
EVAL = 'runs/outcome_selfplay_screen/eval_splits.json'


def read(name):
    return [json.loads(x) for x in (ROOT/name).read_text().splitlines() if x.strip()]


def key(value):
    return sha256(f'{SEED}:{value}'.encode()).hexdigest()


def pick(rows):
    return min(rows, key=lambda r: key(r['id']))


def features(t):
    result = {f'stage:{t["stage"]}', f'players:{t["input"]["game"]["n_players"]}'}
    if t['task'] == 'B':
        gold = t['teacher']['gold']
        result.add(f'set_size:{len(gold["possible_preferences"])}')
        if len(gold['possible_preferences']) > 1 and gold['favored'] != 'undetermined':
            result.add('nonredundant_favored')
        old = t['input'].get('previous_belief')
        if old and old['possible_preferences'] == gold['possible_preferences'] and old['favored'] != gold['favored']:
            result.add('favored_only_update')
    else:
        result.add(f'belief:{t.get("qualitative_level") or "ordinary"}')
        for a in t['teacher']['acceptable_actions']:
            result.add(f'accepted_kind:{a.get("action", a.get("response"))}')
    return result


def select_old(rows):
    chosen = []
    for pool in ('formation', 'maintain', 'update', 'complete', 'uncertain', 'result_use'):
        eligible = [r for r in rows if r['pool'] == pool and not r['direct_answer'] and r['split'] != 'test']
        train = list(combinations([r for r in eligible if r['split'] == 'train'], 2))
        val = list(combinations([r for r in eligible if r['split'] == 'validation'], 2))
        # Coverage priorities are declared before reading any model outcomes.
        def rank(group):
            fs = set().union(*(features(r) for r in group))
            return (-int('favored_only_update' in fs),
                    -len({r['stage'] for r in group}),
                    -len([x for x in fs if x.startswith('belief:')]),
                    -len(fs), -len({r['family'] for r in group}),
                    key(':'.join(sorted(r['id'] for r in group))))
        group = min((a+b for a in train for b in val), key=rank)
        for r in group:
            chosen.append((r, '原 B/P', '每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列'))

    info = [r for r in rows if r['pool'] == 'information']
    positives = [r for r in info if r['split'] == 'train' and r.get('information_positive')
                 and r['teacher'].get('own_query_margin', 0) > .1
                 and any(n['split'] == 'train' and n['contrast_group'] == r['contrast_group']
                         and n.get('information_negative_kind') == 'last_opportunity' for n in info)]
    positive = pick(positives)
    negative = pick([r for r in info if r['split'] == 'train'
                     and r['contrast_group'] == positive['contrast_group']
                     and r.get('information_negative_kind') == 'last_opportunity'])
    future = pick([r for r in info if r['split'] == 'validation'
                   and r.get('information_negative_kind') == 'future_opportunity_remains'])
    val_positive = pick([r for r in info if r['split'] == 'validation' and r.get('information_positive')
                         and r['teacher'].get('own_query_margin', 0) > .1])
    for r, why in ((positive, '调查严格提高自身收益；与下题同 contrast_group'),
                   (negative, '配对的最后机会不调查反例'),
                   (val_positive, '验证集：调查严格提高自身收益'),
                   (future, '验证集：仍有后续机会但不应调查')):
        chosen.append((r, '原 B/P', why))
    return chosen


def select_bridges(rows):
    rows = [r for r in rows if r['split'] != 'test']
    chosen = []
    def add(level, pred, why):
        r = pick([r for r in rows if r['b_lesson_level'] == level and pred(r)])
        assert r['id'] not in {x[0]['id'] for x in chosen}
        chosen.append((r, '新 B', why))
    for answer in ('want', 'avoid'):
        add(0, lambda r, a=answer: r['skill'] == 'formation' and r['teacher']['gold']['possible_preferences'] == [a],
            '两候选：接受／拒绝导致相反结论的形成对照')
    add(0, lambda r: r['skill'] == 'update', '两候选：承接旧 belief 后更新')
    add(0, lambda r: r['skill'] == 'maintain', '两候选：无关证据下维持')
    for mode in ('altruistic', 'conflict'):
        add(1, lambda r, m=mode: r['b_lesson'] == m and r['skill'] == 'formation'
            and r['input']['voluntary_history'][-1].get('response') == 'ACCEPT',
            '同为接受，改变观察者收益后 neutral 的选择不同')
    add(1, lambda r: r['b_lesson'] == 'conflict' and r['skill'] == 'update'
        and r['input']['voluntary_history'][-1].get('response') == 'REJECT', 'neutral 平局：拒绝后的更新')
    add(1, lambda r: r['b_lesson'] == 'altruistic' and r['skill'] == 'maintain', '三候选：无关证据下维持全集')
    for skill in ('maintain', 'update'):
        add(2, lambda r, s=skill: r['skill'] == s, '相同多目标收益背景下，接受维持／拒绝更新对照')
    for split, skill in (('train', 'formation'), ('validation', 'update')):
        for favored in ('want', 'avoid'):
            add(3, lambda r, sp=split, sk=skill, f=favored: r['split'] == sp and r['skill'] == sk
                and r['teacher']['gold']['favored'] == f, '多元素集合内明确 favored；接受／拒绝对照')
    for split, lesson in (('train', 'favored_disappears'), ('validation', 'favored_appears')):
        for full in (True, False):
            add(4, lambda r, sp=split, le=lesson, f=full: r['split'] == sp and r['b_lesson'] == le
                and r['skill'] == 'update' and (len(r['teacher']['gold']['possible_preferences']) == 3) == f,
                '联合约束：集合不变的 favored 更新／同时改变集合的对照')
    return chosen


def select_selfplay(m, e):
    instances = {r['id']: r for r in m['instances']}
    # Four games per completion stratum. Overall: 8 train + 4 validation, 8 two-player + 4 three-player.
    slots = [('foundation', 'linear', 'train', 2, 2), ('foundation', 'linear', 'train', 3, 3),
             ('foundation', 'linear', 'train', 2, 4), ('foundation', 'linear', 'validation', 2, 2),
             ('adaptation', 'mixed', 'train', 2, 3), ('adaptation', 'mixed', 'train', 3, 4),
             ('adaptation', 'mixed', 'train', 2, 2), ('adaptation', 'mixed', 'validation', 3, 3),
             ('tradeoffs', 'binary', 'train', 2, 5), ('tradeoffs', 'binary', 'train', 3, 2),
             ('tradeoffs', 'binary', 'validation', 2, 2), ('tradeoffs', 'binary', 'validation', 2, 3)]
    selected = []
    for level, completion, split, players, rounds in slots:
        if split == 'train':
            r = pick([r for r in m['resets'] if (r['level'], r['players'], r['rounds']) == (level, players, rounds)])
            instance = instances[r['instance_id']]
            raw, world, family = instance['raw'], r['realized_world'], instance['template']
        else:
            r = pick([r for r in e['records'] if (r['split'], r['completion'], r['players'], r['rounds'])
                      == (split, completion, players, rounds)])
            raw, world, family = r['raw'], r['realized_world'], r['structural_key']
        selected.append(dict(id=r['id'], group_id=r['id'], split=split, level=level, completion=completion,
                             players=players, rounds=rounds, family=family, raw=raw, realized_world=world,
                             selection_reason='预先指定人数／轮数／计分方式；层内哈希抽取，不查看 solver 或模型表现'))
    return selected


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--out', type=Path, default=Path(__file__).with_name('selection_v1'))
    args = cli.parse_args()
    selected = select_old(read(BP)) + select_bridges(read(BRIDGES))
    m = json.loads((ROOT/CURRICULUM).read_text()); e = json.loads((ROOT/EVAL).read_text())
    resets = select_selfplay(m, e)
    assert len(selected) == 46 and len({r['id'] for r, _, _ in selected}) == 46
    assert len(resets) == 12 and len({r['id'] for r in resets}) == 12
    assert all(r['split'] != 'test' and not r['direct_answer'] for r, _, _ in selected)
    request_sources = ['examples/bp_pilot_probe_nus/bundle/train_requests.jsonl',
                       'examples/bp_pilot_probe_nus/bundle/validation_requests.jsonl',
                       'examples/social_bp/b_response_bridges_v1/requests.jsonl']
    requests = {r['task_id']: r for name in request_sources for r in read(name)}
    out = args.out; out.mkdir(parents=True, exist_ok=False)
    def write(name, rows):
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    for label, filename in (('原 B/P', 'bp'), ('新 B', 'bridges')):
        rows = [r for r, kind, _ in selected if kind == label]
        write(filename+'_tasks.local.jsonl', rows)
        reqs = [requests[r['id']] for r in rows]
        assert all(r['request']['max_tokens'] == 1024 for r in reqs)
        write(filename+'_requests.jsonl', reqs)
    write('selfplay_resets.environment.jsonl', resets)
    metadata = [dict(id=r['id'], dataset=kind, task=r['task'], pool=r['pool'], split=r['split'],
                     stage=r['stage'], lesson_level=r.get('b_lesson_level'), family=r['family'],
                     features=sorted(features(r)), reason=why) for r, kind, why in selected]
    write('selection.jsonl', metadata)
    source_names = [BP, BRIDGES, CURRICULUM, EVAL, *request_sources,
                    'examples/outcome_selfplay_nus/runtime_v4.tar.gz']
    manifest = dict(version='social-diagnostic-selection-v1', selection_seed=SEED,
                    selection_method='Predeclared diagnostic strata and contrasts; SHA256 tie-break; no model-outcome selection',
                    bp_conditions=28, bridge_conditions=18, selfplay_resets=12, test_selected=0,
                    proposed_bp_repetitions=8, proposed_selfplay_repetitions=4,
                    proposed_bp_calls=368, proposed_full_games=48, sampling_started=False,
                    source_sha256={n:sha256((ROOT/n).read_bytes()).hexdigest() for n in source_names},
                    selector_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                    files_sha256={p.name:sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())})
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    lines = ['# 首轮小样本检查名单', '',
             '仅完成选题，尚未调用模型。原 B/P 每池 4 题，新 B 各层 4/4/2/4/4 题，self-play 各计分层 4 个开局。', '',
             '这是按能力和对照关系分层的诊断集，不按总体数据比例抽取，平均成绩不能当作完整数据集准确率。层内用固定 seed 20260915 的 ID 哈希选择；未读取任何模型结果。', '',
             '原 B/P 每池 2 train + 2 validation；直接读取真值题和 held-out test 均不入选。新 B 的层 0–2 没有可用 validation，均从 train 抽取；层 3–4 各 2 train + 2 validation。', '',
             '建议每道 B/P 采 8 次（368 次回答），每个 self-play 开局采 4 场（48 场）；次数尚未执行。原 B/P 已有基线，可先按这份名单提取旧回答，避免无条件重跑。旧 validation 每题只有 4 次，若对齐到 8 次需要补采并保留批次标记。', '',
             '## B/P 逐题名单', '', '| 来源 | 类别／层 | split | ID | 选取理由 |', '|---|---|---|---|---|']
    for r, kind, why in selected:
        category = f'{r["task"]}/{r["pool"]}' + (f' / L{r["b_lesson_level"]}' if kind == '新 B' else f' / stage {r["stage"]}')
        lines.append(f'| {kind} | {category} | {r["split"]} | `{r["id"]}` | {why} |')
    lines += ['', '## Self-play 开局', '', '| 课程层 | split | 人数 | 每人轮数 | ID |', '|---|---|---:|---:|---|']
    for r in resets:
        lines.append(f'| {r["level"]} / {r["completion"]} | {r["split"]} | {r["players"]} | {r["rounds"]} | `{r["id"]}` |')
    lines += ['', '## 文件与边界', '',
              '- `bp_requests.jsonl`、`bridges_requests.jsonl`：可直接发送的无标签模型请求，沿用冻结的 B/P 原生工具、temperature 0.8、1024 输出预算。',
              '- `*_tasks.local.jsonl`：本地评分标签；不作为模型输入。',
              '- `selfplay_resets.environment.jsonl`：环境重置用，包含真实隐藏世界；只能经 safe_observation 向模型生成输入。',
              '- `selection.jsonl`、`manifest.json`：选取理由、来源与文件哈希。',
              '- self-play 的 validation 按 completion 对应课程层归类，不声称其难度与 train 相同；未筛 solver 收敛或高收益开局。',
              '- 新 B 对照题通常来自同一家族；重复采样及相邻 checkpoint 均不增加独立场景数。',
              '- 当前 P 库尚缺计划中的新增后续决策配对，不能把本次 result_use 选题声称为已补齐该缺口。',
              '- 旧 self-play 的 --suite all 不读取本名单；本次只冻结开局，运行前需要接入显式 reset 文件。', '']
    (out/'README.md').write_text('\n'.join(lines))
    print(json.dumps(dict(output=str(out), bp=dict(Counter((r['split']) for r, k, _ in selected if k == '原 B/P')),
                         bridges=dict(Counter(r['split'] for r, k, _ in selected if k == '新 B')),
                         selfplay=dict(Counter(r['split'] for r in resets))), ensure_ascii=False))


if __name__ == '__main__':
    main()
