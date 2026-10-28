"""Paired model-independent horizon/threshold diagnostics, with raw evidence."""
import argparse
from collections import Counter
from pathlib import Path
import time

from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .build import sample_parent, select_fixed_slices
from .common import digest, write_json, write_rows
from .reference import FixedReference


def public_history_nodes(raw):
    """Count the full unfolded tree; physical memoization is ONLY for counting.

    Histories with the same physical state may have different beliefs. This
    function never merges their strategies or reuses their oracle values.
    """
    rules = PrivateInvestigationRules(raw); memo = {}
    def count(node):
        key = (node.state.turn_index, node.state.snapshot_commitments(),
               node.pending, node.state.investigation_used)
        if key not in memo:
            memo[key] = 1 + sum(count(rules._apply(node, action)) for action in rules.actions(node))
        return memo[key]
    return dict(public_history_nodes=count(rules.initial()), physical_counting_states=len(memo))


def diagnose(output, seeds=24, seed=20261002, max_k=3):
    output.mkdir(parents=True, exist_ok=False)
    config = dict(max_k=max_k, max_nodes=30000, solver_seconds=15, entrance_trajectories=6,
                  reach_epsilon=.25, max_entrances=6, min_c=.1, min_increment=.05, min_s=.05,
                  slices_per_parent=8)
    rows = []
    for candidate in range(seed, seed + seeds):
        for rounds in (1, 2, 3):
            raw = sample_parent(candidate, 3, rounds)
            start = time.monotonic()
            record = dict(seed=candidate, rounds=rounds, parent_id=digest(raw)[:24],
                          reference_backend='fixed-myopic-v1')
            try:
                reference = FixedReference(PrivateInvestigationRules(raw), raw['background_prior'])
                retained, entrances, windows, _ = select_fixed_slices(reference, record['parent_id'], candidate, config)
                spans = [max(w['C_span_by_k']) for w in windows]
                record.update(status='measured', sampled_entrances=entrances, windows=windows,
                    sparse_nodes=sum(w['nodes'] for w in windows), retained=len(retained),
                    max_C_span=max(spans, default=0),
                    above_threshold={str(t): sum(s > t for s in spans) for t in (0., .01, .05, .1, .2)},
                    delayed_windows=sum(w['C_span_by_k'][0] <= .1 and max(w['C_span_by_k'][1:]) > .1 for w in windows),
                    max_private_S=max((v['S'] for s in retained for v in s['information_values']), default=0.),
                    max_S_given_query=max((v['S_given_query'] for s in retained for v in s['information_values']), default=0.))
            except Exception as exc:
                record.update(status='failed', reason=str(exc))
            record['seconds'] = time.monotonic() - start
            rows.append(record); write_rows(output / 'cases.jsonl', rows)
            print(f"seed={candidate} rounds={rounds} status={record['status']} C={record.get('max_C_span')} seconds={record['seconds']:.3f}", flush=True)
    summary = dict(reference_backend='fixed-myopic-v1', model_independent=True, config=config, rounds={})
    for rounds in (1, 2, 3):
        cases = [r for r in rows if r['rounds'] == rounds]
        measured = [r for r in cases if r['status'] == 'measured']
        summary['rounds'][rounds] = dict(candidates=len(cases), measured=len(measured),
            failures=dict(Counter(r.get('reason') for r in cases if r['status'] == 'failed')),
            parents_with_retained_signal=sum(r['retained'] > 0 for r in measured),
            parents_with_private_S_above_005=sum(r['max_private_S'] > .05 for r in measured),
            delayed_windows=sum(r['delayed_windows'] for r in measured),
            entrance_threshold_counts={str(t): sum(r['above_threshold'][str(t)] for r in measured) for t in (0., .01, .05, .1, .2)},
            sparse_nodes=sum(r['sparse_nodes'] for r in measured), seconds=sum(r['seconds'] for r in cases))
    anchor = []
    for rounds in (1, 2, 3):
        raw = sample_parent(20261027, 3, rounds)
        anchor.append(dict(seed=20261027, rounds=rounds, **public_history_nodes(raw)))
    summary['unfolded_tree_count_anchor'] = anchor
    summary['interpretation'] = 'C/S are exact relative to this declared fixed reference. These paired measurements do not estimate equilibrium values or LLM reward diversity.'
    write_json(output / 'summary.json', summary)
    return summary


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--seeds', type=int, default=24)
    cli.add_argument('--seed', type=int, default=20261002)
    cli.add_argument('--max-k', type=int, default=3, help='Vary focal control on the same seeded entrances')
    args = cli.parse_args()
    if args.seeds < 1 or args.max_k < 1:
        cli.error('--seeds and --max-k must be positive')
    diagnose(args.output, args.seeds, args.seed, args.max_k)


if __name__ == '__main__':
    main()
