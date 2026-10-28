"""Budget portability of B labels and higher-budget P on saved audit histories.

Different oracle budgets define different behavior models. A portability
failure does not invalidate an exact B label under its original fixed model.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from benac_p.mcts_bp_audit import (
    actual_oracle_values, difference_stats, make_game, paired_reference_values, write_json,
)
from benac_p.mcts_oracle import Budget


def compact_action(oracle, node, raw):
    return next(a for a in oracle.actions(node) if oracle.native_action(node, a).to_dict() == raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--actual-samples', type=int, default=8)
    parser.add_argument('--eval-samples', type=int, default=1024)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh output directory')
    manifest = json.loads((args.source_dir / 'manifest.json').read_text())
    for name, expected in manifest['source_sha256'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == expected
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'manifest.json', dict(
        source_manifest=manifest, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        configuration={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        scope='Exploratory follow-up on the same development games, not independent test data.'))
    results = []
    for path in sorted((args.source_dir / 'games').glob('*.json')):
        start = time.perf_counter()
        game = json.loads(path.read_text())
        print('START', game['id'], flush=True)
        budget = Budget(**manifest['policy_budget'])
        spec, oracle, actual = make_game(game['seed'], game['cell'], manifest['configuration']['profiles'], budget)
        learner = game['learner']
        node, domains, b_checks, snapshots = (0, 0, None), oracle.prior, [], []
        for index, record in enumerate(game['decisions']):
            snapshots.append((node, domains))
            actor = oracle.actor(node)
            action = compact_action(oracle, node, record['action'])
            after = tuple(tuple(d) for d in record['after_domains'])
            if actor != learner and len(domains[actor]) > len(after[actor]) and len(b_checks) < 3:
                checks = {}
                for name, other_budget in (
                    ('doubled', replace(budget, simulations=2 * budget.simulations)),
                    ('reseeded', replace(budget, salt=17)),
                ):
                    kept = tuple(t for t in domains[actor]
                                 if oracle.search(node, actor, t, domains, budget=other_budget)['action'] == action)
                    checks[name] = dict(matching_types=kept,
                                        realized_type_retained=actual[actor] in kept,
                                        same_support_as_base=set(kept) == set(after[actor]),
                                        empty_support=not kept)
                b_checks.append(dict(decision=index, player=actor, observed_action=record['action'],
                                     before=domains[actor], base_after=after[actor], portability=checks))
            node = oracle.step(node, action)
            domains = after
        # One post-evidence, nonterminal P proposal per game, selected by timing
        # rather than observed advantage; fallback to a later response if needed.
        candidates = [p for p in game['planning_audit'] if p['turn'] > 0 and p['phase'] == 'proposal']
        candidates = candidates or [p for p in game['planning_audit'] if p['turn'] > 0]
        planning = None
        if candidates:
            chosen = candidates[0]
            node, domains = snapshots[chosen['history_decisions']]
            searches = {}
            for multiplier in (1, 4, 16):
                for salt in (0, 17):
                    name = f'n{budget.simulations * multiplier}_salt{salt}'
                    searches[name] = oracle.search(node, learner, actual[learner], domains,
                                                   budget=replace(budget, simulations=budget.simulations * multiplier, salt=salt))
            actions = {name: s['action'] for name, s in searches.items()}
            actions['reference'] = oracle.reference(node, actual[learner], domains)
            actions['prior_only'] = oracle.search(node, learner, actual[learner], oracle.prior)['action']
            base_name = f'n{budget.simulations}_salt0'
            high_name = f'n{budget.simulations * 16}_salt0'
            values = paired_reference_values(oracle, node, domains, learner, actual[learner], actions,
                                             args.eval_samples, (game['id'], 'followup-heldout'))
            actual_check = actual_oracle_values(oracle, node, domains, learner, actual[learner],
                dict(teacher=actions[high_name], reference=actions['reference'],
                     base=actions[base_name], prior_only=actions['prior_only']),
                args.actual_samples, (game['id'], 'followup-actual')) if args.actual_samples else None
            if actual_check:
                actual_check['paired_comparisons'] = {
                    name: difference_stats(actual_check['rewards']['teacher'], actual_check['rewards'][name])
                    for name in ('reference', 'base', 'prior_only')}
            planning = dict(source_position=chosen['id'], turn=node[1],
                            history_decisions=chosen['history_decisions'], domains=domains,
                            actions={name: oracle.native_action(node, a).to_dict() for name, a in actions.items()},
                            search_seconds={name: s['seconds'] for name, s in searches.items()},
                            heldout_means={name: float(np.mean(v)) for name, v in values.items()},
                            high_vs_other={name: difference_stats(values[high_name], vals)
                                           for name, vals in values.items() if name != high_name},
                            actual_continuation=actual_check)
        result = dict(game=game['id'], b_portability=b_checks, planning=planning,
                      seconds=time.perf_counter() - start)
        results.append(result)
        write_json(args.output_dir / f'{game["id"]}.json', result)
        write_json(args.output_dir / 'summary.json', dict(games=len(results), results=results))
        oracle.clear_caches()
        print(json.dumps(dict(game=game['id'], seconds=result['seconds'], b_checks=len(b_checks))), flush=True)
    files = sorted(p for p in args.output_dir.rglob('*') if p.is_file())
    write_json(args.output_dir / 'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


if __name__ == '__main__':
    main()
