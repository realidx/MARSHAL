"""Search small NEW native parents for reachable active information value.

This diagnostic never edits the frozen corpus. Every attempt is recorded,
including solver failures. Catalogues are declared before solving; no support
is dropped, no prefix is forced, and all tree leaves must be native terminal.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from itertools import combinations, product
import json
from pathlib import Path
import time

import numpy as np

from training.b_sft.catalogues import validate_catalogues
from training.b_sft.preference_contract import profile, world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import digest, file_hash, save_reference, write_json
from training.strategic_slices.diagnose_bounded import count_bounded_nodes
from training.strategic_slices.early_investigation import measure_early_investigation
from training.strategic_slices.values import masked_answer_value, window_values


def candidate(seed, geometry):
    rng = np.random.default_rng(seed)
    if geometry in ('fixture', 'historical'):
        raw = deepcopy(json.loads(Path('examples/strategic_slices/fixtures/information_acquisition.json').read_text())['raw'])
        # New parents with the old payoff topology but different public types.
        count = len(raw['game']['goals'])
    else:
        coordinates = {'compact': [2, 1], 'three': [1, 1, 1],
                       'three_rich': [1, 1, 2], 'three_targeted': [2, 1, 1]}[geometry]
        atoms = [(p, a) for p, n in enumerate(coordinates) for a in range(n)]
        possible = [x for arity in (2, 3) for x in combinations(atoms, arity)
                    if len({p for p, _ in x}) >= 2]
        count = 4 if geometry in ('three_rich', 'three_targeted') else 3
        chosen = rng.choice(len(possible), count, replace=False)
        raw = dict(game=dict(n_players=len(coordinates), n_actions_per_player=coordinates,
            goals=[dict(goal_id=g, binary=bool(seed % 3 == 0 or (seed % 3 == 2 and rng.integers(2))),
                required_actions=[dict(player_id=p, action_id=a) for p, a in possible[i]])
                for g, i in enumerate(chosen)], max_changes=1, menu_enabled=False), ego=0)
        if geometry == 'three_targeted':
            for goal in raw['game']['goals']:
                goal['binary'] = seed % 2 == 0 or bool(rng.integers(2))
    raw['game']['round_robin'] = ([0, 1, 2] if geometry.startswith('three') else
        [[0, 1, 0, 1], [0, 1, 1, 0], [1, 0, 0, 1], [1, 0, 1, 0]][seed % 4])
    if geometry == 'historical':
        return raw
    # Public type catalogues can correlate a player's goal preferences. Each
    # profile still wants a goal; every joint world has non-neutral goals.
    possible_types = [list(row) for row in product((-1, 0, 1), repeat=count) if 1 in row]
    for _ in range(10000):
        types = {'0': [possible_types[int(rng.integers(len(possible_types)))]],
                 '1': [possible_types[int(i)] for i in rng.choice(len(possible_types), 3, replace=False)]}
        if geometry.startswith('three'):
            types['2'] = [possible_types[int(rng.integers(len(possible_types)))]]
            if seed % 2:
                types['1'], types['2'] = types['2'], types['1']
        if geometry == 'three_targeted':
            types = {str(p): [possible_types[int(rng.integers(len(possible_types)))]] for p in range(3)}
            # Only one hidden slot: this prevents alternate queries from
            # substituting for the masked answer in the existing S definition.
            slot = int(rng.integers(count))
            base = types['2'][0]
            types['2'] = [base[:slot] + [v] + base[slot+1:] for v in (-1, 0, 1)]
        raw.update(type_catalogues=types, own_preferences=types['0'][0], background_prior=profile('balanced'))
        try:
            validate_catalogues(raw)
            return raw
        except ValueError:
            pass
    raise RuntimeError('Could not generate valid public catalogues')


def attempt(args):
    seed, geometry, out, seconds, max_nodes = args
    name = f'{geometry}_{seed:05d}'
    raw = candidate(seed, geometry)
    return evaluate_parent(raw, name, out, seconds, max_nodes, seed=seed, geometry=geometry)


def evaluate_parent(raw, name, out, seconds, max_nodes, **metadata):
    write_json(out / f'{name}_raw.json', raw)
    result = dict(name=name, **metadata, raw_sha256=digest(raw), status='started')
    start = time.monotonic()
    try:
        rules = PrivateInvestigationRules(raw)
        count = count_bounded_nodes(rules, rules.initial(), len(rules.spec.round_robin))['unfolded_public_history_nodes']
        result.update(nodes=count, worlds=len(rules.worlds))
        if count > max_nodes:
            result.update(status='node_budget', oracle_label=None)
        else:
            tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                world_weights=world_weights(rules.worlds, raw['background_prior']),
                lookahead_rr=len(rules.spec.round_robin), max_nodes=max_nodes,
                seconds=seconds, large_tree_ordered_sweeps=8).solve()
            tree.deadline = time.monotonic() + 120
            audit = tree.audit_native()
            assert audit['cutoff_leaves'] == 0
            rows = measure_early_investigation(tree, name)
            masks = []
            for row in rows:
                if row['delta_investigate'] <= 1e-8:
                    continue
                for query in row['query_details']:
                    if not query['informative'] or query['Q'] < row['best_nonquery_value'] - 1e-8:
                        continue
                    slot = tuple(query['slot'])
                    value = masked_answer_value(tree, ego=row['ego'], root_index=row['root_index'],
                        root_weights=row['world_weights'], query_slot=slot, k=2*len(rules.spec.round_robin))
                    item = dict(entrance_id=row['id'], root_index=row['root_index'], ego=row['ego'],
                        own=row['own'], world_weights=row['world_weights'], history=row['history'],
                        slot=list(slot), V_full=value['V_full'], V_mask=value['V_mask'], S=value['S'],
                        delta_investigate=row['delta_investigate'],
                        oracle_information_set_mass=row['oracle_information_set_mass'])
                    if value['S'] > .05:
                        item['length_curve'] = []
                        for k in (1, 2, 3):
                            metric = window_values(tree, row['ego'], row['root_index'], row['world_weights'], k)
                            masked = masked_answer_value(tree, ego=row['ego'], root_index=row['root_index'],
                                root_weights=row['world_weights'], query_slot=slot, k=k)
                            item['length_curve'].append(dict(k=k, **metric, S=masked['S']))
                    masks.append(item)
            result.update(status='certified', certificate=tree.certificate, native_audit=audit,
                early_rows=rows, masks=masks, max_delta=max(r['delta_investigate'] for r in rows),
                max_measured_S=max((m['S'] for m in masks), default=0),
                strong_witnesses=sum(m['S'] > .05 and m['delta_investigate'] > .05
                    and any(c['C_span'] > .1 and c['S'] > .05 for c in m.get('length_curve', []))
                    for m in masks))
            if result['max_measured_S'] > .05:
                save_reference(out / f'{name}_reference.npz', tree)
    except Exception as exc:
        result.update(status='failed', error=f'{type(exc).__name__}: {exc}', oracle_label=None)
    result['seconds'] = time.monotonic() - start
    write_json(out / f'{name}_result.json', result)
    return {k: v for k, v in result.items() if k not in ('early_rows', 'masks', 'certificate', 'native_audit')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--geometry', choices=('compact', 'fixture', 'historical', 'three', 'three_rich', 'three_targeted'), default='compact')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--count', type=int, default=16)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--max-nodes', type=int, default=160000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'config.json').exists():
        raise ValueError('Use a new output directory; do not overwrite attempts')
    (args.output / 'search_source.py').write_text(Path(__file__).read_text())
    write_json(args.output / 'config.json', dict(**{k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        script_sha256=file_hash(Path(__file__)), mask_screen='Only first-proposal cells with strictly positive query action advantage; this is not an exhaustive S audit of every entrance.',
        scope='New diagnostic parents only; same native rules, full initial terminal solver and same-profile oracle reach. Positive results are convenience witnesses, not yield estimates for the existing generator.'))
    jobs = [(s, args.geometry, args.output, args.seconds, args.max_nodes) for s in range(args.seed, args.seed+args.count)]
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(attempt, jobs):
            results.append(result)
            print(json.dumps(result), flush=True)
            write_json(args.output / 'summary.json', dict(results=results,
                attempted=len(results), certified=sum(r['status']=='certified' for r in results),
                strong_parents=sum(r.get('strong_witnesses', 0)>0 for r in results)))


if __name__ == '__main__':
    main()
