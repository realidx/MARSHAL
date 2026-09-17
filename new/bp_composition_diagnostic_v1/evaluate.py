"""Strict offline scoring, coverage, and same-case composition diagnostics."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json

from prepare import HERE, ROOT, CONDITIONS, sha, request
from training.b_sft.social_bp_training import reward


def load():
    m = json.loads((HERE / 'manifest.json').read_text())
    for name, expected in m['dependencies'].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f'Diagnostic dependency changed: {name}; rebuild and review explicitly')
    for name, expected in m['files'].items():
        if sha(HERE / name) != expected:
            raise ValueError(f'Diagnostic artifact changed: {name}')
    tasks = {t['id']: t for t in map(json.loads, (HERE / 'tasks.jsonl').read_text().splitlines())}
    requests = {r['task_id']: r for r in map(json.loads, (HERE / 'requests.jsonl').read_text().splitlines())}
    if tasks.keys() != requests.keys():
        raise ValueError('Task/request coverage mismatch')
    for tid, task in tasks.items():
        if request(task) != requests[tid]['request']:
            raise ValueError(f'Frozen request differs from current rendering: {tid}')
    return m, tasks, requests


def summarize(records, tasks, repeats):
    if repeats < 1: raise ValueError('Positive repeats required')
    indexed = {}; scored = []
    for r in records:
        tid, replica = r['task_id'], r['replica']
        if tid not in tasks or type(replica) is not int or not 0 <= replica < repeats:
            raise ValueError('Unexpected task or replica')
        if (tid, replica) in indexed: raise ValueError('Duplicate task/replica')
        t = tasks[tid]; s = reward(t, r['completion'])
        row = dict(task_id=tid, case_id=t['case_id'], family=t['family'], condition=t['condition'],
                   replica=replica, score=s)
        indexed[tid, replica] = row; scored.append(row)
    def metric(ids):
        rows = [indexed[tid, rep] for tid in ids for rep in range(repeats) if (tid, rep) in indexed]
        n = len(ids) * repeats; statuses = Counter(r['score']['status'] for r in rows)
        correct = sum(r['score']['correct'] is True for r in rows)
        legal = statuses['ok']; failures = statuses['infrastructure_failure']
        complete = len(rows) == n and not failures
        return dict(planned=n, returned=len(rows), missing=n - len(rows), statuses=dict(statuses),
            correct=correct, legal=legal, complete=complete,
            accuracy=correct / n if complete else None, legal_rate=legal / n if complete else None,
            observed_correct_over_planned=correct / n)
    per_condition = {c: metric([tid for tid, t in tasks.items() if t['condition'] == c]) for c in CONDITIONS}
    per_case = {case: {c: metric([tid for tid, t in tasks.items() if t['case_id'] == case and t['condition'] == c])
                      for c in CONDITIONS} for case in sorted({t['case_id'] for t in tasks.values()})}
    triples = Counter(); paired_gain = []; complete_triples = 0
    for case in per_case:
        ids = {t['condition']: tid for tid, t in tasks.items() if t['case_id'] == case}
        for rep in range(repeats):
            rows = [indexed.get((ids[c], rep)) for c in CONDITIONS]
            if any(r is None or r['score']['correct'] is None for r in rows): continue
            bits = [int(r['score']['correct']) for r in rows]
            triples[f'B{bits[0]}_gold{bits[1]}_infer{bits[2]}'] += 1
            paired_gain.append(bits[1] - bits[2]); complete_triples += 1
    controls = {}
    for family in sorted({t['family'] for t in tasks.values()}):
        controls[family] = {}
        for c in CONDITIONS:
            pairs = []
            for rep in range(repeats):
                rows = [indexed.get((f'{family}:{p}:{c}', rep)) for p in ('voluntary', 'preset')]
                if any(r is None or r['score']['correct'] is None for r in rows): continue
                pairs.append(all(r['score']['correct'] for r in rows))
            controls[family][c] = dict(complete_pairs=len(pairs), planned_pairs=repeats,
                                       both_correct=sum(pairs), pair_accuracy=sum(pairs) / repeats if len(pairs) == repeats else None)
    summary = dict(overall=metric(list(tasks)), by_condition=per_condition, by_case=per_case,
        complete_triples=complete_triples, planned_triples=len(per_case) * repeats,
        joint_outcome_counts=dict(triples),
        gold_minus_infer_accuracy_on_complete_triples=sum(paired_gain) / len(paired_gain) if paired_gain else None,
        evidence_provenance_controls=controls,
        interpretation='Conditions use independent calls, not a chained B-to-P conversation. '
        'Invalid/truncated answers count as failures. Missing/infra failures prevent complete-run accuracy. '
        'Joint rows pair independent calls by case and replica; they do not observe one shared internal belief. '
        'Two structural families only; no broad generalization or independent-rollout confidence interval.')
    return summary, scored


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--check', action='store_true')
    p.add_argument('--responses', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--repeats', type=int, default=8)
    a = p.parse_args(); m, tasks, _ = load()
    if a.check:
        print(json.dumps(dict(status='verified', tasks=len(tasks), cases=m['cases'], model_calls=0))); return
    if not a.responses or not a.output: p.error('--responses and --output required')
    records = [json.loads(line) for line in a.responses.read_text().splitlines() if line.strip()]
    summary, scored = summarize(records, tasks, a.repeats)
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (a.output / 'scored.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in scored))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
