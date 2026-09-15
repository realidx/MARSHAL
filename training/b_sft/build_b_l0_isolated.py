"""Isolated final-response lessons; keep historical probes and test families frozen."""
import argparse
from collections import Counter
from copy import copy
import hashlib
import json
from pathlib import Path

from training.b_sft.bp_semantics import semantic_id
from training.b_sft.build_b_response_bridges import offer, response_certificate, verify_task
from training.b_sft.build_bp_pilot import make_task, topology
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_named_probe import request
from training.b_sft.social_private_teacher import PrivateEpisode

VERSION = 'b-l0-isolated-v1'
LEGACY = ('examples/social_bp/data/tasks.jsonl',
          'examples/social_bp/b_response_bridges_v1/tasks.jsonl')


def fixture(split):
    # Every goal still involves two players. All commitments have a real use.
    # Extra prerequisites make these different physical families from the
    # held-out two-by-two disjoint fixture, not name/padding variants of it.
    if split == 'train':
        counts = [3, 2]
        refs = [[(0, 0), (1, 0)], [(0, 1), (0, 2), (1, 1)]]
    elif split == 'validation':
        counts = [3, 3]
        refs = [[(0, 0), (1, 0), (1, 1)], [(0, 1), (0, 2), (1, 2)]]
    else:
        raise ValueError(split)
    raw = dict(id=f'{VERSION}:{split}', ego=0, own_preferences=[0, 1], history=[],
        type_catalogues={'0': [[0, 1]], '1': [[v, 1] for v in (1, 0, -1)]},
        game=dict(n_players=2, n_actions_per_player=counts, max_changes=2,
            menu_enabled=False, round_robin=[1, 0], goals=[dict(goal_id=g, binary=True,
                required_actions=[dict(player_id=p, action_id=a) for p, a in rs])
                for g, rs in enumerate(refs)]))
    return expand_support(raw)[:2]


def build_tasks():
    tasks = []
    for split in ('train', 'validation'):
        raw, public = fixture(split)
        for goal in (0, 1):
            setup = [dict(action='PASS'), offer(raw, goal)]
            root = PrivateEpisode(raw, setup)
            prior = root.belief(1, 0, observer=0, own=raw['own_preferences'])
            prior = {k: prior[k] for k in ('possible_preferences', 'favored')}
            for response in ('ACCEPT', 'REJECT'):
                cert = response_certificate(root, response)
                if cert is None:
                    continue
                after = copy(root)
                event = dict(response=response)
                after.observe(event)
                for step, previous in (('assisted', prior), ('formation', None)):
                    t = make_task(after, public, setup, [event], 'B', 0, topology(raw),
                                  previous=previous, source=raw['id'])
                    t.update(split=split, name_variant=1, b_lesson_level=0, b_lesson='isolated_response',
                             b_lesson_step=step, short_teaching=True, bridge_version=VERSION,
                             evidence_relation='target' if goal == 0 else 'unrelated')
                    t['contrast_group'] = hashlib.sha256(
                        f'{VERSION}:{t["family"]}:{step}'.encode()).hexdigest()[:20]
                    t['teacher']['response_certificate'] = cert
                    t['semantic_id'] = semantic_id(t)
                    tasks.append(t)
    assert len(tasks) == len({t['semantic_id'] for t in tasks}) == 12
    return tasks


def check_legacy(tasks, paths=LEGACY):
    old = [json.loads(line) for p in paths for line in Path(p).read_text().splitlines()]
    families = {t['family'] for t in tasks}
    # Stronger than just checking test: reject overlap with any historical family.
    assert not families & {t['family'] for t in old}, 'Existing structural family reused'
    old_semantics = {t.get('semantic_id') for t in old}
    assert not {t['semantic_id'] for t in tasks} & old_semantics
    return dict(legacy_tasks=len(old), family_overlap=0, semantic_overlap=0,
                source_sha256={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})


def make_request(t):
    req = request(t, 'action_tools', t['name_variant'])
    req.update(temperature=.8, top_p=1., top_k=-1, repetition_penalty=1.)
    return dict(task_id=t['id'], task='B', split=t['split'], pool=t['pool'],
                stage=t['stage'], output_arm='action_tools', request=req)


def write_pack(out):
    tasks = build_tasks()
    leakage = check_legacy(tasks)
    checks = [verify_task(t) for t in tasks]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    def write(name, rows):
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    write('tasks.jsonl', tasks)
    primary = [t for t in tasks if t['b_lesson_step'] == 'assisted']
    followup = [t for t in tasks if t['b_lesson_step'] == 'formation']
    write('requests.jsonl', [make_request(t) for t in primary])
    write('formation_requests.jsonl', [make_request(t) for t in followup])
    summary = dict(version=VERSION, tasks=len(tasks), primary_conditions=len(primary),
        followup_conditions=len(followup), splits=dict(Counter(t['split'] for t in tasks)),
        families=len({t['family'] for t in tasks}), learner_tested=False,
        scope='Replacement L0 candidate; assisted first, formation follow-up; not merged into full training.')
    (out/'audit.json').write_text(json.dumps(dict(summary=summary, checks=checks, leakage=leakage), indent=2)+'\n')
    (out/'probe_manifest.json').write_text(json.dumps(dict(version=VERSION,
        tasks_sha256=hashlib.sha256((out/'tasks.jsonl').read_bytes()).hexdigest(),
        requests_sha256=hashlib.sha256((out/'requests.jsonl').read_bytes()).hexdigest(),
        conditions=6, group_size=8, formal_requests=48, test_requests=0,
        response_budget=1024, output_arm='action_tools',
        followup=dict(file='formation_requests.jsonl', conditions=6, calls_if_requested=48,
                      sha256=hashlib.sha256((out/'formation_requests.jsonl').read_bytes()).hexdigest())), indent=2)+'\n')
    old_bridge = [json.loads(line) for line in Path(LEGACY[1]).read_text().splitlines()]
    (out/'curriculum_candidate.json').write_text(json.dumps(dict(
        merged=False, entry_task_ids=[t['id'] for t in primary if t['split'] == 'train'],
        validation_task_ids=[t['id'] for t in primary if t['split'] == 'validation'],
        formation_followup_ids=[t['id'] for t in followup],
        historical_non_test_l0_to_defer=[t['id'] for t in old_bridge
            if t['b_lesson_level'] == 0 and t['split'] != 'test'],
        historical_test_unchanged=True), indent=2)+'\n')
    lines = ['# 新 L0：隔离目标收益的最后响应', '',
        '原生 prompt、工具、规则与奖励保持不变；下面证书只供本地审核，不进入模型输入。', '',
        '首测 assisted 6 题，每题 8 次，共 48 次；formation 6 题另存，暂不混进首测。', '',
        '每个 split 各一个结构家族，三个对照不算三个独立场景。Validation 比 train 的目标多一个有效前置承诺，测结构迁移，不是 IID 随机验证。', '',
        '目标之间没有共享承诺，只有最后一个自愿响应。原生环境要求每轮每人一次提案机会，故保留合法起始 PASS 和 OFFER；它们不是行为证据。正确旧 belief 在 assisted 题中直接提供。', '',
        '为避免复用已有 test 的两目标双前置结构，背景目标含三个有效前置承诺；validation 的目标也含三个。每人最多增加两项承诺，属原生合法配置。并非单纯减少题面字数，是否更易须采样验证。', '',
        '前后状态仍由现有 renderer 展示，模型仍需重建接受前状态；没有直接给出收益表或答案。', '']
    for t in sorted(tasks, key=lambda t: (t['b_lesson_step'] != 'assisted', t['split'], t['id'])):
        lines += [f'## {t["split"]} / {t["b_lesson_step"]} / {t["skill"]} / {t["id"]}', '',
                  make_request(t)['request']['messages'][1]['content'], '',
                  '### 本地标签依据（不发送）', '', '```json',
                  json.dumps(t['teacher']['response_certificate'], ensure_ascii=False, indent=2), '```', '']
    (out/'review.md').write_text('\n'.join(lines))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='examples/social_bp/b_l0_isolated_v1')
    print(json.dumps(write_pack(parser.parse_args().out), indent=2))
