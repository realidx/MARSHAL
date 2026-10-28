"""Score a small native-tool B bridge probe locally, including failure groups."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from training.b_sft.social_bp_training import reward


def read(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def score_run(pack, samples):
    pack = Path(pack)
    manifest = json.loads((pack/'probe_manifest.json').read_text())
    for name in ('tasks', 'requests'):
        assert hashlib.sha256((pack/f'{name}.jsonl').read_bytes()).hexdigest() == manifest[f'{name}_sha256']
    tasks = {t['id']: t for t in read(pack/'tasks.jsonl')}
    allowed = {r['task_id'] for r in read(pack/'requests.jsonl')}
    seen, rows, groups, cells = set(), [], defaultdict(list), defaultdict(list)
    for s in read(samples):
        key = (s['task_id'], s['sample_index'])
        if key in seen or key[0] not in allowed or not 0 <= key[1] < manifest['group_size']:
            raise ValueError('Duplicate, unknown, held-out test or out-of-range sample')
        seen.add(key)
        task = tasks[key[0]]; scored = reward(task, s)
        rows.append(dict(s, score=scored))
        groups[key[0]].append(scored)
        for cell in ('all', f"lesson/{task['b_lesson']}", f"level/{task['b_lesson_level']}",
                     f"skill/{task['skill']}", f"split/{task['split']}"):
            cells[cell].append(scored)
    summary = {}
    for key, rs in cells.items():
        valid = [r for r in rs if r['reward'] is not None]
        summary[key] = dict(responses=len(rs), infrastructure_failures=len(rs)-len(valid),
            correct=sum(bool(r['correct']) for r in valid),
            truncated=sum(r['status'] == 'truncated' for r in valid),
            format_failure=sum(r['status'] == 'format_failure' for r in valid),
            set_only_correct=sum(bool(r.get('set_exact')) and not r['correct'] for r in valid),
            wrong_fullset=sum(r.get('predicted_full_set', False) and not r['correct'] for r in valid))
    group_counts = Counter(); task_groups = {}
    for tid in allowed:
        rs = groups[tid]
        if len(rs) != manifest['group_size'] or any(r['reward'] is None for r in rs):
            category = 'incomplete_or_infrastructure_failure'
        else:
            correct = sum(r['correct'] for r in rs)
            category = 'all_wrong' if correct == 0 else 'all_correct' if correct == len(rs) else 'mixed'
        task_groups[tid] = category
        group_counts[category] += 1
    for key, cell in summary.items():
        ids = [tid for tid in allowed if key in ('all', f"lesson/{tasks[tid]['b_lesson']}",
            f"level/{tasks[tid]['b_lesson_level']}", f"skill/{tasks[tid]['skill']}", f"split/{tasks[tid]['split']}")]
        cell['groups'] = dict(Counter(task_groups[tid] for tid in ids))
    return dict(planned=manifest['formal_requests'], received=len(rows), cells=summary,
                groups=dict(group_counts), learner_parameters_updated=False), rows


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--pack', default='examples/social_bp/b_response_bridges_v1')
    p.add_argument('--samples', required=True); p.add_argument('--out', required=True)
    a = p.parse_args(); summary, rows = score_run(a.pack, a.samples)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=False)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (out/'scored.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    print(json.dumps(summary, indent=2))
