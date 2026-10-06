"""Native structural neighbors of validated acquisition mechanisms.

No added dummy goals, scaling, preference changes, or renamed duplicates.
Each candidate changes a goal's actual requirements/mode or legal turn order;
canonical structural families are deduplicated before any oracle solve.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from itertools import combinations, permutations
import json
from pathlib import Path

from examples.strategic_slices.search_native_acquisition import evaluate_parent
from training.strategic_slices.build import structural_family
from training.strategic_slices.common import file_hash, write_json


def neighbors(raw):
    game = raw['game']
    atoms = [(p, a) for p, n in enumerate(game['n_actions_per_player']) for a in range(n)]
    geometries = [c for size in range(2, len(atoms)+1) for c in combinations(atoms, size)
                  if len({p for p, _ in c}) >= 2]
    for gi, goal in enumerate(game['goals']):
        old = tuple((a['player_id'], a['action_id']) for a in goal['required_actions'])
        for new in geometries:
            if new == old:
                continue
            variant = deepcopy(raw)
            variant['game']['goals'][gi]['required_actions'] = [dict(player_id=p, action_id=a) for p, a in new]
            # Equal-mode duplicate goals can amount to payoff reweighting.
            keys = [(g['binary'], tuple((a['player_id'], a['action_id']) for a in g['required_actions']))
                    for g in variant['game']['goals']]
            if len(set(keys)) != len(keys):
                continue
            yield dict(kind='requirements', goal=gi, before=old, after=new), variant
        variant = deepcopy(raw)
        variant['game']['goals'][gi]['binary'] = not goal['binary']
        yield dict(kind='goal_mode', goal=gi), variant
    n = game['n_players']
    for order in permutations(range(n)):
        schedule = list(order)*(len(game['round_robin'])//n)
        if schedule != game['round_robin']:
            variant = deepcopy(raw)
            variant['game']['round_robin'] = schedule
            yield dict(kind='schedule', schedule=schedule), variant


def worker(job):
    raw, name, out, seconds, family, change = job
    return evaluate_parent(raw, name, out, seconds, 160000, family=family, change=change)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, default=Path('examples/strategic_slices/fixtures/native_acquisition_three_player.json'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=45)
    p.add_argument('--workers', type=int, default=2)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise ValueError('Use an empty output directory')
    raw = json.loads(args.fixture.read_text())['raw']
    seen = {structural_family(raw['game'])}
    jobs = []
    for change, variant in neighbors(raw):
        family = structural_family(variant['game'])
        if family in seen:
            continue
        seen.add(family)
        jobs.append((variant, f'neighbor_{len(jobs):03d}', args.output, args.seconds, family, change))
    sources = [Path(__file__), Path('examples/strategic_slices/search_native_acquisition.py')]
    for source in sources:
        (args.output/(source.stem+'_source.py')).write_text(source.read_text())
    write_json(args.output/'config.json', dict(fixture_sha256=file_hash(args.fixture),
        source_sha256={str(s):file_hash(s) for s in sources}, seconds=args.seconds, workers=args.workers,
        target='5–10 structurally distinct certified acquisition families including existing prototypes',
        fixed_fields=['preferences', 'catalogues', 'prior', 'goal_count', 'action_coordinates', 'native_rules'],
        note='All predeclared neighbors are attempted; no outcome-based renaming, scaling or early success stopping.'))
    write_json(args.output/'jobs.json', [dict(raw=j[0], name=j[1], family=j[4], change=j[5]) for j in jobs])
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(worker, jobs):
            results.append(result)
            write_json(args.output/'summary.json', dict(results=results, attempted=len(results),
                certified=sum(r['status']=='certified' for r in results),
                strong_families=[r['family'] for r in results if r.get('strong_witnesses',0)>0]))
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
