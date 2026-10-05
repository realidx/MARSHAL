"""Resumable, deterministic production freeze of the bounded shared-parent corpus.

Independent worker processes only compute candidates. Their completion order
never assigns splits or selects examples. Every result (including rejection)
is cached under its exact input/config/source identity and atomically saved.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from training.b_sft.preference_contract import profile
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .bounded import resolve_horizon
from .bounded_data import BACKEND, CONTRACT, public_entrances, select_bounded_slices
from .build import sample_parent, structural_family
from .common import VERSION, digest, file_hash, stable, write_json, write_rows
from .coverage_pool import candidates as coverage_candidates

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ('train', 'validation', 'test')


def source_identity():
    folders = ('training/strategic_slices', 'training/b_sft', 'new/benac_slice_pilot',
               'third_party/negotiation_benchmark/src')
    return {str(p.relative_to(ROOT)): file_hash(p) for folder in folders
            for p in sorted((ROOT / folder).rglob('*.py'))}


def parent_identity(raw):
    # Different sampled entrances or provenance never manufacture new parents.
    return digest({k: v for k, v in raw.items() if k not in ('slice_setup_histories', 'generation')})[:24]


def candidate(index, config):
    """16 labeled acquisition candidates, then an independent random 2:1 pool."""
    supplemental = 16
    if index < supplemental:
        raw = deepcopy(coverage_candidates()[index // 2])
        raw['background_prior'] = profile(('balanced', 'want_heavy')[index % 2])
        origin = dict(kind='source-derived-information-acquisition', scoring_mask=index // 2,
                      prior=raw['background_prior']['name'])
    else:
        offset = index - supplemental
        players = 3 if offset % 3 == 2 else 2
        raw = sample_parent(config['seed'] + offset, players, rounds=3)
        support = None
        if players == 3:
            variables = [(p, g) for p, rows in raw['type_catalogues'].items()
                         for g in range(len(rows[0])) if len({r[g] for r in rows}) > 1]
            keep = sorted(variables, key=lambda cell: digest((config['seed'] + index, cell)))[
                :config['three_player_variable_slots']]
            for p, rows in raw['type_catalogues'].items():
                baseline = rows[int(digest((config['seed'] + index, p))[:8], 16) % len(rows)]
                raw['type_catalogues'][p] = [r for r in rows if all(
                    r[g] == baseline[g] for g in range(len(r)) if (p, g) not in keep)]
            raw['own_preferences'] = raw['type_catalogues']['0'][0]
            support = dict(original_variable_slots=len(variables), retained_variable_slots=keep,
                           fixed_values='Seeded uniform catalogue draw; independent of oracle and model')
        rules = PrivateInvestigationRules(raw)
        # Initial root plus one independently sampled interior information
        # context; the public history selection sees no hidden preferences.
        choices = public_entrances(rules, config['seed'] + offset, 4, 100)
        eligible = [(h, n) for h, n in choices if h and
                    resolve_horizon(rules, n)['next_own_proposal_included']]
        if eligible:
            history, _ = min(eligible, key=lambda item: digest((config['seed'], offset, item[0])))
            raw['slice_setup_histories'] = [[], list(history)]
        else:
            raw['slice_setup_histories'] = [[]]
        origin = dict(kind='native-random-three-round', generator_seed=config['seed'] + offset,
                      private_support=support)
    return dict(index=index, seed=config['seed'] + index, raw=raw, origin=origin,
                parent_id=parent_identity(raw), family=structural_family(raw['game']),
                players=raw['game']['n_players'])


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    write_json(temporary, value)
    temporary.replace(path)


def worker(path):
    request = json.loads((path / 'request.json').read_text())
    item, config = request['candidate'], request['config']
    start = time.monotonic()
    (path / 'references').mkdir(exist_ok=True)
    result = dict(candidate=item, cache_key=request['cache_key'], source_sha256=request['source_sha256'])
    try:
        participants = {a['player_id'] for g in item['raw']['game']['goals'] for a in g['required_actions']}
        if len(participants) != item['players']:
            result.update(status='excluded', slices=[], references={}, world_weights=[],
                          entrances_sampled=0, diagnostics=[], reason='Isolated player')
            result['seconds'] = time.monotonic() - start
            atomic_json(path / 'result.json', result)
            return
        solve_config = dict(config)
        if item['origin']['kind'] == 'native-random-three-round':
            solve_config['lookahead_depths'] = config['random_lookahead_depths']
            solve_config['require_initial_reference'] = True
        selected, entrances, diagnostic, references, prior = select_bounded_slices(
            item['raw'], item['parent_id'], item['seed'], solve_config, path)
        # A parent whose initial context is outside the reference domain is
        # unsuitable for the planned complete-game focal-reference evaluation.
        root = next((d for d in diagnostic if not d['history'] and d['lookahead_rr'] == 1), None)
        needs_root = item['origin']['kind'] == 'native-random-three-round'
        eligible = bool(selected) and (not needs_root or (root and root['status'] == 'certified'))
        result.update(status='qualified' if eligible else 'excluded', slices=selected if eligible else [],
            references=references if eligible else {}, world_weights=prior, entrances_sampled=entrances,
            diagnostics=diagnostic, reason=None if eligible else 'No consequential slices or uncertified initial reference context')
    except Exception as exc:
        # SciPy can report this numerical breakdown as ValueError rather than
        # NoConvergence. It supplies no certified profile: reject the entire
        # candidate, retaining the exception, just as for a search-budget miss.
        # Other ValueErrors remain infrastructure failures and stop the build.
        if isinstance(exc, ValueError) and str(exc) == (
                'Jacobian inversion yielded zero vector. This indicates a bug in the Jacobian approximation.'):
            result.update(status='excluded', error=repr(exc), slices=[], references={},
                world_weights=[], entrances_sampled=0, diagnostics=[],
                reason='SciPy Jacobian nonconvergence; entire candidate excluded with no oracle label')
        else:
            result.update(status='error', error=repr(exc))
    result['seconds'] = time.monotonic() - start
    atomic_json(path / 'result.json', result)


def cached_candidate(item, config, sources, cache):
    request = dict(candidate=item, config=config, source_sha256=sources)
    key = digest(request); request['cache_key'] = key
    path = cache / key; path.mkdir(parents=True, exist_ok=True)
    if (path / 'result.json').exists():
        result = json.loads((path / 'result.json').read_text())
        if result['cache_key'] != key or result['source_sha256'] != sources:
            raise ValueError('Candidate cache identity mismatch')
    else:
        atomic_json(path / 'request.json', request)
        env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with (path / 'worker.log').open('w') as log:
            completed = subprocess.run([sys.executable, '-m', 'training.strategic_slices.freeze', '--worker', str(path)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            raise RuntimeError(f'Candidate worker exited {completed.returncode}: {path}')
        result = json.loads((path / 'result.json').read_text())
    if result['status'] == 'error':
        raise RuntimeError(f'Candidate infrastructure error: {result["error"]}; {path}')
    for reference in result.get('references', {}).values():
        if file_hash(path / reference['reference_file']) != reference['reference_sha256']:
            raise ValueError('Candidate reference checksum changed')
    return result, path


def freeze(output, cache, config, workers=3):
    sources = source_identity()
    output.mkdir(parents=True, exist_ok=True); cache.mkdir(parents=True, exist_ok=True)
    if (output / 'COMPLETE.json').exists():
        raise ValueError('Dataset is already complete; use its audit/entrypoints')
    contract = dict(config=config, source_sha256=sources)
    contract_path = output / 'build_contract.json'
    if contract_path.exists() and json.loads(contract_path.read_text()) != contract:
        raise ValueError('Resume requires unchanged config and sources; previous results remain intact')
    atomic_json(contract_path, contract)
    (output / 'references').mkdir(exist_ok=True)
    parents = {s: [] for s in SPLITS}; slices = {s: [] for s in SPLITS}
    counts = {s: Counter() for s in SPLITS}; families = Counter(); family_splits = {}; seen = set()
    positive = Counter()
    targets = {s: {3: round(config[s] / 3), 2: config[s] - round(config[s] / 3)} for s in SPLITS}
    required_positive = {s: max(1, round(config[s] * .05)) for s in SPLITS}
    started = time.monotonic(); log_rows = []
    def full():
        return all(counts[s][p] == targets[s][p] for s in SPLITS for p in (2, 3))
    def eligible(item):
        n, family = item['players'], item['family']
        if all(counts[s][n] == targets[s][n] for s in SPLITS):
            return False
        assigned = family_splits.get(family)
        return (item['parent_id'] not in seen and families[family] < config['max_per_family']
                and (assigned is None or counts[assigned][n] < targets[assigned][n]))
    # The producer has a bounded lookahead; unused speculative computations
    # remain cache evidence and never enter the selected corpus or its counts.
    with ThreadPoolExecutor(max_workers=workers) as executor, (output / 'generation_log.jsonl').open('w') as log:
        pending = {}; next_submit = 0
        for index in range(config['max_attempts']):
            while next_submit < min(config['max_attempts'], index + workers * 4):
                item = candidate(next_submit, config)
                future = executor.submit(cached_candidate, item, config, sources, cache) if eligible(item) else None
                pending[next_submit] = (item, future); next_submit += 1
            item, future = pending.pop(index)
            row = {k: item[k] for k in ('index', 'seed', 'parent_id', 'family', 'players', 'origin')}
            if future is None:
                row['status'] = 'quota_or_duplicate'
            else:
                result, source = future.result()
                row.update(status=result['status'], seconds=result['seconds'], cache_key=result['cache_key'],
                           reason=result.get('reason'), diagnostics=result['diagnostics'])
                if result['status'] == 'qualified' and eligible(item):
                    n, family = item['players'], item['family']
                    split = family_splits.get(family) or min((s for s in SPLITS if counts[s][n] < targets[s][n]),
                        key=lambda s: (counts[s][n] / targets[s][n], digest((family, s))))
                    has_positive = any(s['information_positive'] for s in result['slices'])
                    remaining = config[split] - sum(counts[split].values())
                    if not has_positive and remaining <= required_positive[split] - positive[split]:
                        row.update(status='excluded', reason='Remaining slots reserved for positive-S coverage')
                    else:
                        references = result['references']
                        for reference in references.values():
                            shutil.copyfile(source / reference['reference_file'], output / reference['reference_file'])
                        parent = dict(id=item['parent_id'], family=family, split=split, seed=item['seed'],
                            players=n, raw=item['raw'], origin=item['origin'], reference_backend=BACKEND,
                            bounded_references=references, world_weights=result['world_weights'],
                            native_audit={k: r['native_audit'] for k, r in references.items()},
                            entrances_sampled=result['entrances_sampled'], slices=len(result['slices']))
                        parents[split].append(parent)
                        slices[split].extend(dict(s, split=split) for s in result['slices'])
                        counts[split][n] += 1; families[family] += 1; family_splits[family] = split
                        seen.add(parent['id']); positive[split] += int(has_positive)
                        row.update(status='accepted', split=split, slices=parent['slices'])
                        for kind, records in (('parents', parents[split]), ('slices', slices[split])):
                            write_rows(output / f'{split}_{kind}.jsonl', records)
                        print(stable(dict(index=index, accepted=len(seen), counts=counts, positive=positive,
                                          elapsed_seconds=time.monotonic()-started)), flush=True)
                elif result['status'] == 'qualified':
                    row['status'] = 'quota_or_duplicate'
            log_rows.append(row); log.write(stable(row)+'\n'); log.flush()
            atomic_json(output / 'progress.json', dict(processed=index+1, accepted=len(seen), counts=counts,
                positive=positive, elapsed_seconds=time.monotonic()-started))
            if full():
                for _, queued in pending.values():
                    if queued is not None:
                        queued.cancel()
                break
    files = {}
    for split in SPLITS:
        for kind, records in (('parents', parents[split]), ('slices', slices[split])):
            name = f'{split}_{kind}.jsonl'; write_rows(output / name, records)
            files[name] = dict(rows=len(records), sha256=file_hash(output / name))
    unchanged = sources == source_identity()
    complete = full() and unchanged and all(positive[s] >= required_positive[s] for s in SPLITS)
    manifest = dict(version=VERSION, config=config, files=files, counts=counts, targets=targets,
        complete=complete, training_contract=CONTRACT, source_sha256=sources, source_unchanged_during_build=unchanged,
        positive_S_parents=positive, minimum_positive_S_parents=required_positive,
        families={s: len({p['family'] for p in parents[s]}) for s in SPLITS},
        origins={s: dict(Counter(p['origin']['kind'] for p in parents[s])) for s in SPLITS},
        generation_attempts=len(log_rows), elapsed_seconds=time.monotonic()-started,
        sampling='Uniform shared parent then uniform retained slice; no D or model-dependent selection.',
        entry='Public uniformly sampled legal histories plus labeled exogenous acquisition prefixes; condition public prior on own type/private answers.',
        split='Whole canonical public structural family assigned deterministically to underfilled player quota; max eight parents per family.',
        domain='Selected oracle-solvable native three-round 2/3-player games; 16 designed acquisition candidates followed by a seeded random pool. Two-player supports have at most three variable slots; three-player supports use the declared slot cap with other uncertain cells fixed by seeded draws.',
        limitations='Not random yield; acquisition variants share a source mechanism across scoring families. Full-game rolling-reference solves may fail on previously untested model histories.')
    atomic_json(output / 'manifest.json', manifest)
    if not complete:
        raise RuntimeError('Incomplete corpus: inspect progress, quotas, coverage and source identity')
    atomic_json(output / 'COMPLETE.json', dict(manifest_sha256=file_hash(output / 'manifest.json')))
    return manifest


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--worker', type=Path)
    cli.add_argument('--output', type=Path)
    cli.add_argument('--cache', type=Path)
    cli.add_argument('--workers', type=int, default=3)
    cli.add_argument('--max-attempts', type=int, default=2400)
    cli.add_argument('--seed', type=int, default=20261003)
    cli.add_argument('--solver-seconds', type=float, default=120.)
    cli.add_argument('--max-nodes', type=int, default=120000)
    cli.add_argument('--three-player-variable-slots', type=int, choices=(1, 2, 3), default=1)
    args = cli.parse_args()
    if args.worker:
        worker(args.worker); return
    if not args.output or not args.cache:
        cli.error('--output and --cache are required')
    config = dict(train=100, validation=20, test=40, reference_policy=BACKEND,
        seed=args.seed, max_attempts=args.max_attempts, max_nodes=args.max_nodes,
        solver_seconds=args.solver_seconds, max_k=3, max_entrances=2, entrance_trajectories=4,
        slices_per_parent=8, max_per_family=8, lookahead_rr=1, lookahead_depths=[1, 2], random_lookahead_depths=[1],
        max_joint_cells=4096, max_joint_evaluations=160, reach_epsilon=1.,
        min_c=.1, min_increment=.05, min_s=.05, two_player_rounds=3, three_player_rounds=3,
        three_player_fraction=1/3, three_player_variable_slots=args.three_player_variable_slots,
        production_generator='bounded-production-v2')
    print(stable(freeze(args.output.resolve(), args.cache.resolve(), config, args.workers)), flush=True)


if __name__ == '__main__':
    main()
