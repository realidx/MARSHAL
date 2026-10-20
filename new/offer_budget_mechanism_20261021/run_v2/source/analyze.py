"""Summarize the fixed experiment without selecting on positive outcomes."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def root_summary(result):
    row = next(r for r in result['rows'] if r['root_index'] == 0)
    offers = [(a, q) for a, q in zip(row['actions'], row['Q']) if a['action'] == 'OFFER']
    passes = [q for a, q in zip(row['actions'], row['Q']) if a['action'] == 'PASS']
    informative = [q for q in row['query_details'] if len(q['support']) > 1]
    return dict(V_full=row['V_full'], V_no_own_queries=row['V_no_own_queries'],
        best_query_Q=row['best_query_Q'], best_offer_Q=max(q for a, q in offers),
        PASS_Q=passes[0], query_gap=row['first_query_gap'],
        query_access_value=row['query_access_value'], query_probability=row['query_probability'],
        informative_queries=informative, offer_values=[dict(action=a,Q=q) for a,q in offers],
        ex_ante_payoffs=result['ex_ante_payoffs'], nodes=result['nodes'],
        certificate_max_gain=result['certificate']['max_own_deviation_gain'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    assert (args.run / 'COMPLETE.json').exists(), 'Wait for the fixed run to complete'
    summary = json.loads((args.run / 'summary.json').read_text())
    paired = []
    files = [args.run / 'summary.json', args.run / 'COMPLETE.json', args.run / 'pipeline_snapshot.json']
    for name in dict.fromkeys(r['name'] for r in summary['results']):
        pair = dict(name=name)
        for suffix in ('unlimited', 'quota1'):
            path = args.run / f'{name}_{suffix}_result.json'
            files.append(path)
            result = json.loads(path.read_text())
            pair[suffix] = (dict(status='certified', **root_summary(result))
                            if result['status']=='certified' else
                            dict(status=result['status'], reason=result.get('reason')))
        if all(pair[s]['status']=='certified' for s in ('unlimited','quota1')):
            pair['initial_value_change_quota_minus_unlimited'] = pair['quota1']['V_full']-pair['unlimited']['V_full']
            pair['initial_query_gap_change'] = pair['quota1']['query_gap']-pair['unlimited']['query_gap']
            pair['initial_query_access_change'] = pair['quota1']['query_access_value']-pair['unlimited']['query_access_value']
        paired.append(pair)
    data = dict(pairs=paired,
        scope='Seven predeclared convenience parents; initial actor information cell per parent. Paired variants independently re-solved, including partner adaptation and profile selection. Not prevalence or unique-equilibrium claim.',
        failures_are_missing_not_zero=True,
        informative_answer_value_scope='Same-query masks measured only for informative best queries; absence is not evidence every possible slot has zero value',
        artifact_inputs={str(path):digest(path) for path in files})
    write(args.run / 'paired_analysis.json', data)
    write(args.run / 'analysis_snapshot.json', dict(status='completed-cpu-analysis-only',
        actual_argv=sys.argv, resolved_config=dict(input_run=str(args.run), tolerance=1e-8,
            selection='all cases from completed fixed run; no post-hoc positive filtering',
            cell='initial root_index=0', fields='primary utility, first query gap, no-own-queries access value, same-query answer masks'),
        model_identity='not applicable', sampling_reward_contract='read-only result aggregation, no training/sampling',
        source_sha256=digest(Path(__file__)), inputs=data['artifact_inputs'],
        runtime=dict(python=sys.version, executable=sys.executable, platform=platform.platform()),
        result_sha256=digest(args.run/'paired_analysis.json')))
    for pair in paired:
        print(json.dumps({k:(dict(status=v['status'],V=v.get('V_full'),query_gap=v.get('query_gap'),access=v.get('query_access_value'),informative_queries=v.get('informative_queries'))
                            if k in ('unlimited','quota1') else v)
                          for k,v in pair.items()}), flush=True)


if __name__ == '__main__':
    main()
