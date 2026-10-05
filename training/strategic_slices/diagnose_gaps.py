"""Recheck the six previously selected three-round parents with current solver.

This panel is selected historical evidence, not random yield. A 300-second
budget differs from the earlier 90-second run and is reported explicitly.
"""
import argparse
from pathlib import Path
import time

from training.b_sft.preference_contract import world_weights
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .bounded import BoundedPrivateWindow
from .build import sample_parent
from .common import file_hash, stable, write_json

PANEL = ((20261002, 2), (20261003, 2), (20261005, 2), (20261011, 2), (20261006, 3), (20261010, 3))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--seconds', type=float, default=300)
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    sources = [p for folder in ('training/strategic_slices', 'training/b_sft', 'third_party/negotiation_benchmark/src')
               for p in (root / folder).rglob('*.py')]
    before = {str(p.relative_to(root)): file_hash(p) for p in sources}
    write_json(args.output / 'sources.json', before)
    cases = []
    with (args.output / 'cases.jsonl').open('w') as log:
        for seed, players in PANEL:
            raw = sample_parent(seed, players, 3)
            rules = PrivateInvestigationRules(raw)
            settings = dict(lookahead_rr=1, max_nodes=400000, seconds=args.seconds)
            record = dict(seed=seed, players=players, raw=raw, settings=settings,
                diagnostic_only=True, random_yield_estimate=False,
                previous_panel_seconds=90, comparison_changes_solver_and_time_budget=args.seconds != 90)
            start = time.monotonic()
            try:
                tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                    world_weights=world_weights(rules.worlds, raw['background_prior']), **settings).solve()
                record.update(status='certified', nodes=len(tree.entries), certificate=tree.certificate,
                              native_audit=tree.audit_native())
            except SearchLimit as exc:
                record.update(status='unavailable', reason=str(exc), certificate=None)
            record['seconds'] = time.monotonic() - start
            cases.append(record); log.write(stable(record) + '\n'); log.flush()
            print(stable({k: record[k] for k in ('seed', 'players', 'status', 'seconds')}), flush=True)
    unchanged = all(file_hash(root / p) == expected for p, expected in before.items())
    summary = dict(source_unchanged=unchanged, solver_seconds=args.seconds, previous_panel_seconds=90,
        selected_panel_not_random_yield=True, cases=len(cases),
        by_players={str(n): dict(attempted=sum(c['players'] == n for c in cases),
            certified=sum(c['players'] == n and c['status'] == 'certified' for c in cases)) for n in (2, 3)})
    write_json(args.output / 'summary.json', summary)
    if not unchanged:
        raise RuntimeError('Source changed during diagnostic; no completion certificate')
    write_json(args.output / 'COMPLETE.json', dict(summary_sha256=file_hash(args.output / 'summary.json')))


if __name__ == '__main__':
    main()
