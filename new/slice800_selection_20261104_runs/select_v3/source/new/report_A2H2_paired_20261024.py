"""Paired mechanism audit; no new game, S, reference selection or training rule."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from new.three_player_complexity_v1_20261023 import common as c
from new.strategic_game_v1_20261021.rules import StrategicRules

VERSION = 'A2H2-paired-mechanism-audit-v1'
REG = c.ROOT/'examples/strategic_slices/versions/A2H2_paired_audit_v1_20261024/SNAPSHOT.json'
EPS = 1e-8


def positive(row):
    return max(row['S_private'], row['S_history']) > EPS


def action_key(action):
    return c.stable(action)


def load_run(run, inputs, prefix):
    for name in ('pipeline_snapshot.json', 'COMPLETE.json', 'results.json', 'jobs.json'):
        inputs[f'{prefix}:{name}'] = c.identity(run/name)
    jobs = {j['index']: j for j in json.loads((run/'jobs.json').read_text())}
    results = json.loads((run/'results.json').read_text())
    assert len({r['original_index'] for r in results}) == len(results)
    for r in results:
        if r.get('reference_accepted'):
            ref = run/r['reference_path']
            assert c.sha(ref) == r['reference_sha256']
            inputs[f'{prefix}:reference:{r["index"]}'] = c.identity(ref)
        if r.get('labels') == 'MEASURED':
            labels = run/Path(r['result_path']).parent/'labels.jsonl.gz'
            assert c.sha(labels) == r['labels_sha256']
            inputs[f'{prefix}:labels:{r["index"]}'] = c.identity(labels)
    return jobs, results


def summarize_game(run, job, result):
    if result.get('labels') != 'MEASURED':
        return dict(original_index=job['original_index'], index=job['index'],
                    status=result['status'], measured=False)
    path = run/Path(result['result_path']).parent/'labels.jsonl.gz'
    scopes = {s: Counter() for s in ('counterfactual', 'on_reference')}
    witnesses = {}
    groups = defaultdict(list)
    worlds = StrategicRules(job['raw']).worlds
    query_rows = []
    final_turn = len(job['raw']['game']['round_robin'])-1
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            is_positive = positive(row)
            entry_positive = any(x.get('entry_action_regret', 0) > EPS for x in row['S_items'])
            social = terminal_social = False
            for item in row['S_items']:
                p = item.get('omitted_action_probabilities')
                if p is None or row['phase'] != 'response' or len(row['own_optimal']) < 2:
                    continue
                own = max(row['Q'])-sum(a*b for a, b in zip(p, row['Q']))
                others = max(row['Q_others'][a] for a in row['own_optimal'])-sum(a*b for a, b in zip(p, row['Q_others']))
                if own <= EPS and others > EPS:
                    social = True
                    if row['turn'] == final_turn:
                        assert abs(item['response_secondary_loss']-others) < 1e-7
                        terminal_social = True
            for scope, counts in scopes.items():
                if scope == 'on_reference' and row['reference_mass'] <= 0:
                    continue
                counts['contexts'] += 1
                counts['positive_own_S'] += is_positive
                counts['positive_own_S_proposal'] += is_positive and row['phase'] == 'proposal'
                counts['positive_own_S_response'] += is_positive and row['phase'] == 'response'
                counts['positive_own_S_and_entry_regret'] += is_positive and entry_positive
                counts['positive_own_S_proposal_and_entry_regret'] += is_positive and entry_positive and row['phase'] == 'proposal'
                counts['positive_private_S'] += row['S_private'] > EPS
                counts['positive_history_S'] += row['S_history'] > EPS
                counts['positive_response_tie_information'] += social
                counts['positive_terminal_response_tie_information'] += terminal_social
                counts['own_S_or_response_tie_diagnostic'] += is_positive or social
                counts['positive_Q_span'] += row['span'] > EPS
                counts['reference_decision_mass'] += row['reference_mass']
                counts['positive_own_S_reference_mass'] += row['reference_mass']*is_positive
                counts['own_S_times_reference_mass'] += row['reference_mass']*max(row['S_private'], row['S_history'])
            for channel in ('private', 'history'):
                score = row['S_'+channel]
                if score <= EPS:
                    continue
                for category in (channel, channel+'_'+row['phase']):
                    if category not in witnesses or (score, row['reference_mass'], -row['node']) > witnesses[category][0]:
                        witnesses[category] = ((score, row['reference_mass'], -row['node']), row)
            # Same public node + own type + all other retained direct answers.
            # Public facts and native menu are identical within each such group.
            for item in row['S_items']:
                mask = item['omitted']
                if mask[0] != 'private' or item.get('full_contexts', 1) <= 1:
                    continue
                other = [a for a in row['private_answers'] if a[:2] != mask[1:]]
                key = (row['node'], row['actor'], c.stable(row['own_type']), c.stable(other), tuple(mask))
                groups[key].append(row)
            if row['query_gap'] is not None and row['query_gap'] > EPS:
                targets = []
                for ai in row['own_optimal']:
                    action = row['actions'][ai]
                    if action.get('action') != 'INVESTIGATE':
                        continue
                    support = {worlds[w][action['player']][action['goal']]
                               for w, m in zip(row['world_ids'], row['posterior']) if m > 0}
                    targets.append(dict(action=action, support=sorted(support), already_inferred=len(support) == 1))
                assert targets
                query_rows.append(dict(node=row['node'], cell=row['cell'], reference_mass=row['reference_mass'],
                                       gap=row['query_gap'], targets=targets,
                                       all_best_targets_inferred=all(t['already_inferred'] for t in targets)))
    group_counts = Counter()
    group_examples = []
    for key, rows in groups.items():
        assert len(rows) == next(x['full_contexts'] for x in rows[0]['S_items'] if tuple(x['omitted']) == key[-1])
        sets = [{action_key(r['actions'][a]) for a in r['own_optimal']} for r in rows]
        no_common = not set.intersection(*sets)
        any_positive = any(next(x['S'] for x in r['S_items'] if tuple(x['omitted']) == key[-1]) > EPS for r in rows)
        proposal = rows[0]['phase'] == 'proposal'
        group_counts['ambiguous_private_groups'] += 1
        group_counts['no_common_current_own_optimum'] += no_common
        group_counts['positive_own_S_groups'] += any_positive
        group_counts['proposal_no_common_current_own_optimum'] += no_common and proposal
        group_counts['proposal_no_common_optimum_with_own_S'] += no_common and proposal and any_positive
        if no_common and proposal and any_positive:
            group_examples.append(dict(node=key[0], actor=key[1], omitted=list(key[-1]),
                cases=[{k:r[k] for k in ('cell','private_answers','actions','Q','own_optimal','S_private','reference_mass')} for r in rows]))
    witness_rows = {category: value[1] for category, value in witnesses.items()}
    return dict(original_index=job['original_index'], index=job['index'], measured=True,
        status=result['status'], nodes=result['nodes'], cutoff_leaves=result['cutoff_leaves'],
        reference_sha256=result['reference_sha256'], scopes=scopes, private_groups=group_counts,
        witnesses=witness_rows, private_proposal_switch_examples=group_examples[:5],
        query_diagnostic=dict(strict_contexts=len(query_rows),
            inferred_best_target_contexts=sum(r['all_best_targets_inferred'] for r in query_rows),
            on_reference_strict_contexts=sum(r['reference_mass']>0 for r in query_rows),
            on_reference_inferred_best_target_contexts=sum(r['reference_mass']>0 and r['all_best_targets_inferred'] for r in query_rows),
            rows=query_rows),
        stored_summary=result['summary'])


def aggregate(rows):
    measured = [r for r in rows if r['measured']]
    out = dict(measured=len(measured), original_indices=[r['original_index'] for r in measured], scopes={})
    for scope in ('counterfactual', 'on_reference'):
        count = Counter()
        for r in measured:
            count.update(r['scopes'][scope])
        metrics = ('positive_own_S','positive_own_S_proposal','positive_own_S_response',
            'positive_own_S_proposal_and_entry_regret','positive_private_S','positive_history_S',
            'positive_response_tie_information','positive_terminal_response_tie_information')
        parents = {k:[r['original_index'] for r in measured if r['scopes'][scope].get(k,0)>0] for k in metrics}
        denominator = count['contexts']
        mass = count['reference_decision_mass']
        ratios = dict(positive_own_S_context_fraction=count['positive_own_S']/denominator if denominator else None,
            equal_parent_mean_positive_fraction=float(np.mean([r['scopes'][scope]['positive_own_S']/r['scopes'][scope]['contexts'] for r in measured])) if measured else None,
            reference_occupancy_positive_fraction=count['positive_own_S_reference_mass']/mass if mass else None)
        out['scopes'][scope] = dict(counts=count, positive_parents=parents, ratios=ratios)
    out['private_groups'] = dict(sum((Counter(r['private_groups']) for r in measured), Counter()))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--H2', type=Path, required=True)
    parser.add_argument('--A2H2', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    c.VERSION, c.REG = VERSION, REG
    inputs = {}
    h_jobs, h_results = load_run(args.H2, inputs, 'H2')
    a_jobs, a_results = load_run(args.A2H2, inputs, 'A2H2')
    assert {j['original_index'] for j in h_jobs.values()} == {j['original_index'] for j in a_jobs.values()}
    c.snapshot(args.output, dict(operation='Full A2H2 versus H2 paired mechanism audit',
        H2=str(args.H2), A2H2=str(args.A2H2), numeric_epsilon=EPS,
        inclusion='All33 frozen paired parents; matched comparison only where both have measured labels',
        source_reference_selection='Existing first certified candidate; no new solve or result-dependent choice',
        S='Existing own-terminal-utility single-item omission; unchanged',
        social='Separate current response tie information diagnostic; terminal responses checked against saved actual loss',
        private_groups='Identical public node, own type, other answers and private mask; compare intersection of own-current-optimal actions',
        query='Strict own-query gap with reference-relative inferred-answer classification; not automatic acquisition value',
        rates='Context-count, equal-parent and reference-decision-occupancy fractions; none is model exposure or D',
        missing='Unavailable certificate/labels excluded only from matched comparison and retained in all33 coverage'), inputs)
    data = {}
    for arm, run, jobs, results in [('H2',args.H2,h_jobs,h_results),('A2H2',args.A2H2,a_jobs,a_results)]:
        data[arm] = [summarize_game(run,jobs[r['index']],r) for r in results]
    hm = {r['original_index']:r for r in data['H2'] if r['measured']}
    am = {r['original_index']:r for r in data['A2H2'] if r['measured']}
    common = sorted(hm.keys() & am.keys())
    report = dict(version=VERSION, attempted_per_arm=33,
        all_available={arm:aggregate(rows) for arm,rows in data.items()},
        missing_labels={arm:sorted(j['original_index'] for j in jobs.values() if j['original_index'] not in {r['original_index'] for r in data[arm] if r['measured']}) for arm,jobs in [('H2',h_jobs),('A2H2',a_jobs)]},
        paired_indices=common,paired=dict(H2=aggregate([hm[i] for i in common]),A2H2=aggregate([am[i] for i in common])),
        per_game=data,model_D='NOT_MEASURED', production='UNCHANGED_V8',training='NOT_RUN',
        limits=['A2H2 adds a cumulative commitment option, not a new exclusive action rule',
            'Changed game may select a different certified reference; no cross-equilibrium invariance claim',
            'Zero counterfactual reach remains unavailable; off-reference positive contexts are not model mistakes',
            'Private own-optimum switches are current proposal diagnostics; social tie channel is separate'])
    c.write(args.output/'PAIRED.json',report)
    c.write(args.output/'COMPLETE.json',dict(paired_games=len(common),report_sha256=c.sha(args.output/'PAIRED.json'),
        pipeline_snapshot_sha256=c.sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps({k:v for k,v in report.items() if k not in ('per_game','limits')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
