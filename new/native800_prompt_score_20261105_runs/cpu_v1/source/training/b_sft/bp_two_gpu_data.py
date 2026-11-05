"""Frozen two-GPU pilot data and deterministic, outcome-independent sampling."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

VERSION = 'bp-two-a100-v1'
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'examples/social_bp/data'
BRIDGE = ROOT/'examples/social_bp/b_response_bridges_v1'
L0 = ROOT/'examples/social_bp/b_l0_isolated_v1'


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select_batch(rows, step, max_steps, batch_size, seed):
    if batch_size != 16 or not 0 <= step < max_steps:
        raise ValueError('Two-GPU pilot requires 16 distinct prompts and a valid step')
    if any(t['split'] != 'train' or t.get('training_pack_version') != VERSION for t in rows):
        raise ValueError('Only frozen train rows may enter the sampler')
    rng = random.Random(f'{VERSION}:{seed}:{step}')
    selected = []; used = set(); families = Counter()
    def pick(pool):
        pool = [t for t in pool if t['id'] not in used]
        if not pool:
            raise ValueError('Missing distinct source/skill/contrast in frozen train data')
        least = min(families[t['family']] for t in pool)
        pool = sorted([t for t in pool if families[t['family']] == least], key=lambda t:t['id'])
        t = rng.choice(pool)
        selected.append(t); used.add(t['id']); families[t['family']] += 1
    l0 = sorted([t for t in rows if t['training_source'] == 'l0'], key=lambda t:t['id'])
    if len(l0) != 3:
        raise ValueError('Expected exactly three assisted train L0 contrasts')
    for offset in (0, 1):
        pick([l0[(step+offset) % 3]])
    for source in ('bridge', 'original'):
        for skill in ('formation', 'maintain', 'update'):
            pool = [t for t in rows if t['task'] == 'B' and t['training_source'] == source
                    and t['pool'] == skill and not t['direct_answer']]
            # Keep multi-element favored and same-set favored updates exposed,
            # without using model scores or promoting difficulty mid-pilot.
            if skill == 'update' and step % 5 == 0:
                special = [t for t in pool if len(t['teacher']['gold']['possible_preferences']) > 1
                           and t['input'].get('previous_belief') != t['teacher']['gold']]
                if special:
                    pool = special
            pick(pool)
    for skill in ('complete', 'uncertain', 'result_use', 'information'):
        for index in range(2):
            pool = [t for t in rows if t['task'] == 'P' and t['pool'] == skill]
            if skill == 'information':
                pool = [t for t in pool if bool(t.get('information_positive')) == (index == 0)]
                if index == 1 and step % 2 == 0:
                    future = [t for t in pool if t.get('information_negative_kind') == 'future_opportunity_remains']
                    if future:
                        pool = future
            pick(pool)
    rng.shuffle(selected)
    return selected


def build(out):
    from training.b_sft.bp_semantics import semantic_id
    from training.b_sft.build_b_response_bridges import verify_task
    from training.b_sft.social_bp_grpo import validate_tasks
    baseline_audit = json.loads((BASE/'solver_audit.json').read_text())
    bridge_audit = json.loads((BRIDGE/'audit.json').read_text())
    assert baseline_audit['tasks_sha256'] == sha(BASE/'tasks.jsonl')
    assert bridge_audit['summary']['tasks_sha256'] == sha(BRIDGE/'tasks.jsonl')
    candidate = []
    for t in read(BASE/'tasks.jsonl'):
        if t['split'] == 'train' and t['task'] == 'B' and t['direct_answer']:
            continue
        candidate.append((t, 'original'))
    for t in read(BRIDGE/'tasks.jsonl'):
        if t['split'] == 'train' and t['b_lesson_level'] > 0:
            candidate.append((t, 'bridge'))
    for t in read(L0/'tasks.jsonl'):
        if t['b_lesson_step'] == 'assisted':
            candidate.append((t, 'l0'))
    seen = {}; tasks = []; duplicates = []
    for original, source in candidate:
        t = deepcopy(original); key = semantic_id(t)
        assert key == t['semantic_id']
        if key in seen:
            assert seen[key]['split'] == t['split']
            duplicates.append(dict(id=t['id'], kept=seen[key]['id']))
            continue
        t.update(training_pack_version=VERSION, training_source=source)
        seen[key] = t; tasks.append(t)
    checks = validate_tasks(tasks)
    added_checks = [verify_task(t) for t in tasks if t['training_source'] != 'original']
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    (out/'tasks.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in tasks))
    audit = dict(tasks_sha256=sha(out/'tasks.jsonl'), summary=dict(checks,
        tokenizer=baseline_audit['summary']['tokenizer']), version=VERSION,
        base_labels='Unchanged inputs/labels bound to the previous independent solver audit hash',
        new_label_checks=added_checks, duplicates=duplicates,
        sources={str(p.relative_to(ROOT)):sha(p) for p in
            (BASE/'tasks.jsonl', BASE/'solver_audit.json', BRIDGE/'tasks.jsonl', BRIDGE/'audit.json',
             L0/'tasks.jsonl', L0/'audit.json')})
    (out/'solver_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    train = [t for t in tasks if t['split']=='train']
    schedule = [dict(step=s, ids=[t['id'] for t in select_batch(train,s,30,16,20260915)]) for s in range(30)]
    (out/'schedule_seed20260915.json').write_text(json.dumps(schedule,indent=2)+'\n')
    result = dict(version=VERSION, splits=dict(Counter(t['split'] for t in tasks)),
        train_sources=dict(Counter(t['training_source'] for t in train)),
        train_kinds=dict(Counter(t['task'] for t in train)),
        validation_ids=[t['id'] for t in tasks if t['split']=='validation'],
        test_ids_unchanged=[t['id'] for t in tasks if t['split']=='test'],
        source_quota=dict(l0=2,bridge=3,original_b=3,p=8), direct_b_training=0,
        merged=True, learner_trained=False, difficulty_schedule='fixed for 30 updates',
        files_sha256={p.name:sha(p) for p in out.iterdir()})
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('version','splits','train_sources','train_kinds')},indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default=str(ROOT/'examples/social_bp/data_two_a100_v1'))
    build(parser.parse_args().out)
