"""Read-only startup snapshot; never selects, reserves, or preempts GPUs."""

import argparse
import csv
import json
import os
import subprocess
import sys


def device_tokens(value):
    tokens = [part.strip() for part in value.split(',')]
    if not value or any(not token for token in tokens) or len(set(tokens)) != len(tokens):
        raise ValueError('Set CUDA_VISIBLE_DEVICES explicitly to distinct GPU indices or full GPU UUIDs')
    return tokens


def select_devices(tokens, rows, min_free_mib=0):
    selected = []
    for token in tokens:
        matches = [row for row in rows if token in (row['index'], row['uuid'])]
        if len(matches) != 1:
            raise ValueError(f'GPU {token!r} is unavailable; use an index or full GPU UUID from nvidia-smi')
        row = matches[0]
        if row['uuid'] in {r['uuid'] for r in selected}:
            raise ValueError('The same physical GPU was selected twice')
        if int(row['memory.free']) < min_free_mib:
            raise ValueError(f"GPU {token}: {row['memory.free']} MiB free, below requested {min_free_mib} MiB")
        selected.append(row)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--min-free-mib', type=int, default=0,
                        help='Optional per-GPU admission threshold; no fixed memory assumption by default')
    args = parser.parse_args()
    if args.min_free_mib < 0:
        parser.error('--min-free-mib must be nonnegative')
    try:
        tokens = device_tokens(os.environ.get('CUDA_VISIBLE_DEVICES', ''))
        fields = ['index', 'uuid', 'name', 'memory.total', 'memory.free', 'utilization.gpu']
        result = subprocess.run(['nvidia-smi', '--query-gpu=' + ','.join(fields),
                                 '--format=csv,noheader,nounits'], check=True,
                                capture_output=True, text=True, timeout=10)
        rows = [dict(zip(fields, [cell.strip() for cell in row]))
                for row in csv.reader(result.stdout.splitlines()) if row]
        selected = select_devices(tokens, rows, args.min_free_mib)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        parser.exit(2, f'GPU preflight failed: {error}\n')
    print(json.dumps(dict(selected_gpus=selected, min_free_mib=args.min_free_mib,
                         note='Snapshot only, not a reservation or a guarantee that training fits. '
                              'Existing tasks are neither stopped nor modified.'), indent=2), file=sys.stderr)
    print(len(selected))


if __name__ == '__main__':
    main()
