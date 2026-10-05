"""Frozen complete-game and slice evaluation; no training or test-based selection."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import threading
from urllib.request import Request, urlopen

import numpy as np
from .common import Dataset, VERSION, seed_for, stable, write_json, write_rows
from .runtime import Rollout, execute


def interval(values, seed=42):
    if not values:
        return dict(mean=None, bootstrap95=None, n=0)
    values = np.asarray(values, float)
    rng = np.random.default_rng(seed)
    means = values[rng.integers(len(values), size=(2000, len(values)))].mean(axis=1)
    return dict(mean=float(values.mean()), bootstrap95=np.quantile(means, [.025, .975]).tolist(), n=len(values))


def summarize(jobs):
    strata = defaultdict(list)
    for job in jobs:
        strata['all'].append(job)
        strata[f'{job.parent["players"]}p'].append(job)
    metrics = {}
    for stratum, cohort in strata.items():
        done = [j for j in cohort if j.completed]
        calls = [c for j in cohort for c in j.calls]
        parents = defaultdict(list)
        bounds = defaultdict(list)
        regrets = defaultdict(list)
        for j in cohort:
            p = j.ego
            player_count = j.parent['players']
            rows = [j.world[p]] if p is not None else j.world
            lower = sum(sum(min(0, v) for v in row) for row in rows) / len(rows)
            upper = sum(sum(max(0, v) for v in row) for row in rows) / len(rows)
            if j.utility is not None:
                value = j.utility[p] if p is not None else sum(j.utility) / player_count
                parents[j.parent['id']].append(value)
                bounds[j.parent['id']].append((value, value))
                if j.slice:
                    regrets[j.parent['id']].append(j.slice['V_star'] - j.utility[p])
            else:
                bounds[j.parent['id']].append((lower, upper))
        scopes = {'cutoff' if j.bounded and j.slice else 'native-terminal' for j in cohort}
        if len(scopes) != 1:
            raise ValueError('Cannot combine cutoff and terminal utilities in one metric')
        metrics[stratum] = dict(utility_scope=next(iter(scopes)), episodes=len(cohort), completed=len(done), completion_rate=len(done) / len(cohort),
            decision_calls=len(calls), invalid_calls=sum(not c['valid'] for c in calls),
            truncated_calls=sum(c['protocol_failure'] == 'truncated' for c in calls),
            player_utility_completed_parent_macro=interval([np.mean(v) for v in parents.values()]),
            cohort_player_utility_bounds=[float(np.mean([np.mean([v[i] for v in vs]) for vs in bounds.values()])) for i in (0, 1)],
            D_completed_parent_macro=interval([np.mean(v) for v in regrets.values()]) if regrets else None)
    return metrics


class Evaluator:
    def __init__(self, dataset, generate, split='validation', repeats=1, modes=('team', 'focal_reference'), seed=42, concurrency=32):
        if split not in ('validation', 'test') or repeats < 1:
            raise ValueError('Use frozen validation/test games and positive repeats')
        self.dataset, self.generate, self.split = dataset, generate, split
        self.repeats, self.modes, self.seed, self.concurrency = repeats, modes, seed, concurrency

    def run(self):
        reports, games, calls = {}, [], []
        for mode in self.modes:
            if mode not in ('team', 'focal_reference', 'slices'):
                raise ValueError('Unknown evaluation mode')
            jobs = []
            for parent in self.dataset.parents[self.split]:
                parent_jobs = []
                items = [None] if mode == 'team' else list(range(parent['players'])) if mode == 'focal_reference' else [s for s in self.dataset.slices[self.split] if s['parent_id'] == parent['id']]
                for item in items:
                    for replica in range(self.repeats):
                        key = item['id'] if isinstance(item, dict) else item
                        seed = seed_for(self.seed, 'evaluation', parent['id'], mode, key, replica)
                        weights = item['entry_world_weights'] if mode == 'slices' else parent['world_weights']
                        wi = int(np.random.default_rng(seed).choice(len(weights), p=weights))
                        parent_jobs.append(Rollout(self.dataset, parent, seed, wi,
                                                   slice_record=item if mode == 'slices' else None,
                                                   focal=item if mode == 'focal_reference' else None))
                execute(parent_jobs, self.generate, temperature=0.0, concurrency=self.concurrency)
                for job in parent_jobs:
                    job.tree = job.rules = job.node = job.reference = None
                    if job.rolling:
                        # Keep timing/counts, not one large cached oracle per
                        # completed episode, across the entire evaluation set.
                        job.rolling.cache = None
                jobs.extend(parent_jobs)
            reports[mode] = summarize(jobs)
            for number, job in enumerate(jobs):
                record = dict(job.summary(), mode=mode, evaluation_id=f'{mode}:{number}',
                              seed=job.seed, world=[list(r) for r in job.world])
                games.append(record)
                calls.extend(dict(c, mode=mode, parent_id=job.parent['id'], evaluation_id=record['evaluation_id']) for c in job.calls)
        return dict(protocol=dict(version=VERSION, split=self.split, dataset_sha256=self.dataset.sha,
                                  repeats=self.repeats, modes=self.modes, temperature=0., max_tokens=1024,
                                  primary='Final checkpoint, complete-game utility and legal completion; failed utilities remain null.'),
                    metrics=reports, games=games, calls=calls)


class HTTPGenerator:
    def __init__(self, base_url, model, concurrency=16, timeout=180, evidence=None):
        self.base_url, self.model, self.concurrency, self.timeout = base_url.rstrip('/'), model, concurrency, timeout
        self.evidence, self.lock = evidence, threading.Lock()

    def record(self, row):
        if self.evidence is not None:
            with self.lock, self.evidence.open('a') as log:
                log.write(stable(row) + '\n')

    def __call__(self, requests):
        def complete(request):
            started = time.monotonic()
            body = dict(request, model=self.model, max_tokens=1024, top_p=1.)
            req = Request(self.base_url + '/chat/completions', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    result = json.load(response)
            except Exception as exc:
                self.record(dict(status='infrastructure_failure', request=body, error=repr(exc)))
                raise
            self.record(dict(status='ok', request=body, response=result))
            choice = result['choices'][0]
            return dict(completion=dict(finish_reason=choice['finish_reason'], raw_message=choice['message']),
                        finish_reason=choice['finish_reason'], request=request, usage=result.get('usage'),
                        elapsed_seconds=time.monotonic() - started)
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            return list(executor.map(complete, requests))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', required=True, type=Path)
    cli.add_argument('--split', choices=('validation', 'test'), default='test')
    cli.add_argument('--base-url', required=True)
    cli.add_argument('--model', required=True)
    cli.add_argument('--checkpoint-hash', required=True)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--modes', nargs='+', choices=('team', 'focal_reference', 'slices'), default=['team', 'focal_reference'])
    cli.add_argument('--repeats', type=int, default=4)
    cli.add_argument('--seed', type=int, default=42)
    cli.add_argument('--concurrency', type=int, default=16)
    args = cli.parse_args()
    dataset = Dataset(args.data, (args.split,))
    args.output.mkdir(parents=True, exist_ok=False)
    generator = HTTPGenerator(args.base_url, args.model, args.concurrency, evidence=args.output / 'transport.jsonl')
    evaluator = Evaluator(dataset, generator, args.split, args.repeats, args.modes, args.seed, args.concurrency)
    try:
        report = evaluator.run()
        report['protocol'].update(model=args.model, checkpoint_hash=args.checkpoint_hash, seed=args.seed)
        write_rows(args.output / 'games.jsonl', report.pop('games'))
        write_rows(args.output / 'calls.jsonl', report.pop('calls'))
        write_json(args.output / 'summary.json', report)
        write_json(args.output / 'COMPLETE.json', report['protocol'])
        print(stable(report['metrics']))
    except Exception as exc:
        write_json(args.output / 'FAILED.json', dict(error=repr(exc)))
        raise


if __name__ == '__main__':
    main()
