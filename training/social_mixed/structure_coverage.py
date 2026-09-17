"""Exact small-game dependency isomorphism audit, independent of names/priors.

Geometry deliberately ignores scoring, timing and preference worlds so variants
cannot masquerade as held-out structures. Those dimensions are reported separately.
"""
import argparse
from collections import Counter, defaultdict
from itertools import permutations, product
import hashlib
import json
from pathlib import Path


def geometry_id(game):
    n = game['n_players']
    counts = game['n_actions_per_player']
    if n > 4 or max(counts) > 4:
        raise ValueError('Exact canonicalization budget exceeded; do not approximate silently')
    best = None
    for players in permutations(range(n)):
        for actions in product(*(permutations(range(c)) for c in counts)):
            sizes = [0] * n
            for p in range(n):
                sizes[players[p]] = counts[p]
            goals = sorted(tuple(sorted((players[r['player_id']], actions[r['player_id']][r['action_id']])
                                        for r in g['required_actions'])) for g in game['goals'])
            candidate = (tuple(sizes), tuple(goals))
            if best is None or candidate < best:
                best = candidate
    return hashlib.sha256(repr(best).encode()).hexdigest()[:24]


def audit(folder):
    memberships = defaultdict(set)
    counts = {}
    records = []
    for path in sorted(folder.glob('*.jsonl')):
        if path.stem not in ('bp_train', 'bp_validation', 'bp_test', 'selfplay_train', 'selfplay_validation', 'selfplay_test'):
            continue
        cells = Counter()
        for line in path.read_text().splitlines():
            row = json.loads(line)
            game = row.get('input', row.get('raw', {}))['game']
            family = geometry_id(game)
            split = path.stem.split('_')[-1]
            memberships[family].add(split)
            mode = 'binary' if all(g['binary'] for g in game['goals']) else 'linear' if not any(g['binary'] for g in game['goals']) else 'mixed'
            cell = (row.get('kernel', 'selfplay'), mode, row.get('information_role', 'na'))
            cells['/'.join(cell)] += 1
            records.append(dict(id=row['id'], source=path.name, structure_family=family,
                                mode=mode, timing=game['round_robin'], split=split,
                                origin_id=row.get('origin_id', row.get('geometry_source_id'))))
        counts[path.stem] = dict(sorted(cells.items()))
    overlaps = {k: sorted(v) for k, v in memberships.items() if len(v) > 1}
    return dict(counts=counts, structure_families=len(memberships), cross_split_families=overlaps,
                independent_structure_test_ready=bool(any(r['split']=='test' for r in records)) and not overlaps,
                scope='Exact dependency geometry up to player, commitment and goal permutation; multiplicities retained. Scoring/timing/prior variants share a family. Existing evaluated validation remains development.', records=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='records'}, indent=2))

if __name__ == '__main__':
    main()
