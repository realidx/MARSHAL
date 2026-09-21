"""Audit diagnostic regret/repair identities and semantic-B sufficiency.

This script needs no model calls.  Given a diagnostic_v5/v6 result directory,
it emits the row-level quantities needed to distinguish scoring, missingness,
and aggregation explanations for an apparent regret/repair inconsistency.
"""
from collections import defaultdict
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from training.b_sft.preference_contract import belief


VALUES = ('want', 'neutral', 'avoid')
DEFAULT_CASES = ROOT / 'new/diagnostic_v5/cases.json'
DEFAULT_RUN = (ROOT /
    'runs/diagnostic/q0-v5-t0-no-cache-serial-868698/structure_v5')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def metric_weights(rows, getter):
    """Reproduce v5 structure-macro weights for one metric."""
    grouped = defaultdict(list)
    for index, row in enumerate(rows):
        if getter(row) is not None:
            grouped[row['structure_id']].append(index)
    if not grouped:
        return {}
    result = {}
    for indices in grouped.values():
        for index in indices:
            result[index] = 1 / len(grouped) / len(indices)
    return result


def close(left, right, tolerance=1e-9):
    return left is not None and right is not None and abs(left-right) <= tolerance


def row_audit(run):
    rows = load(run / 'results.json')
    protocol = load(run / 'protocol.json')
    summary = load(run / 'summary.json')
    get_model = lambda row: row['model_B_model_P'].get('regret')
    get_correct = lambda row: row['correct_B_model_P'].get('regret')
    get_repair = lambda row: row.get('B_repair_gain')
    weights = {
        'model_B_regret': metric_weights(rows, get_model),
        'correct_B_regret': metric_weights(rows, get_correct),
        'repair_gain': metric_weights(rows, get_repair),
    }
    audited = []
    failures = []
    for index, row in enumerate(rows):
        model = row['model_B_model_P']
        correct = row['correct_B_model_P']
        reference = row['correct_B_reference_P'].get('utility')
        model_regret = model.get('regret')
        correct_regret = correct.get('regret')
        repair = row.get('B_repair_gain')
        expected = (None if model_regret is None or correct_regret is None
                    else model_regret-correct_regret)
        residual = (None if expected is None or repair is None
                    else repair-expected)
        record = {
            'case_id': row['case_id'],
            'structure_id': row['structure_id'],
            'replica': row['replica'],
            'checkpoint_hash': protocol.get('checkpoint_hash'),
            'model': protocol.get('model'),
            'manifest_sha256': protocol.get('manifest_sha256'),
            'runtime_sha256': protocol.get('runtime_sha256'),
            'model_B_valid': row.get('B_status') == 'ok',
            'model_B_P_valid': model.get('status') == 'ok',
            'correct_B_P_valid': correct.get('status') == 'ok',
            'scoring_belief': 'teacher_posterior',
            'reference_value': reference,
            'normalization': 'raw terminal own utility; no normalization',
            'U_modelB_modelP': model.get('utility'),
            'U_correctB_modelP': correct.get('utility'),
            'regret_modelB': model_regret,
            'regret_correctB': correct_regret,
            'repair_gain': repair,
            'expected_repair_from_regrets': expected,
            'identity_residual': residual,
            'aggregation_weight_modelB_regret':
                weights['model_B_regret'].get(index),
            'aggregation_weight_correctB_regret':
                weights['correct_B_regret'].get(index),
            'aggregation_weight_repair': weights['repair_gain'].get(index),
        }
        audited.append(record)
        if residual is not None and abs(residual) > 1e-9:
            failures.append(record)
        if model_regret is not None and not close(
                model_regret, reference-model['utility']):
            failures.append(dict(record, failure='model regret/reference mismatch'))
        if correct_regret is not None and not close(
                correct_regret, reference-correct['utility']):
            failures.append(dict(record, failure='correct regret/reference mismatch'))

    structure = summary['structure_level']
    reported = {
        'model_B_regret': structure['model_B_planning_regret']['mean'],
        'correct_B_regret': structure['gold_B_planning_regret']['mean'],
        'repair_gain': structure['B_repair_gain']['mean'],
    }
    aggregate_residual = (reported['repair_gain'] -
        (reported['model_B_regret']-reported['correct_B_regret']))
    paired_rows = [item for item in audited
                   if item['regret_modelB'] is not None
                   and item['regret_correctB'] is not None
                   and item['repair_gain'] is not None]
    paired_by_structure = defaultdict(list)
    for item in paired_rows:
        paired_by_structure[item['structure_id']].append(item)

    def paired_macro(key):
        values = [sum(item[key] for item in selected)/len(selected)
                  for selected in paired_by_structure.values()]
        return None if not values else sum(values)/len(values)

    paired_model = paired_macro('regret_modelB')
    paired_correct = paired_macro('regret_correctB')
    paired_repair = paired_macro('repair_gain')
    return audited, {
        'run': str(run.relative_to(ROOT)),
        'results_sha256': sha(run / 'results.json'),
        'rows': len(rows),
        'paired_valid_rows': sum(
            item['regret_modelB'] is not None and
            item['regret_correctB'] is not None and
            item['repair_gain'] is not None for item in audited),
        'row_identity_failures': len(failures),
        'max_abs_row_identity_residual': max(
            (abs(item['identity_residual']) for item in audited
             if item['identity_residual'] is not None), default=None),
        'reported_structure_macro': reported,
        'reported_regret_difference':
            reported['model_B_regret']-reported['correct_B_regret'],
        'reported_identity_residual': aggregate_residual,
        'common_pair_structure_macro': {
            'structures': len(paired_by_structure),
            'model_B_regret': paired_model,
            'correct_B_regret': paired_correct,
            'regret_difference': (None if paired_model is None else
                                  paired_model-paired_correct),
            'repair_gain': paired_repair,
            'identity_residual': (None if paired_repair is None else
                paired_repair-(paired_model-paired_correct)),
        },
        'weights_identical_on_paired_rows': all(
            item['aggregation_weight_modelB_regret'] ==
            item['aggregation_weight_correctB_regret'] ==
            item['aggregation_weight_repair']
            for item in audited if item['repair_gain'] is not None),
    }


def mass_grid(judgment, denominator=100):
    support = [VALUES.index(value)
               for value in judgment['possible_preferences']]
    if len(support) == 1:
        candidates = [[0, 0, 0]]
        candidates[0][support[0]] = denominator
    elif len(support) == 2:
        candidates = []
        for first in range(1, denominator):
            row = [0, 0, 0]
            row[support[0]] = first
            row[support[1]] = denominator-first
            candidates.append(row)
    else:
        candidates = []
        for first in range(1, denominator-1):
            for second in range(1, denominator-first):
                row = [first, second, denominator-first-second]
                candidates.append(row)
    for counts in candidates:
        mass = {name: count/denominator
                for name, count in zip(VALUES, counts)}
        if belief(mass) == judgment:
            yield [mass[name] for name in VALUES]


def optimal_set(payoffs, posterior, tolerance=1e-9):
    values = [sum(weight*world[0]
                  for weight, world in zip(posterior, action))
              for action in payoffs]
    best = max(values)
    return tuple(index for index, value in enumerate(values)
                 if best-value <= tolerance), values


def semantic_audit(cases_path):
    cases = load(cases_path)
    rows = []
    for case in cases:
        judgment = case['gold_judgment']
        payoffs = case['task']['teacher']['per_world_payoffs']
        witnesses = {}
        orderings = set()
        for posterior in mass_grid(judgment):
            optimum, values = optimal_set(payoffs, posterior)
            witnesses.setdefault(optimum, {
                'posterior': dict(zip(VALUES, posterior)),
                'optimal_action_indices': list(optimum),
                'optimal_value': max(values),
            })
            signature = tuple(
                0 if abs(left-right) <= 1e-9 else (1 if left > right else -1)
                for left in values for right in values)
            orderings.add(signature)
        exact_optimum, _ = optimal_set(payoffs, case['teacher_posterior'])
        rows.append({
            'case_id': case['id'],
            'structure_id': case['structure_id'],
            'gold_judgment': judgment,
            'grid_denominator': 100,
            'feasible_grid_beliefs': sum(1 for _ in mass_grid(judgment)),
            'distinct_action_orderings': len(orderings),
            'distinct_optimal_action_sets': len(witnesses),
            'semantic_summary_changes_optimum': len(witnesses) > 1,
            'exact_posterior_optimal_action_indices': list(exact_optimum),
            'witnesses': list(witnesses.values())[:4],
        })
    return rows, {
        'cases': len(rows),
        'cases_with_multiple_action_orderings': sum(
            row['distinct_action_orderings'] > 1 for row in rows),
        'cases_where_same_semantic_summary_allows_different_optima': sum(
            row['semantic_summary_changes_optimum'] for row in rows),
        'scope': (
            'Constructive 0.01-grid witness search under the public B margin; '
            'a positive finding proves ambiguity, while a negative finding is '
            'not a continuous-space proof of invariance.'),
    }


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'new/training_debug_20260921')
    args = parser.parse_args()
    rows, identity = row_audit(args.run.resolve())
    semantic_rows, semantic = semantic_audit(args.cases.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output/'diagnostic_record_audit.csv', rows)
    report = {
        'identity_audit': identity,
        'semantic_summary_audit': semantic,
        'semantic_cases': semantic_rows,
        'unavailable_claimed_runs': {
            'old_BP99': 'raw diagnostic scoring records not present locally',
            'new_BP99': 'raw diagnostic scoring records not present locally',
            'new_BP139': 'raw diagnostic scoring records not present locally',
        },
    }
    (args.output/'diagnostic_consistency_audit.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({
        'identity_audit': identity,
        'semantic_summary_audit': semantic,
        'row_table': str(args.output/'diagnostic_record_audit.csv'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
