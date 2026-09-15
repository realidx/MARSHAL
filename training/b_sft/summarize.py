"""Summarize synchronized optimizer-step timing; exclude startup steps by default."""

import argparse
import json
import statistics
from pathlib import Path


def summarize(path, warmup=3):
    manifests = sorted(path.glob('run_manifest_*.json'))
    manifest = json.loads(manifests[-1].read_text())
    latest = {}
    for file in path.glob('rank_*_steps.jsonl'):
        for line in file.read_text().splitlines():
            row = json.loads(line)
            latest[row['rank'], row['step']] = row
    steps = sorted({step for _, step in latest})[warmup:]
    world = manifest['world_size']
    complete = [step for step in steps if all((rank, step) in latest for rank in range(world))]
    if not complete:
        raise ValueError('No complete measured steps after warmup')
    times = [max(latest[rank, step]['step_seconds'] for rank in range(world)) for step in complete]
    global_batch = world * manifest['arguments']['gradient_accumulation']
    return dict(complete_optimizer_steps=len(complete), skipped_initial_steps=warmup,
                median_step_seconds=statistics.median(times),
                mean_step_seconds=statistics.mean(times),
                nominal_samples_per_second=global_batch/statistics.mean(times),
                allocator_peak_gib_by_rank={rank: max(r['reserved_peak_bytes'] for (k, _), r in latest.items()
                                                       if k == rank)/2**30 for rank in range(world)},
                note='Step timing excludes checkpoint/evaluation time; GPU allocator is not total process/device memory. '
                     'Use train_results.json for end-to-end throughput and gpu_resources.jsonl for machine contention.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--warmup', type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(summarize(args.run_dir, args.warmup), indent=2))


if __name__ == '__main__':
    main()
