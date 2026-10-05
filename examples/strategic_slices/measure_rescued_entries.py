"""Measure saved certified retry profiles, without rerunning equilibrium search."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from collections import Counter
from examples.strategic_slices.check_entry_information import restore, measure
from training.strategic_slices.common import file_hash, write_json


def worker(source, retry, out, index, diagnostic=False):
    started = time.monotonic()
    record = json.loads((retry / (f'result_{index}.json' if diagnostic else f'result_30_{index}.json')).read_text())
    assert record['status'] in ('certified','certified_on_diagnostic_rerun')
    raw_path = source / f'raw_{index}.json'
    assert file_hash(raw_path) == record['raw_sha256']
    raw = json.loads(raw_path.read_text())
    reference = retry / (f'reference_{index}.npz' if diagnostic else f'reference_30_{index}.npz')
    tree = restore(dict(raw=raw), dict(full_certificate=record['certificate']), reference)
    rows = measure(tree, max_groups=6, include_singletons=True)
    shutil.copyfile(raw_path, out / raw_path.name)
    shutil.copyfile(reference, out / f'reference_{index}.npz')
    write_json(out / f'result_{index}.json', dict(
        status='verified', index=index, seed=2026100700 + index, players=tree.n,
        worlds=tree.worlds, certificate=tree.certificate, audit=tree.audit_native(),
        seconds=time.monotonic() - started, rows=rows,
        origin=dict(kind='native-random-budget-recovery', original_budget=6,
                    certified_budget=record.get('budget',30), diagnostic_reference=diagnostic, raw_sha256=file_hash(raw_path),
                    reference_sha256=file_hash(reference), retry_source=str(retry))))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('new/local_data/strategic_slices_native_entry_search_v2'))
    p.add_argument('--retry', type=Path, default=Path('new/local_data/strategic_slices_terminal_budget_retry_v1'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--worker', type=int)
    p.add_argument('--diagnostic-references', action='store_true', help='Read successful saved references from diagnose_terminal_failures')
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    if a.worker is not None:
        worker(a.source, a.retry, a.output, a.worker, a.diagnostic_references); return
    summary = json.loads((a.retry / 'summary.json').read_text())
    records = summary['results'] if a.diagnostic_references else summary['stages']['30']['results']
    indices = [r['index'] for r in records if r['status'] in ('certified','certified_on_diagnostic_rerun')]
    started = time.monotonic()
    def launch(index):
        with (a.output / f'worker_{index}.log').open('w') as log:
            try:
                subprocess.run([sys.executable, '-m', 'examples.strategic_slices.measure_rescued_entries',
                    '--source', str(a.source), '--retry', str(a.retry), '--output', str(a.output), '--worker', str(index)] + (['--diagnostic-references'] if a.diagnostic_references else []),
                    stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120,
                    env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))
                result = json.loads((a.output / f'result_{index}.json').read_text())
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                result = dict(index=index, status='measurement_failed', reason=str(exc),
                              reference_status='certified', metrics=None)
                write_json(a.output / f'result_{index}.json', result)
        print(index, result['status'], len(result.get('rows', [])), flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(launch, indices))
    rows = [row for r in results for row in r.get('rows', [])]
    write_json(a.output / 'summary.json', dict(results=results, seconds=time.monotonic()-started,
        statuses=dict(Counter(r['status'] for r in results)), comparisons=len(rows),
        positive_S=sum(r['S']>.05 for r in rows), max_S=max((r['S'] for r in rows), default=0),
        retry_summary_sha256=file_hash(a.retry / 'summary.json'),
        scope='Saved certified profiles; no equilibrium rerun. Same max_groups=6 and k=1/2/3 as original search. C is computed during candidate packaging.'))

if __name__ == '__main__':
    main()
