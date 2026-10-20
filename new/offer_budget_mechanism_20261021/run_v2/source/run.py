"""Paired full-terminal research runs, with immutable per-run provenance."""
import argparse
import gc
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time
import unittest

import numpy as np

from new.offer_budget_mechanism_20261021.research import (
    VERSION, OfferQuotaRules, assert_factorized, small_parents, measure,
    audit_quota, one_round_control,
)
from training.b_sft.preference_contract import world_weights
from training.b_sft.shared_teacher import SearchLimit
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference
from training.strategic_slices.pipeline_versions import registered_snapshot

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open('x') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def summarize(rows):
    return dict(first_proposal_cells=len(rows),
        strict_query_advantage=sum(r['first_query_gap'] > 1e-8 for r in rows),
        positive_query_access=sum(r['query_access_value'] > 1e-8 for r in rows),
        max_query_gap=max((r['first_query_gap'] for r in rows), default=None),
        max_query_access_value=max((r['query_access_value'] for r in rows), default=None),
        max_measured_same_query_answer_value=max((q['same_query_answer_value']
            for r in rows for q in r['query_details'] if 'same_query_answer_value' in q), default=None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=45)
    parser.add_argument('--max-nodes', type=int, default=160000)
    parser.add_argument('--compact-count', type=int, default=6)
    parser.add_argument('--include-fixture', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.compact_count <= 6:
        parser.error('compact-count must be 0..6')
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = registered_snapshot('terminal-node-regret-grpo-readable-v8', 'terminal-readable-named-v2')
    inherited = json.loads((ROOT / baseline['path']).read_text())
    sources = {str(p.relative_to(ROOT)): file_hash(p) for p in HERE.glob('*.py')}
    fixture = ROOT / 'examples/strategic_slices/fixtures/native_acquisition_two_player.json'
    if args.include_fixture:
        sources[str(fixture.relative_to(ROOT))] = file_hash(fixture)
    config = dict(version=VERSION, paired_offer_limits=[None, 1],
        query='unchanged: one private answer per player per game; consumes a proposal turn; public target; only proposal phase',
        payoff='unchanged native additive binary/linear goal utility; no OFFER penalty or investigation bonus',
        preferences='original parent support/prior fixed within pair; require factorized support; no dependent-preference rules',
        response_ties='own expected final utility first, then sum of others, response only; uniform remaining ties',
        proposal_ties='own expected final utility only; uniform remaining ties',
        solver=dict(lookahead_rr='full native schedule length for each parent; no nonterminal leaves',
            max_nodes=args.max_nodes, seconds=args.seconds, max_sweeps=128,
            horizon_mode='rr-plus-next-own-proposal-v1', solver_mode='equilibrium', epsilon=1e-8,
            max_candidates=6, max_joint_cells=4096, max_joint_evaluations=160,
            large_tree_ordered_sweeps=2, initialization='uniform', audit_update_order=None),
        analysis_seconds_per_player=120,
        diagnostics='every reachable first-proposal own-information cell; vector full-terminal BR, no-own-queries BR, same-query answer mask for informative best queries',
        selection='first N of six declared compact convenience parents plus optional existing independent native witness; not random corpus sampling',
        model='not applicable', training='not applicable', sampling='none; complete public tree and information-conditioned expectations')
    snapshot = dict(schema=1, status='launched-not-completed', diagnostic_version=VERSION,
        actual_argv=sys.argv, actual_options={k:str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
        resolved_config=config, active_training=baseline,
        source_manifest={**inherited['contract_sources'], **sources},
        model_identity='none', data_identity='raw parent JSON and sha256 saved separately per parent',
        sampling_reward_contract=config['diagnostics'],
        runtime=dict(python=sys.version, executable=sys.executable, platform=platform.platform(), numpy=np.__version__),
        gpu_used=False, production_changed=False)
    write(args.output / 'pipeline_snapshot.json', snapshot)
    suite = unittest.defaultTestLoader.loadTestsFromName('new.offer_budget_mechanism_20261021.test_research')
    tested = unittest.TextTestRunner(verbosity=1).run(suite)
    write(args.output / 'semantic_checks.json', dict(tests=tested.testsRun,
        passed=tested.wasSuccessful(), errors=[str(e) for e in tested.errors], failures=[str(e) for e in tested.failures]))
    if not tested.wasSuccessful():
        raise RuntimeError('Rule semantic checks failed')
    parents = list(small_parents())[:args.compact_count]
    if args.include_fixture:
        parents.append(('native_two_player_existing', json.loads(fixture.read_text())['raw']))
    results = []
    for name, raw in parents:
        supports = assert_factorized(raw)
        raw_file = args.output / f'{name}_raw.json'
        write(raw_file, raw)
        control = one_round_control(raw)
        write(args.output / f'{name}_one_round_control.json', control)
        for limit in (None, 1):
            label = name + ('_unlimited' if limit is None else '_quota1')
            result = dict(name=name, limit=limit, raw_sha256=file_hash(raw_file),
                factorized_support=supports, status='started', oracle_label=None)
            start = time.monotonic()
            tree = None
            try:
                rules = OfferQuotaRules(raw, limit)
                tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                    world_weights=world_weights(rules.worlds, raw['background_prior']),
                    lookahead_rr=len(rules.spec.round_robin), max_nodes=args.max_nodes,
                    seconds=args.seconds, large_tree_ordered_sweeps=2).solve()
                assert not tree.cutoff_leaves
                tree.deadline = time.monotonic() + 120
                native_audit = tree.audit_native()
                quota_audit = audit_quota(tree)
                rows = measure(tree)
                save_reference(args.output / f'{label}_reference.npz', tree)
                result.update(status='certified', certificate=tree.certificate,
                    scope='Selected full-terminal own-utility epsilon-Nash plus local support/response-tie audit for this quota variant; not unique equilibrium or corpus prevalence',
                    nodes=len(tree.entries), worlds=tree.w, native_audit=native_audit, quota_audit=quota_audit,
                    rows=rows, summary=summarize(rows),
                    ex_ante_payoffs=(tree.world_weights @ tree.values[0]).tolist(),
                    reference_sha256=file_hash(args.output / f'{label}_reference.npz'))
            except SearchLimit as exc:
                result.update(status='no_certified_label', reason=str(exc),
                    nodes_built=None if tree is None else len(tree.entries))
            except Exception as exc:
                result.update(status='implementation_error', reason=f'{type(exc).__name__}: {exc}')
                write(args.output / f'{label}_result.json', result)
                raise
            result['seconds'] = time.monotonic() - start
            write(args.output / f'{label}_result.json', result)
            results.append({k:v for k,v in result.items() if k in (
                'name','limit','status','reason','nodes','worlds','summary','ex_ante_payoffs','seconds')})
            print(json.dumps(results[-1]), flush=True)
            del tree
            gc.collect()
    write(args.output / 'summary.json', dict(results=results,
        status='completed', executed_cases=len(results), certified=sum(r['status']=='certified' for r in results),
        failures_are_missing_labels_not_zero_signal=True,
        causal_scope='Within-parent quota is the only physical change. Each variant is independently re-solved, so differences include profile selection and partner adaptation.',
        production_changed=False, gpu_used=False))
    write(args.output / 'COMPLETE.json', dict(status='completed',
        pipeline_snapshot_sha256=file_hash(args.output / 'pipeline_snapshot.json'),
        summary_sha256=file_hash(args.output / 'summary.json')))


if __name__ == '__main__':
    main()
