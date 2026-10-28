"""Score B sets, separating protocol failures from semantic inference errors."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from benac_p.b_training_data import OPTIONS, score_set


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def evaluate(gold_rows, prediction_rows, pairs=()):
    gold = {r['id']: r for r in gold_rows}
    assert len(gold) == len(gold_rows), 'Duplicate gold ID'
    predictions = {r['id']: r for r in prediction_rows}
    assert len(predictions) == len(prediction_rows), 'Duplicate prediction ID'
    assert not predictions.keys() - gold.keys(), 'Prediction IDs not present in this gold split'
    rows = {}
    for identifier, example in gold.items():
        truth = example['answer']['possible_preferences']
        prediction = predictions.get(identifier)
        if prediction is None:
            rows[identifier] = dict(status='missing', exact=False, source_id=example['source_id'], gold_size=len(truth))
            continue
        answer = prediction.get('answer')
        if answer is None and 'possible_preferences' in prediction:
            answer = {'possible_preferences': prediction['possible_preferences']}
        valid_answer = isinstance(answer, dict) and set(answer) == {'possible_preferences'}
        scored = score_set(answer['possible_preferences'] if valid_answer else None, truth)
        if prediction.get('status', 'ok') != 'ok' or not scored['valid']:
            rows[identifier] = dict(status='protocol_failure', exact=False,
                                    source_id=example['source_id'], gold_size=len(truth))
            continue
        rows[identifier] = dict(status='valid', source_id=example['source_id'], gold_size=len(truth), **scored)

    def summarize(items):
        n = len(items)
        valid = [r for r in items if r['status'] == 'valid']
        return dict(n=n, valid=len(valid), missing=sum(r['status'] == 'missing' for r in items),
                    protocol_failures=sum(r['status'] == 'protocol_failure' for r in items),
                    exact_rate_all=sum(r['exact'] for r in items)/n if n else None,
                    exact_rate_valid=sum(r['exact'] for r in valid)/len(valid) if valid else None,
                    mean_false_exclusions_valid=sum(r['false_exclusions'] for r in valid)/len(valid) if valid else None,
                    mean_unsupported_possibilities_valid=sum(r['unsupported_possibilities'] for r in valid)/len(valid) if valid else None)
    by_source = defaultdict(list)
    for row in rows.values():
        by_source[row['source_id']].append(row)
    source_metrics = {s: summarize(rs) for s, rs in by_source.items()}
    usable_pairs = [p for p in pairs if p['before'] in rows and p['after'] in rows]
    both_valid = [p for p in usable_pairs if rows[p['before']]['status'] == rows[p['after']]['status'] == 'valid']
    both_exact = sum(rows[p['before']]['exact'] and rows[p['after']]['exact'] for p in both_valid)
    return dict(overall=summarize(list(rows.values())), by_source=source_metrics,
                source_macro_exact=sum(m['exact_rate_all'] for m in source_metrics.values())/len(source_metrics) if source_metrics else None,
                by_gold_support_size={size: summarize([r for r in rows.values() if r['gold_size'] == size]) for size in (1, 2, 3)},
                update_pairs=dict(present_in_split=len(usable_pairs), both_valid=len(both_valid), both_exact=both_exact,
                                  both_exact_rate_valid=both_exact/len(both_valid) if both_valid else None),
                note='Missing/protocol failures affect overall accuracy but are not counted as semantic false exclusions. Samples share source games; no independent-sample significance claim.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold', type=Path, required=True)
    prediction = parser.add_mutually_exclusive_group(required=True)
    prediction.add_argument('--predictions', type=Path)
    prediction.add_argument('--baseline', choices=('always_all', 'gold_self_check'))
    parser.add_argument('--pairs', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    gold = load_jsonl(args.gold)
    if args.predictions:
        predictions = load_jsonl(args.predictions)
    elif args.baseline == 'always_all':
        predictions = [dict(id=r['id'], answer={'possible_preferences': OPTIONS}) for r in gold]
    else:
        predictions = gold
    result = evaluate(gold, predictions, load_jsonl(args.pairs) if args.pairs else ())
    result['prediction_source'] = str(args.predictions) if args.predictions else args.baseline
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
