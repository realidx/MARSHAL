"""Measure four-replica reward diversity before GPU optimization.

An HTTP run uses actual model actions. --mock only checks the pipeline and
must never be represented as evidence of model learning or model diversity.
"""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from .common import Dataset, seed_for, write_json, write_rows, file_hash
from .evaluate import HTTPGenerator
from .runtime import Rollout, execute


def probe(dataset, generate, arm, groups=24, replicas=4, seed=42):
    if arm not in ('slices', 'selfplay') or groups < 1 or replicas < 2:
        raise ValueError('Positive groups and at least two replicas required')
    parents = dataset.parents['train']
    pool = {p['id']: [s for s in dataset.slices['train'] if s['parent_id'] == p['id']] for p in parents}
    rows, calls = [], []
    for group in range(groups):
        cycle, offset = divmod(group, len(parents))
        order = np.random.default_rng(seed_for(seed, 'parents', cycle)).permutation(len(parents))
        parent = parents[int(order[offset])]
        rng = np.random.default_rng(seed_for(seed, arm, group))
        selected = pool[parent['id']][int(rng.integers(len(pool[parent['id']])))] if arm == 'slices' else None
        weights = selected['entry_world_weights'] if selected else parent['world_weights']
        wi = int(rng.choice(len(weights), p=weights))
        jobs = [Rollout(dataset, parent, seed_for(seed, arm, group, r), wi, selected) for r in range(replicas)]
        execute(jobs, generate, temperature=1.)
        complete = all(j.completed for j in jobs)
        players = [selected['ego']] if selected else range(parent['players'])
        for player in players:
            rewards = [j.utility[player] if j.completed else None for j in jobs]
            rows.append(dict(group=group, parent_id=parent['id'], players=parent['players'], player=player,
                slice_id=selected['id'] if selected else None,
                information_positive=selected['information_positive'] if selected else None,
                world_index=wi, complete=complete, rewards=rewards,
                reward_span=float(np.ptp(rewards)) if complete else None,
                reward_std=float(np.std(rewards)) if complete else None,
                active_task_advantage=bool(complete and np.ptp(rewards) > 1e-12),
                distinct_action_trajectories=len({tuple(c['action_index'] for c in j.calls if c['player'] == player) for j in jobs}),
                statuses=[j.status for j in jobs], utility_scope='cutoff' if selected and parent.get('reference_backend') == 'bounded-next-own-v1' else 'native-terminal'))
        calls.extend(dict(c, group=group, replica=r) for r, job in enumerate(jobs) for c in job.calls)
    summary = dict(arm=arm, dataset_sha256=dataset.sha, reset_groups=groups, player_groups=len(rows),
        completed_player_groups=sum(r['complete'] for r in rows),
        active_player_groups=sum(r['active_task_advantage'] for r in rows),
        active_group_fraction=sum(r['active_task_advantage'] for r in rows) / len(rows),
        response_tokens=sum((c.get('usage') or {}).get('completion_tokens', len(c.get('response_ids', []))) for c in calls),
        calls=len(calls), failures=dict(Counter(c['protocol_failure'] for c in calls if not c['valid'])),
        positive_S_player_groups=sum(r['information_positive'] is True for r in rows),
        interpretation='Positive C/S does not imply sampled reward diversity; report failed and zero-variance groups without resampling.')
    return summary, rows, calls


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--base-url')
    cli.add_argument('--model')
    cli.add_argument('--checkpoint-hash')
    cli.add_argument('--mock', action='store_true')
    cli.add_argument('--groups', type=int, default=24)
    cli.add_argument('--replicas', type=int, default=4)
    cli.add_argument('--seed', type=int, default=42)
    args = cli.parse_args()
    if not args.mock and not all((args.base_url, args.model, args.checkpoint_hash)):
        cli.error('Actual model probe requires --base-url, --model and --checkpoint-hash')
    if args.mock and any((args.base_url, args.model, args.checkpoint_hash)):
        cli.error('Mock probe cannot carry real-model identity')
    dataset = Dataset(args.data, ('train',))
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mock:
        from .test_pipeline import mock_generate
        generate = mock_generate
    else:
        generate = HTTPGenerator(args.base_url, args.model, evidence=args.output / 'transport.jsonl')
    result = dict(mock=args.mock, model_learning_validated=False, actual_model_actions=not args.mock,
        model=args.model, checkpoint_hash=args.checkpoint_hash, seed=args.seed, replicas=args.replicas,
        dataset_sha256=dataset.sha, source_sha256={p.name: file_hash(p) for p in Path(__file__).parent.glob('*.py')}, arms={})
    try:
        for arm in ('slices', 'selfplay'):
            summary, rows, calls = probe(dataset, generate, arm, args.groups, args.replicas, args.seed)
            result['arms'][arm] = summary
            write_rows(args.output / f'{arm}_groups.jsonl', rows)
            write_rows(args.output / f'{arm}_calls.jsonl', calls)
        write_json(args.output / 'summary.json', result)
        write_json(args.output / 'COMPLETE.json', dict(summary_sha256=file_hash(args.output / 'summary.json')))
        print(result['arms'])
    except Exception as exc:
        write_json(args.output / 'FAILED.json', dict(error=repr(exc), mock=args.mock))
        raise


if __name__ == '__main__':
    main()
