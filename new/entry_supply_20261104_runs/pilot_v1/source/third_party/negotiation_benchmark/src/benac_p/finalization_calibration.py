"""Replay only balanced truncations from a frozen discovery calibration."""
import argparse
import json
import os
from pathlib import Path

import numpy as np

from benac_p.diagnose_protocol import FINALIZATION_VERSION, finalize, protocol_summary, system_prompt
from benac_p.diagnose_suite import digest, dump
from benac_p.reasoning_calibration import evaluate
from benac_p.semantic_suite import SYSTEM


def summary(rows, records):
    scored = [(row, evaluate(row, records[row['id']])) for row in rows]
    def mean(key, kind=None):
        values = [r[key] for row, r in scored if kind is None or row['task']['kind'] == kind]
        return float(np.mean(values)) if values else None
    return dict(valid_rate=mean('valid'),
                belief_valid_and_exact_rate=mean('success', 'semantic_belief'),
                planning_valid_and_optimal_rate=mean('success', 'planning'),
                protocol=protocol_summary(records))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--base-url', default='http://localhost:8000/v1')
    parser.add_argument('--model', default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--finalization-tokens', type=int, default=128)
    parser.add_argument('--export-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    source, out = args.source_run.resolve(), args.output_dir.resolve()
    if out == source or source in out.parents:
        parser.error('Keep outputs outside the immutable source run.')
    if args.finalization_tokens < 1:
        parser.error('Finalization budget must be positive.')
    source_manifest = json.loads((source/'manifest.json').read_text())
    rows = json.loads((source/'tasks.json').read_text())
    labels = json.loads((source/'oracle_labels.json').read_text())
    archived = json.loads((source/'answers.json').read_text())
    if source_manifest['model'] != args.model:
        parser.error('Use the same served model as the source calibration.')
    if source_manifest['system_hashes']['balanced'] != digest(system_prompt(SYSTEM, 'reasoning_tools', 'balanced')):
        parser.error('Balanced prompt changed; cannot reuse these first passes.')
    if len({row['id'] for row in rows}) != len(rows):
        parser.error('Duplicate source task IDs.')
    baseline = {row['id']: archived['balanced/'+row['id']] for row in rows}
    if any(r.get('status') not in ('ok', 'invalid', 'truncated') or r.get('reasoning_profile') != 'balanced'
           or r.get('response_protocol') != 'reasoning_tools' or 'attempts' in r for r in baseline.values()):
        parser.error('Source must contain completed, unrecovered balanced first passes.')
    for row in rows:
        row['expected'] = labels[row['id']]
    manifest = dict(version=FINALIZATION_VERSION, source_hash=digest([source_manifest, rows, baseline]),
                    model=args.model, base_url=args.base_url, finalization_tokens=args.finalization_tokens,
                    initial_max_tokens=source_manifest['max_tokens'])
    out.mkdir(parents=True, exist_ok=True)
    if (out/'manifest.json').exists():
        if json.loads((out/'manifest.json').read_text()) != manifest:
            parser.error('Manifest changed; use a fresh directory.')
        if (out/'answers.json').exists() and not args.resume:
            parser.error('Existing output requires --resume.')
    elif args.resume:
        parser.error('No manifest to resume.')
    dump(out/'manifest.json', manifest)
    records = json.loads((out/'answers.json').read_text()) if (out/'answers.json').exists() else {}
    for key, record in baseline.items():
        records.setdefault(key, record)
    jobs = [row for row in rows if records[row['id']]['status'] == 'truncated'
            and not records[row['id']].get('finalization_attempted')]
    dump(out/'answers.json', records)
    dump(out/'pending_tasks.json', [{k: v for k, v in row.items() if k != 'expected'} for row in jobs])
    if args.export_only:
        print(f'{len(rows)} frozen tasks; {len(jobs)} new submission requests, each capped at {args.finalization_tokens} tokens.')
        return
    from methods.vllm_client import OpenAICompatibleNegotiationClient
    client = OpenAICompatibleNegotiationClient(args.base_url, args.model,
        api_key=os.environ.get('BENAC_P_VLLM_API_KEY', 'EMPTY'),
        max_tokens=source_manifest['max_tokens'], temperature=source_manifest['source_manifest']['temperature'])
    for row in jobs:
        records[row['id']] = finalize(client, row['task'], row['payload'], SYSTEM,
                                      baseline[row['id']], args.finalization_tokens)
        # Apply the same semantic validity rule as the original calibration.
        if records[row['id']]['status'] == 'ok' and not evaluate(row, records[row['id']])['valid']:
            records[row['id']].update(status='invalid', error='Invalid semantic submission.')
        dump(out/'answers.json', records)
        print(f"{row['id']}: {records[row['id']]['status']}", flush=True)
    result = dict(balanced=summary(rows, baseline), balanced_finalized=summary(rows, records),
                  per_recovered_task={row['id']: evaluate(row, records[row['id']]) for row in rows
                                      if records[row['id']].get('finalization_attempted')},
                  interpretation='All original valid outputs are frozen; only length-stopped outputs receive one bounded submission. '
                  'B/P success uses all selected tasks. First-pass truncation remains a separate metric. '
                  'This measures completion recovery, not a new independent reasoning-quality comparison.')
    dump(out/'comparison.json', result)
    lines = ['# Balanced bounded-finalization calibration', '', result['interpretation'], '',
             '| Setting | Valid | B valid + exact | P valid + optimal | Mean total completion tokens/task |',
             '|---|---:|---:|---:|---:|']
    def percent(value):return 'NA' if value is None else f'{value:.1%}'
    for name in ('balanced', 'balanced_finalized'):
        r = result[name]
        lines.append(f"| {name} | {r['valid_rate']:.1%} | {percent(r['belief_valid_and_exact_rate'])} | "
                     f"{percent(r['planning_valid_and_optimal_rate'])} | {r['protocol']['mean_total_completion_tokens_per_task']:.1f} |")
    p = result['balanced_finalized']['protocol']
    lines += ['', f"First-pass truncated tasks: {p['first_pass_truncated_tasks']}; "
              f"finalizations attempted: {p['finalization_attempted_tasks']}; "
              f"protocol-valid finalizations: {p['finalization_protocol_successes']}.",
              'Both attempts, including prompt-token cost and failed submissions, are retained in answers.json. '
              'A failed finalization is not automatically retried. See comparison.json for correctness per recovered task.']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    print(f"Report: {out/'report.md'}")


if __name__ == '__main__':
    main()
