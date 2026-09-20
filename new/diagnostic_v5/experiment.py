"""Run the native-semantic structure-level B/P diagnostic.

The model never receives or emits a numeric belief.  Exact posteriors are used
only by the local scorer to evaluate actions under the certified teacher.
"""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from urllib.request import Request, urlopen
import argparse
import hashlib
import json
import math
import os
import random
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from training.b_sft.social_named_probe import Names, present, score

VALUES = ('want', 'neutral', 'avoid')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(HERE / name) != digest:
            raise ValueError('Frozen artifact changed: ' + name)
    for name, digest in manifest.get('dependencies', {}).items():
        if sha(ROOT / name) != digest:
            raise ValueError('Frozen dependency changed: ' + name)
    return manifest, json.loads((HERE / 'cases.json').read_text())


def _judgment_text(case, judgment):
    query = case['task']['input']['queries'][0]
    names = Names(case['task']['input'], 0)
    target = names.players[query['player']] + ' / ' + names.goals[query['goal']]
    possible = ', '.join(judgment['possible_preferences'])
    return (f'Target: {target}.\npossible_preferences: [{possible}]\n'
            f'favored: {judgment["favored"]}')


def b_request(case, assisted=False):
    request = deepcopy(case['requests']['B'])
    if not assisted:
        return request
    likelihood = case['likelihood_by_preference']
    positive = [(name, value) for name, value in zip(VALUES, likelihood) if value > 1e-12]
    groups = []
    for value in sorted({round(value, 12) for _, value in positive}, reverse=True):
        labels = [name for name, weight in positive if abs(weight - value) < 1e-10]
        groups.append(labels)
    descriptions = []
    for name, value in zip(VALUES, likelihood):
        if value <= 1e-12:
            descriptions.append(f'- {name}: the displayed voluntary sequence is impossible')
        else:
            rank = next(i for i, labels in enumerate(groups) if name in labels)
            level = ('most likely' if rank == 0 else
                     'least likely' if rank == len(groups) - 1 else 'intermediate likelihood')
            tie = ' (tied)' if len(groups[rank]) > 1 else ''
            descriptions.append(f'- {name}: {level}{tie}')
    text = request['messages'][1]['content']
    marker = '\nRESPONSE INSTRUCTIONS'
    before, after = text.split(marker, 1)
    request['messages'][1]['content'] = before + (
        '\n\nQUALITATIVE PARTNER-PLAN ASSISTANCE\n'
        'A verified partner planner gives the following ordering for how compatible '
        'the displayed voluntary sequence is with each preference. No probabilities '
        'or posterior are supplied; combine this planning fact with the visible prior '
        'and constraints.\n' + '\n'.join(descriptions) + marker + after)
    return request


def p_request(case, judgment):
    """Inject exactly the deployed semantic B output into a fresh P context."""
    request = deepcopy(case['requests']['P_infer'])
    text = request['messages'][1]['content']
    text = text.replace(
        'Infer the relevant preferences from the visible information and choose your next action.',
        'Choose your next action using the supplied partner judgment and visible game state.')
    marker = '\nRESPONSE INSTRUCTIONS'
    before, after = text.split(marker, 1)
    request['messages'][1]['content'] = before + (
        '\n\nSUPPLIED PARTNER JUDGMENT\n'
        'This is the complete output of the partner-inference stage. Use it directly. '
        'possible_preferences retains every supported value; favored is the uniquely '
        'most supported value under the stated rule or undetermined. No probability '
        'is available to the agent.\n' + _judgment_text(case, judgment) +
        marker + after)
    return request


def valid_judgment(value):
    if not isinstance(value, dict) or set(value) != {'possible_preferences', 'favored'}:
        return False
    possible = value['possible_preferences']; favored = value['favored']
    if (not isinstance(possible, list) or not possible or len(possible) != len(set(possible))
            or any(item not in VALUES for item in possible)):
        return False
    if favored not in VALUES + ('undetermined',):
        return False
    if len(possible) == 1:
        return favored == possible[0]
    return favored == 'undetermined' or favored in possible


def parse_b(case, completion):
    if completion.get('status') == 'infrastructure_failure':
        return None, 'infrastructure_failure'
    if completion.get('finish_reason') == 'length':
        return None, 'truncated'
    try:
        calls = completion['raw_message']['tool_calls']
        assert len(calls) == 1
        function = calls[0]['function']
        assert function['name'] == 'SUBMIT_BELIEFS'
        args = json.loads(function['arguments'])
        assert set(args) == {'judgments'} and len(args['judgments']) == 1
        item = args['judgments'][0]
        query = case['task']['input']['queries'][0]
        names = Names(case['task']['input'], 0)
        assert item['player'] == names.players[query['player']]
        assert item['goal'] == names.goals[query['goal']]
        judgment = {key: item[key] for key in ('possible_preferences', 'favored')}
        assert valid_judgment(judgment)
        return judgment, 'ok'
    except (ValueError, KeyError, TypeError, AssertionError):
        return None, 'format_failure'


def action_index(case, completion):
    result = score(case['task'], completion, 'action_tools', 0)
    if result['status'] != 'ok':
        return None, result['status']
    function = completion['raw_message']['tool_calls'][0]['function']
    args = json.loads(function['arguments'])
    action = {'response' if function['name'] in ('ACCEPT', 'REJECT') else 'action':
              function['name'], **args}
    return present(case['task'], 0)['legal_actions'].index(action), 'ok'


def values(case):
    posterior = case['teacher_posterior']
    payoffs = case['task']['teacher']['per_world_payoffs']
    return [sum(weight * world[0] for weight, world in zip(posterior, action))
            for action in payoffs]


def reference(case):
    local = values(case); best = max(local)
    choices = [i for i, value in enumerate(local) if abs(value - best) < 1e-9]
    return dict(status='ok', action_indices=choices, utility=best, regret=0.,
                tie_rule='all exact own-utility maximizers')


def model_value(case, completion):
    index, status = action_index(case, completion)
    if index is None:
        return dict(status=status, utility=None, regret=None)
    local = values(case)
    return dict(status=status, action_index=index, utility=local[index],
                regret=max(local) - local[index])


def belief_scores(prediction, gold):
    if prediction is None:
        return dict(exact=None, set_exact=None, favored_exact=None,
                    false_exclusions=None, unsupported_additions=None)
    predicted, target = set(prediction['possible_preferences']), set(gold['possible_preferences'])
    return dict(exact=prediction['favored'] == gold['favored'] and predicted == target,
                set_exact=predicted == target,
                favored_exact=prediction['favored'] == gold['favored'],
                false_exclusions=len(target - predicted),
                unsupported_additions=len(predicted - target))


def run_case(case, call):
    b_completion = call('B', b_request(case))
    model_judgment, b_status = parse_b(case, b_completion)
    assisted_judgment = None; assisted_status = 'not_planned'
    if case['planning_assisted_B']:
        assisted_judgment, assisted_status = parse_b(
            case, call('B_with_qualitative_partner_plan', b_request(case, assisted=True)))

    correct_p = model_value(case, call(
        'correct_B_model_P', p_request(case, case['gold_judgment'])))
    end_to_end = model_value(case, call(
        'end_to_end_P', deepcopy(case['requests']['P_infer'])))
    if model_judgment is None:
        model_p = dict(status='blocked_by_' + b_status, utility=None, regret=None)
    else:
        model_p = model_value(case, call(
            'model_B_model_P', p_request(case, model_judgment)))
    oracle = reference(case)
    b = belief_scores(model_judgment, case['gold_judgment'])
    assisted = belief_scores(assisted_judgment, case['gold_judgment'])

    def difference(left, right):
        return None if left is None or right is None else left - right

    row = dict(
        case_id=case['id'], structure_id=case['structure_id'],
        structure_family=case['structure_family'], mode=case['mode'],
        provenance=case['provenance'], B_status=b_status,
        model_judgment=model_judgment, gold_judgment=case['gold_judgment'],
        B=b, B_with_qualitative_partner_plan_status=assisted_status,
        assisted_model_judgment=assisted_judgment, assisted_B=assisted,
        correct_B_model_P=correct_p, model_B_model_P=model_p,
        end_to_end_P=end_to_end, correct_B_reference_P=oracle,
        B_repair_gain=difference(correct_p['utility'], model_p['utility']),
        P_gap_given_correct_B=correct_p['regret'],
        composition_gap=model_p['regret'], end_to_end_gap=end_to_end['regret'],
        action_changed_under_B_repair=(None if model_p.get('action_index') is None or
            correct_p.get('action_index') is None else
            model_p['action_index'] != correct_p['action_index']))
    row['qualitative_partner_plan_exact_gain'] = (
        None if b['exact'] is None or assisted['exact'] is None else
        int(assisted['exact']) - int(b['exact']))
    local = values(case); lower = [v for v in local if max(local) - v > 1e-9]
    row['decision_gap'] = max(local) - max(lower) if lower else None
    return row


def _strip_judgment_prompt(request):
    text = request['messages'][1]['content']
    before, rest = text.split('\n\nSUPPLIED PARTNER JUDGMENT\n', 1)
    _, after = rest.split('\nRESPONSE INSTRUCTIONS', 1)
    clean = deepcopy(request)
    clean['messages'][1]['content'] = before + '\nRESPONSE INSTRUCTIONS' + after
    return clean


def audit_cases(cases):
    grouped = defaultdict(list)
    for case in cases:
        grouped[case['structure_id']].append(case)
        for request in (b_request(case), p_request(case, case['gold_judgment'])):
            serialized = json.dumps(request)
            for forbidden in ('joint_distribution', 'preference_weights',
                              'SUBMIT_DISTRIBUTION', 'want=', 'neutral=', 'avoid='):
                assert forbidden not in serialized
    assert len(grouped) == 16 and len(cases) == 32
    assert len({c['structure_family'] for c in cases}) == 16
    assert Counter(c['mode'] for c in cases) == {'binary': 16, 'linear': 16}
    for pair in grouped.values():
        assert {c['provenance'] for c in pair} == {'voluntary', 'preset'}
        first, second = pair
        assert first['gold_judgment'] != second['gold_judgment']
        assert first['task']['input']['current_state'] == second['task']['input']['current_state']
        assert first['task']['input']['legal_actions'] == second['task']['input']['legal_actions']
        assert first['task']['teacher']['per_world_payoffs'] == second['task']['teacher']['per_world_payoffs']
        assert not set(reference(first)['action_indices']) & set(reference(second)['action_indices'])
        for case in pair:
            a = p_request(case, case['gold_judgment'])
            altered = deepcopy(case['gold_judgment'])
            altered['favored'] = ('undetermined' if altered['favored'] != 'undetermined'
                                  else altered['possible_preferences'][0])
            if not valid_judgment(altered):
                altered = {'possible_preferences': ['want'], 'favored': 'want'}
            b = p_request(case, altered)
            assert _strip_judgment_prompt(a) == _strip_judgment_prompt(b)
    return dict(structures=16, matched_cases=32,
                native_semantic_contract=True,
                no_numeric_belief_in_model_requests=True,
                same_state_actions_payoffs=True,
                semantic_labels_differ=True,
                exact_reference_actions_disjoint=True)


def _stat(items):
    items = [x for x in items if x is not None]
    return dict(valid=len(items), mean=sum(items) / len(items) if items else None)


def row_metric(row, key):
    mapping = {
        'B_exact': row['B']['exact'],
        'B_set_exact': row['B']['set_exact'],
        'B_favored_exact': row['B']['favored_exact'],
        'B_false_exclusions': row['B']['false_exclusions'],
        'B_unsupported_additions': row['B']['unsupported_additions'],
        'gold_B_planning_regret': row['P_gap_given_correct_B'],
        'model_B_planning_regret': row['composition_gap'],
        'end_to_end_P_regret': row['end_to_end_gap'],
    }
    return mapping.get(key, row.get(key))


def summarize(rows, cases, repeats):
    metrics = ('B_exact', 'B_set_exact', 'B_favored_exact', 'B_false_exclusions',
        'B_unsupported_additions', 'gold_B_planning_regret',
        'model_B_planning_regret', 'end_to_end_P_regret', 'B_repair_gain',
        'qualitative_partner_plan_exact_gain')
    row_level = {key: _stat([row_metric(row, key) for row in rows]) for key in metrics}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['structure_id']].append(row)
    structure_level = {}
    for key in metrics:
        means = []
        for selected in grouped.values():
            valid = [row_metric(row, key) for row in selected
                     if row_metric(row, key) is not None]
            if valid:
                means.append(sum(valid) / len(valid))
        structure_level[key] = _stat(means)
    statuses = {}
    for condition in ('B', 'B_with_qualitative_partner_plan',
                      'correct_B_model_P', 'model_B_model_P', 'end_to_end_P'):
        if condition == 'B':
            states = [row['B_status'] for row in rows]
        elif condition == 'B_with_qualitative_partner_plan':
            states = [row['B_with_qualitative_partner_plan_status'] for row in rows
                      if row['B_with_qualitative_partner_plan_status'] != 'not_planned']
        else:
            states = [row[condition]['status'] for row in rows]
        statuses[condition] = dict(returned=len(states), statuses=dict(Counter(states)))
    return dict(
        planned_rows=len(cases) * repeats, returned_rows=len(rows),
        missing_rows=len(cases) * repeats - len(rows),
        complete_composition_rows=sum(row['model_B_model_P']['utility'] is not None
                                      and row['correct_B_model_P']['utility'] is not None
                                      for row in rows),
        row_level=row_level, structure_level=structure_level,
        condition_coverage=statuses,
        interpretation=('B is scored only on the native semantic contract. '
            'P regret is evaluated backend-side under the certified posterior. '
            'B_repair_gain is a paired intervention on the same model planner; '
            'there is intentionally no reference-P cell under a model semantic B.'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True, nargs='+')
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--temperature', type=float, default=1.)
    parser.add_argument('--top-p', type=float, default=1.)
    parser.add_argument('--top-k', type=int, default=-1)
    parser.add_argument('--concurrency-per-endpoint', type=int, default=16)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=float, default=180.)
    args = parser.parse_args()
    if (args.repeats < 1 or args.max_tokens < 1 or args.temperature < 0 or
            not 0 < args.top_p <= 1 or args.concurrency_per_endpoint < 1):
        parser.error('Invalid sampling settings')
    manifest, cases = load(); audit = audit_cases(cases)
    args.output.mkdir(parents=True, exist_ok=False)
    config = dict(model=args.model, base_url=args.base_url, repeats=args.repeats,
        temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
        repetition_penalty=1., max_tokens=args.max_tokens, seed=args.seed,
        retry=0, timeout=args.timeout,
        concurrency_per_endpoint=args.concurrency_per_endpoint,
        independent_contexts=True, manifest_sha256=sha(HERE / 'manifest.json'),
        runtime_sha256=sha(Path(__file__)), audit=audit)
    (args.output / 'protocol.json').write_text(json.dumps(config, indent=2) + '\n')
    jobs = [(case, replica) for case in cases for replica in range(args.repeats)]
    random.Random(args.seed).shuffle(jobs)
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('OPENAI_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENAI_API_KEY']
    locks = [threading.BoundedSemaphore(args.concurrency_per_endpoint)
             for _ in args.base_url]
    log_lock = threading.Lock()

    def execute(case, replica):
        endpoint = int(hashlib.sha256(f'{case["id"]}:{replica}'.encode()).hexdigest()[:8], 16) % len(args.base_url)
        def call(condition, request):
            seed_condition = ('semantic_controlled_P' if condition in
                              ('correct_B_model_P', 'model_B_model_P') else condition)
            call_seed = int(hashlib.sha256(
                f'{args.seed}:{case["id"]}:{replica}:{seed_condition}'.encode()
                ).hexdigest()[:8], 16)
            body = dict(request, model=args.model, temperature=args.temperature,
                        top_p=args.top_p, top_k=args.top_k, repetition_penalty=1.,
                        max_tokens=args.max_tokens, seed=call_seed)
            started = time.monotonic()
            try:
                with locks[endpoint]:
                    req = Request(args.base_url[endpoint].rstrip('/') + '/chat/completions',
                        data=json.dumps(body).encode(), headers=headers, method='POST')
                    with urlopen(req, timeout=args.timeout) as response:
                        payload = json.load(response)
                choice = payload['choices'][0]
                completion = dict(raw_message=choice['message'],
                                  finish_reason=choice['finish_reason'])
                usage = payload.get('usage')
            except Exception as exc:
                completion = dict(status='infrastructure_failure',
                                  error_type=type(exc).__name__,
                                  http_status=getattr(exc, 'code', None))
                usage = None
            record = dict(case_id=case['id'], structure_id=case['structure_id'],
                replica=replica, condition=condition, seed=call_seed,
                endpoint_index=endpoint, elapsed_seconds=time.monotonic() - started,
                request=body, completion=completion, usage=usage)
            with log_lock:
                with (args.output / 'calls.jsonl').open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
            return completion
        return dict(run_case(case, call), replica=replica)

    rows = []
    with ThreadPoolExecutor(max_workers=len(args.base_url) * args.concurrency_per_endpoint) as pool:
        futures = [pool.submit(execute, case, replica) for case, replica in jobs]
        for number, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            rows.sort(key=lambda row: (row['structure_id'], row['provenance'], row['replica']))
            (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
            (args.output / 'summary.json').write_text(
                json.dumps(summarize(rows, cases, args.repeats), indent=2) + '\n')
            print(f'{number}/{len(jobs)} structure replicas complete', flush=True)
    summary = summarize(rows, cases, args.repeats)
    complete = len(rows) == len(jobs) and all(
        count == 0 for condition in summary['condition_coverage'].values()
        for status, count in condition['statuses'].items()
        if status == 'infrastructure_failure')
    name = 'COMPLETE.json' if complete else 'INCOMPLETE.json'
    (args.output / name).write_text(json.dumps(config, indent=2) + '\n')
    if not complete:
        raise SystemExit('Incomplete inference run; inspect infrastructure failures')


if __name__ == '__main__':
    main()
