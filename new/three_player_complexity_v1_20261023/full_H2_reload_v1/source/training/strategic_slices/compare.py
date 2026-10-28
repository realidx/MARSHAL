"""Paired frozen-test comparison and token-indexed validation curves."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
from .common import write_json
from .evaluate import interval


def compare(sp, slices):
    left = json.loads((sp / 'summary.json').read_text())
    right = json.loads((slices / 'summary.json').read_text())
    for folder in (sp, slices):
        if not (folder / 'COMPLETE.json').is_file():
            raise ValueError('Both evaluations must complete')
    for key in ('version', 'dataset_sha256', 'split', 'modes', 'repeats', 'temperature', 'max_tokens', 'seed'):
        if left['protocol'].get(key) != right['protocol'].get(key):
            raise ValueError('Evaluation protocols differ: ' + key)
    def load(folder):
        rows = [json.loads(line) for line in (folder / 'games.jsonl').read_text().splitlines()]
        by = {(r['mode'], r['parent_id'], r['seed'], r['focal'], r['slice_id']): r for r in rows}
        if len(by) != len(rows):
            raise ValueError('Duplicate evaluation pairs')
        return by
    a, b = load(sp), load(slices)
    if a.keys() != b.keys():
        raise ValueError('Evaluation cases differ')
    grouped, completion, counts = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list)), defaultdict(int)
    for key, x in a.items():
        y = b[key]
        if x['world'] != y['world']:
            raise ValueError('Paired hidden worlds differ')
        mode, parent = x['mode'], x['parent_id']
        if x.get('utility_scope', 'native-terminal') != y.get('utility_scope', 'native-terminal'):
            raise ValueError('Paired utility objectives differ')
        x_done = x.get('completed', x['status'] == 'terminal')
        y_done = y.get('completed', y['status'] == 'terminal')
        completion[mode][parent].append(int(y_done) - int(x_done))
        counts[mode + '/pairs'] += 1
        if x_done and y_done:
            def utility(r):
                values = r.get('objective_utility', r['terminal_utility'])
                return values[r['focal']] if r['focal'] is not None else np.mean(values)
            grouped[mode][parent].append(float(utility(y) - utility(x)))
            counts[mode + '/both_complete'] += 1
    return dict(direction='slices minus SP', protocol=left['protocol'],
                paired_utility_completed_parent_macro={m: interval([np.mean(v) for v in ps.values()]) for m, ps in grouped.items()},
                paired_completion_parent_macro={m: interval([np.mean(v) for v in ps.values()]) for m, ps in completion.items()},
                coverage=dict(counts),
                limitation='Utility differences condition on both runs completing; read completion differences and each cohort utility bound alongside them.')


def curves(folder):
    if folder is None:
        return None
    points = []
    for path in (folder / 'validation').glob('step-*.json'):
        report = json.loads(path.read_text())
        points.append(dict(tokens=report['training_response_tokens'], updates=report['completed_updates'], metrics=report['metrics']))
    return sorted(points, key=lambda p: (p['tokens'], p['updates']))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--sp', required=True, type=Path)
    cli.add_argument('--slices', required=True, type=Path)
    cli.add_argument('--sp-training', type=Path)
    cli.add_argument('--slices-training', type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    result = compare(args.sp, args.slices)
    result['learning_curves'] = dict(sp=curves(args.sp_training), slices=curves(args.slices_training))
    write_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'learning_curves'}, indent=2))


if __name__ == '__main__':
    main()
