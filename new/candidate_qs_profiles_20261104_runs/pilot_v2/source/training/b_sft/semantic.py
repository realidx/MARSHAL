"""Dependency-light, first-response B scoring and reviewable reports."""

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

VALUES = ('want', 'neutral', 'avoid')


def valid_set(values):
    return (isinstance(values, list) and 0 < len(values) <= 3
            and all(isinstance(v, str) and v in VALUES for v in values)
            and len(set(values)) == len(values))


def parse_response(raw, truncated=False, allow_preface=True):
    """One native tool call only. Preserve failures; never repair/retry a first answer."""
    if truncated:
        return dict(status='truncated', answer=None)
    text = raw.strip()
    # Retain special tokens in raw logs, but accept the normal Qwen EOS suffix.
    text = re.sub(r'(?:<\|im_end\|>|<\|endoftext\|>)\s*$', '', text).strip()
    match = re.fullmatch(r'(.*?)<tool_call>\s*(.*?)\s*</tool_call>', text, flags=re.S)
    if (not match or text.count('<tool_call>') != 1 or text.count('</tool_call>') != 1):
        return dict(status='protocol_failure', answer=None)
    if match[1].strip() and not allow_preface:
        return dict(status='protocol_failure', answer=None)
    try:
        call = json.loads(match[2])
        if not isinstance(call, dict) or set(call) != {'name', 'arguments'}:
            raise ValueError('tool fields')
        answer = call['arguments']
        if (call['name'] != 'SUBMIT_JUDGMENT' or not isinstance(answer, dict)
                or set(answer) != {'possible_preferences'} or not valid_set(answer['possible_preferences'])):
            raise ValueError('answer fields')
    except (ValueError, TypeError):
        return dict(status='protocol_failure', answer=None)
    # Existing system prompts permit brief reasoning. Do not turn it into a
    # format failure; log it without making it a supervised target.
    return dict(status='ok', answer=answer, preface=match[1].strip())


def gold_answer(row):
    answer = row['messages'][-1]['tool_calls'][0]['function']['arguments']
    return json.loads(answer) if isinstance(answer, str) else answer


def read_pairs(path):
    if not path:
        return []
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    seen, result = set(), []
    for row in rows:
        key = (row['before'], row['after'])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def summarize(rows):
    valid = [r for r in rows if r['status'] == 'ok']
    n = len(rows)
    return dict(n=n, valid=len(valid), status_counts=dict(Counter(r['status'] for r in rows)),
                format_success_rate=len(valid)/n if n else None,
                exact_rate_all=sum(r['exact'] for r in rows)/n if n else None,
                exact_rate_valid=sum(r['exact'] for r in valid)/len(valid) if valid else None,
                mean_false_exclusions_valid=sum(len(r['false_exclusions']) for r in valid)/len(valid) if valid else None,
                mean_extra_possibilities_valid=sum(len(r['extra_possibilities']) for r in valid)/len(valid) if valid else None)


def score_records(records, predictions, pairs=(), baseline=()):
    gold = {r['id']: r for r in records}
    pred = {p['id']: p for p in predictions}
    base = {p['id']: p for p in baseline}
    if len(gold) != len(records) or len(pred) != len(predictions) or pred.keys() - gold.keys():
        raise ValueError('Duplicate IDs or predictions outside requested split')
    rows, by_id = [], {}
    for identifier, record in gold.items():
        truth = gold_answer(record)['possible_preferences']
        if not valid_set(truth):
            raise ValueError('Invalid gold set')
        p = pred.get(identifier, dict(status='missing', answer=None))
        values = (p.get('answer') or {}).get('possible_preferences')
        status = p['status']
        if status == 'ok' and not valid_set(values):
            status = 'protocol_failure'
        valid = status == 'ok'
        exact = valid and set(values) == set(truth)
        b = base.get(identifier)
        b_values = (b.get('answer') or {}).get('possible_preferences') if b else None
        b_exact = (b.get('status') == 'ok' and valid_set(b_values) and set(b_values) == set(truth)) if b else None
        try:
            payload = json.loads(record['messages'][1]['content'])
        except ValueError:
            payload = {}
        row = dict(id=identifier, source_id=record['source_id'], query=payload.get('query'),
                   n_players=payload.get('game', {}).get('n_players'),
                   goal_mode=('unknown' if not payload.get('game', {}).get('goals') else
                              'binary' if all(g.get('binary', True) for g in payload['game']['goals']) else
                              'linear' if all(not g.get('binary', True) for g in payload['game']['goals']) else 'mixed'),
                   history_length=len(payload.get('history', [])), gold=truth, prediction=values,
                   status=status, exact=exact,
                   false_exclusions=[v for v in truth if v not in values] if valid else None,
                   extra_possibilities=[v for v in values if v not in truth] if valid else None,
                   baseline_prediction=b_values, baseline_exact=b_exact,
                   comparison=None if b_exact is None else ('correct' if b_exact else 'wrong') + '->' + ('correct' if exact else 'wrong'),
                   raw_response=p.get('raw_response'), baseline_raw_response=b.get('raw_response') if b else None)
        rows.append(row)
        by_id[identifier] = row
    pair_rows = []
    for pair in pairs:
        if pair['before'] not in by_id or pair['after'] not in by_id:
            continue
        before, after = by_id[pair['before']], by_id[pair['after']]
        if before['source_id'] != after['source_id'] or before['source_id'] != pair['source_id']:
            raise ValueError('Pair source mismatch')
        if before['query'] != after['query']:
            raise ValueError('Pair query mismatch')
        a = gold[pair['before']]['messages'][1]['content']
        b = gold[pair['after']]['messages'][1]['content']
        old_history, new_history = json.loads(a)['history'], json.loads(b)['history']
        if len(new_history) != len(old_history) + 1 or new_history[:-1] != old_history:
            raise ValueError('Pair must add exactly one public event')
        kind = 'maintain' if set(before['gold']) == set(after['gold']) else 'update'
        both_valid = before['status'] == after['status'] == 'ok'
        pair_rows.append(dict(before_id=pair['before'], after_id=pair['after'], source_id=pair['source_id'],
                              kind=kind, natural=pair.get('natural'), new_event=new_history[-1],
                              gold_before=before['gold'], gold_after=after['gold'],
                              prediction_before=before['prediction'], prediction_after=after['prediction'],
                              status_before=before['status'], status_after=after['status'],
                              both_valid=both_valid, both_exact=before['exact'] and after['exact'],
                              predicted_change=(set(before['prediction']) != set(after['prediction'])) if both_valid else None))
    sources = defaultdict(list)
    for row in rows:
        sources[row['source_id']].append(row)
    source_metrics = {key: summarize(value) for key, value in sources.items()}
    pair_metrics = {}
    for kind in ('all', 'maintain', 'update'):
        group = [p for p in pair_rows if kind == 'all' or p['kind'] == kind]
        valid = [p for p in group if p['both_valid']]
        correct = sum(p['both_exact'] for p in group)
        pair_metrics[kind] = dict(n=len(group), both_valid=len(valid), both_exact=correct,
                                  both_exact_rate_all=correct/len(group) if group else None,
                                  both_exact_rate_valid=correct/len(valid) if valid else None)
    metrics = dict(overall=summarize(rows), by_source=source_metrics,
                   source_macro_exact=sum(v['exact_rate_all'] for v in source_metrics.values())/len(sources) if sources else None,
                   by_gold_size={str(n): summarize([r for r in rows if len(r['gold']) == n]) for n in (1, 2, 3)},
                   formation=summarize([r for r in rows if r['history_length'] == 0]),
                   by_player_count={str(n): summarize([r for r in rows if r['n_players'] == n])
                                    for n in sorted({r['n_players'] for r in rows}, key=str)},
                   by_goal_mode={mode: summarize([r for r in rows if r['goal_mode'] == mode])
                                 for mode in sorted({r['goal_mode'] for r in rows})},
                   pairs=pair_metrics, supplied_pairs=len(pairs), unavailable_pairs=len(pairs)-len(pair_rows))
    # Cheap controls expose the all-possible shortcut without another model pass.
    all_possible_exact = sum(len(r['gold']) == 3 for r in rows)/len(rows) if rows else None
    metrics['shortcut_diagnostics'] = dict(
        prediction_counts=dict(Counter('|'.join(v for v in VALUES if v in r['prediction'])
                                       for r in rows if r['status'] == 'ok')),
        all_possible_baseline_exact=all_possible_exact,
        excess_exact_over_all_possible=(metrics['overall']['exact_rate_all']-all_possible_exact) if rows else None,
        informative_questions=summarize([r for r in rows if len(r['gold']) < 3]))
    return metrics, rows, pair_rows


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def write_report(directory, records, predictions, pairs=(), baseline=(), metadata=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metrics, rows, pair_rows = score_records(records, predictions, pairs, baseline)
    write_json(directory / 'metrics.json', dict(metrics, metadata=metadata or {}))
    write_jsonl(directory / 'predictions.jsonl', predictions)
    write_jsonl(directory / 'questions.jsonl', rows)
    write_jsonl(directory / 'pairs.jsonl', pair_rows)
    for name, content in [('questions', rows), ('pairs', pair_rows)]:
        with (directory / f'{name}.csv').open('w', newline='') as stream:
            if content:
                writer = csv.DictWriter(stream, fieldnames=list(content[0]))
                writer.writeheader()
                for row in content:
                    writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                                     for k, v in row.items()})
    return metrics


@dataclass
class Selection:
    """Baseline is eligible: no improvement means select the original model."""
    best_score: float | None = None
    best_step: int = 0
    bad_evaluations: int = 0
    last_step: int = -1

    def observe(self, step, score, patience):
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Selection score must be finite in [0, 1]')
        if step <= self.last_step:
            raise ValueError('Selection steps must increase')
        improved = self.best_score is None or score > self.best_score
        if improved:
            self.best_score, self.best_step, self.bad_evaluations = score, step, 0
        elif step > 0:
            self.bad_evaluations += 1
        self.last_step = step
        return improved, patience > 0 and self.bad_evaluations >= patience

    def to_dict(self):
        return asdict(self)
