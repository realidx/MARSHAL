"""Paired native initial-oracle pilot for optional multi-action goal generation.

Pairs differ in one added same-player goal requirement. Select seeds using
structural eligibility only, before any solve. Failed arms are never zero-S
observations; incomplete pairs are reported separately. No frozen data changes.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from examples.strategic_slices.search_native_acquisition import evaluate_parent
from training.strategic_slices.build import sample_parent, with_multi_action_goal, structural_family
from training.strategic_slices.common import file_hash, write_json


def worker(job):
    raw, name, out, seconds, seed, arm, family = job
    return evaluate_parent(raw, name, out, seconds, 160000, seed=seed, arm=arm, family=family)


def summarize(pairs, results):
    by_name = {r['name']: r for r in results}
    paired = []
    for pair in pairs:
        arms = {arm: by_name.get(pair['names'][arm]) for arm in ('legacy', 'multi_action')}
        complete = all(r is not None and r['status'] == 'certified' for r in arms.values())
        paired.append(dict(seed=pair['seed'], change=pair['change'], both_certified=complete,
            statuses={a: r['status'] if r else 'pending' for a, r in arms.items()},
            S_difference=(arms['multi_action']['max_measured_S']-arms['legacy']['max_measured_S']) if complete else None))
    arms = {}
    for arm in ('legacy', 'multi_action'):
        rs = [r for r in results if r['arm'] == arm]
        strong = [r for r in rs if r.get('strong_witnesses', 0) > 0]
        arms[arm] = dict(attempted=len(rs), certified=sum(r['status']=='certified' for r in rs),
            strong_parents=len(strong), strong_structural_families=sorted({r['family'] for r in strong}))
    return dict(arms=arms, pairs=paired, results=results,
        interpretation='Small paired pilot in structurally eligible three-player one-round games. Not a population yield estimate or a claim about all equilibria. Only certified pairs admit a value comparison; null means unavailable, never zero.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=2026101500)
    p.add_argument('--pairs', type=int, default=8)
    p.add_argument('--seconds', type=float, default=45)
    p.add_argument('--workers', type=int, default=2)
    args = p.parse_args()
    if min(args.pairs, args.seconds, args.workers) <= 0:
        raise ValueError('Positive pair count, seconds and workers required')
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise ValueError('Use an empty output directory')
    pairs, jobs, skipped = [], [], []
    for seed in range(args.seed, args.seed+10000):
        old = sample_parent(seed, 3, rounds=1)
        new, change = with_multi_action_goal(old, seed)
        if change is None:
            skipped.append(dict(seed=seed, reason='no_same_player_requirement_available'))
            continue
        names = {arm: f'{seed}_{arm}' for arm in ('legacy', 'multi_action')}
        families = {arm: structural_family(raw['game']) for arm, raw in [('legacy', old), ('multi_action', new)]}
        assert families['legacy'] != families['multi_action']
        pairs.append(dict(seed=seed, names=names, change=change, families=families))
        for arm, raw in [('legacy', old), ('multi_action', new)]:
            jobs.append((raw, names[arm], args.output, args.seconds, seed, arm, families[arm]))
        if len(pairs) == args.pairs:
            break
    if len(pairs) != args.pairs:
        raise RuntimeError('Not enough structurally eligible seeds')
    sources = [Path(__file__), Path('training/strategic_slices/build.py'),
               Path('examples/strategic_slices/search_native_acquisition.py')]
    for source in sources:
        (args.output / (source.stem+'_source.py')).write_text(source.read_text())
    write_json(args.output/'config.json', dict(seed=args.seed, pairs=pairs, skipped_before_solve=skipped,
        seconds=args.seconds, workers=args.workers, max_nodes=160000, min_C=.1, min_S=.05,
        source_sha256={str(p):file_hash(p) for p in sources},
        fixed_fields=['preferences', 'type_catalogues', 'prior', 'schedule', 'coordinate_counts', 'goal_modes', 'native_rules'],
        scope='Initial terminal oracle for each arm; no external prefixes or model calls. Probe first-proposal active acquisition using existing C/S definitions.'))
    # Persist the exact pair before any solver starts.
    write_json(args.output/'jobs.json', [dict(raw=j[0], name=j[1], seed=j[4], arm=j[5], family=j[6]) for j in jobs])
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(worker, jobs):
            results.append(result)
            write_json(args.output/'summary.json', summarize(pairs, results))
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
