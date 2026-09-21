"""Search teacher-generated matched structures for semantic-B sufficiency."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from new.diagnostic_v4.build import VALUES, occupied_geometries
from new.diagnostic_v6.candidates import matched_candidate
from new.diagnostic_v6.semantic_sufficiency import certify
from training.b_sft.preference_contract import belief


OCCUPIED = None


def initialize(occupied):
    global OCCUPIED
    OCCUPIED = occupied


def check(seed):
    mode = 'binary' if seed % 2 == 0 else 'linear'
    try:
        candidate = matched_candidate(seed, mode, OCCUPIED)
    except Exception as exc:
        return seed, mode, 'error:' + type(exc).__name__, None
    if candidate is None:
        return seed, mode, 'ineligible', None
    judgments = []
    certificates = []
    for weights in (candidate['posterior'], candidate['prior']):
        judgment = belief(dict(zip(VALUES, map(float, weights))))
        judgments.append(judgment)
        certificates.append(certify(judgment, candidate['pay'].tolist()))
    if not all(item['decision_sufficient'] for item in certificates):
        return seed, mode, 'semantic_ambiguous', None
    return seed, mode, 'pass', {
        'seed': seed,
        'mode': mode,
        'structure_family': candidate['family'],
        'voluntary_posterior': candidate['posterior'].tolist(),
        'judgments': judgments,
        'invariant_optimal_action_indices': [
            item['invariant_optimal_action_indices'] for item in certificates],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=12000)
    parser.add_argument('--stop', type=int, default=20000)
    parser.add_argument('--per-mode', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--mode', choices=('binary', 'linear'))
    args = parser.parse_args()
    occupied, _ = occupied_geometries()
    counts = Counter()
    selected = []
    used = set()
    with ProcessPoolExecutor(max_workers=args.workers,
                             initializer=initialize,
                             initargs=(occupied,)) as pool:
        seeds = [seed for seed in range(args.start, args.stop)
                 if args.mode is None or
                 ('binary' if seed % 2 == 0 else 'linear') == args.mode]
        for number, result in enumerate(
                pool.map(check, seeds, chunksize=1), 1):
            seed, mode, status, record = result
            counts[(mode, status)] += 1
            if record is not None and record['structure_family'] not in used:
                if sum(item['mode'] == mode for item in selected) < args.per_mode:
                    selected.append(record)
                    used.add(record['structure_family'])
                    print(json.dumps({'selected': record}), flush=True)
            if number % 250 == 0:
                print(json.dumps({'through_seed': seed,
                                  'selected_by_mode': dict(Counter(
                                      item['mode'] for item in selected)),
                                  'counts': {'|'.join(key): value
                                             for key, value in counts.items()}}),
                      flush=True)
            by_mode = Counter(item['mode'] for item in selected)
            targets = (args.mode,) if args.mode else ('binary', 'linear')
            if all(by_mode[mode] >= args.per_mode for mode in targets):
                break
    print(json.dumps({'selected': selected,
                      'counts': {'|'.join(key): value
                                 for key, value in counts.items()}}, indent=2))


if __name__ == '__main__':
    main()
