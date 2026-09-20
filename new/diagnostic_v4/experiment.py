"""Run and score the frozen structure-level B/P diagnostic.

The runner talks only to user-supplied OpenAI-compatible endpoints.  Reference
planning and all utility scoring are deterministic local computations.
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


def b_request(case, assisted=False):
    request = deepcopy(case['requests']['B'])
    prefix = request['messages'][1]['content'].split('RESPONSE INSTRUCTIONS')[0]
    if assisted:
        likelihood = case['likelihood_by_preference']
        prefix += ('\nVERIFIED PARTNER-PLANNING ASSISTANCE\n'
            'Under the fixed partner policy, the likelihood of the displayed voluntary event sequence is: '
            + '; '.join(f'{name}={value:.12g}' for name, value in zip(VALUES, likelihood))
            + '. These are likelihoods, not posterior probabilities. Combine them with the stated prior and constraints.\n')
    request['messages'][1]['content'] = prefix + (
        '\nRESPONSE INSTRUCTIONS\nFor the queried partner preference, infer the full posterior distribution. '
        'Briefly explain, then call SUBMIT_DISTRIBUTION with want, neutral and avoid probabilities summing to 1. '
        'This numeric interface is only for the controlled diagnostic.')
    request['tools'] = [dict(type='function', function=dict(name='SUBMIT_DISTRIBUTION',
        parameters=dict(type='object', additionalProperties=False, required=list(VALUES),
            properties={key: dict(type='number', minimum=0, maximum=1) for key in VALUES})))]
    return request


def p_request(case, belief):
    request = deepcopy(case['requests']['P_gold'])
    text = request['messages'][1]['content']
    before, rest = text.split('EVENTS IN ORDER', 1)
    state = rest.split('CURRENT BINDING STATE', 1)[1].split('CORRECT CURRENT BELIEF', 1)[0]
    instructions = text.split('RESPONSE INSTRUCTIONS', 1)[1]
    before = before.replace('Choose your next action using the supplied correct belief.',
                            'Choose your next action using the supplied belief.')
    query = case['task']['input']['queries'][0]
    names = Names(case['task']['input'], 0)
    target = names.players[query['player']] + "'s preference for " + names.goals[query['goal']]
    request['messages'][1]['content'] = before + 'CURRENT BINDING STATE' + state + (
        '\nSUPPLIED CURRENT BELIEF\nUse this distribution directly for this decision. '
        'All other preferences remain as publicly listed. Past behavioral evidence is intentionally withheld '
        'in this controlled planning condition.\n' + target + ': ' +
        '; '.join(f'{key}={value:.12g}' for key, value in zip(VALUES, belief)) +
        '\nRESPONSE INSTRUCTIONS' + instructions)
    return request


def parse_b(completion):
    if completion.get('status') == 'infrastructure_failure':
        return None, 'infrastructure_failure'
    if completion.get('finish_reason') == 'length':
        return None, 'truncated'
    try:
        calls = completion['raw_message']['tool_calls']
        assert len(calls) == 1
        function = calls[0]['function']
        assert function['name'] == 'SUBMIT_DISTRIBUTION'
        args = json.loads(function['arguments'])
        assert set(args) == set(VALUES)
        values = [args[key] for key in VALUES]
        assert all(type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1
                   for value in values)
        assert abs(sum(values) - 1) < 1e-6
        return [value / sum(values) for value in values], 'ok'
    except (ValueError, KeyError, TypeError, AssertionError):
        return None, 'format_failure'


def action_index(case, completion):
    task = case['task']
    result = score(task, completion, 'action_tools', 0)
    if result['status'] != 'ok':
        return None, result['status']
    function = completion['raw_message']['tool_calls'][0]['function']
    args = json.loads(function['arguments'])
    action = {'response' if function['name'] in ('ACCEPT', 'REJECT') else 'action': function['name'], **args}
    return present(task, 0)['legal_actions'].index(action), 'ok'


def values(case, belief):
    payoffs = case['task']['teacher']['per_world_payoffs']
    return [sum(weight * world[0] for weight, world in zip(belief, action)) for action in payoffs]


def reference(case, belief):
    local = values(case, belief)
    best = max(local)
    choices = [index for index, value in enumerate(local) if abs(value - best) < 1e-9]
    truth = values(case, case['gold_belief'])
    utility = sum(truth[index] for index in choices) / len(choices)
    return dict(status='ok', action_indices=choices,
        tie_rule='uniform exact own-utility maximizers', utility=utility,
        regret=max(truth) - utility)


def model_value(case, completion, input_belief=None):
    index, status = action_index(case, completion)
    if index is None:
        return dict(status=status, utility=None, regret=None,
                    input_belief_planning_regret=None)
    truth = values(case, case['gold_belief'])
    supplied = values(case, input_belief if input_belief is not None else case['gold_belief'])
    return dict(status=status, action_index=index, utility=truth[index],
        regret=max(truth) - truth[index],
        input_belief_planning_regret=max(supplied) - supplied[index])


def total_variation(left, right):
    return sum(abs(x - y) for x, y in zip(left, right)) / 2


def run_case(case, call):
    b_completion = call('B', b_request(case))
    model_belief, b_status = parse_b(b_completion)
    assisted_belief = None; assisted_status = 'not_planned'
    if case['planning_assisted_B']:
        assisted_belief, assisted_status = parse_b(call(
            'B_with_planning_assistance', b_request(case, assisted=True)))

    gold_p = model_value(case, call('correct_B_model_P', p_request(case, case['gold_belief'])))
    end_to_end = model_value(case, call('end_to_end_P', deepcopy(case['requests']['P_infer'])))
    cells = {'correct_B_model_P': gold_p,
             'correct_B_reference_P': reference(case, case['gold_belief'])}
    if model_belief is None:
        for key in ('model_B_model_P', 'model_B_reference_P'):
            cells[key] = dict(status='blocked_by_' + b_status, utility=None, regret=None,
                              input_belief_planning_regret=None)
    else:
        cells['model_B_model_P'] = model_value(
            case, call('model_B_model_P', p_request(case, model_belief)), model_belief)
        cells['model_B_reference_P'] = reference(case, model_belief)

    def gain(repaired, original):
        left, right = cells[repaired]['utility'], cells[original]['utility']
        return None if left is None or right is None else left - right

    row = dict(case_id=case['id'], structure_id=case['structure_id'],
        structure_family=case['structure_family'], mode=case['mode'], provenance=case['provenance'],
        B_status=b_status, model_belief=model_belief, gold_belief=case['gold_belief'],
        B_total_variation=None if model_belief is None else total_variation(model_belief, case['gold_belief']),
        B_with_planning_assistance_status=assisted_status,
        assisted_model_belief=assisted_belief,
        assisted_B_total_variation=(None if assisted_belief is None else
                                    total_variation(assisted_belief, case['gold_belief'])),
        end_to_end_P=end_to_end, cells=cells,
        B_repair_gain=gain('correct_B_model_P', 'model_B_model_P'),
        P_repair_gain=gain('model_B_reference_P', 'model_B_model_P'),
        P_repair_given_correct_B=gain('correct_B_reference_P', 'correct_B_model_P'),
        B_repair_with_reference_P=gain('correct_B_reference_P', 'model_B_reference_P'))
    row['planning_assistance_TV_gain'] = (None if row['B_total_variation'] is None or
        row['assisted_B_total_variation'] is None else
        row['B_total_variation'] - row['assisted_B_total_variation'])
    row['four_cells_complete'] = all(cell['utility'] is not None for cell in cells.values())
    row['interaction_gamma'] = (row['B_repair_with_reference_P'] - row['B_repair_gain']
                                if row['four_cells_complete'] else None)
    row['total_gap'] = gain('correct_B_reference_P', 'model_B_model_P')
    for key in ('P_repair_given_correct_B', 'B_repair_with_reference_P'):
        assert row[key] is None or row[key] >= -1e-9
    if row['four_cells_complete']:
        assert abs(row['total_gap'] - row['B_repair_gain'] - row['P_repair_given_correct_B']) < 1e-9
        assert abs(row['total_gap'] - row['P_repair_gain'] - row['B_repair_with_reference_P']) < 1e-9
    truth = values(case, case['gold_belief'])
    lower = [value for value in truth if max(truth) - value > 1e-9]
    row['decision_gap'] = max(truth) - max(lower) if lower else None
    row['near_optimal_tolerance'] = case['task']['teacher'].get('own_tolerance', .1)
    return row


def audit_cases(cases):
    structures = defaultdict(list)
    for case in cases:
        structures[case['structure_id']].append(case)
    assert len(structures) == 16
    assert len({case['structure_family'] for case in cases}) == 16
    for structure_id, pair in structures.items():
        assert {case['provenance'] for case in pair} == {'voluntary', 'preset'}
        first, second = pair
        assert first['task']['input']['current_state'] == second['task']['input']['current_state']
        assert first['task']['input']['legal_actions'] == second['task']['input']['legal_actions']
        assert first['task']['teacher']['per_world_payoffs'] == second['task']['teacher']['per_world_payoffs']
        for belief in ([1/3] * 3, [1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                       first['gold_belief'], second['gold_belief']):
            assert p_request(first, belief) == p_request(second, belief)
            assert reference(first, belief)['action_indices'] == reference(second, belief)['action_indices']
        voluntary = next(case for case in pair if case['provenance'] == 'voluntary')
        prior = next(case for case in pair if case['provenance'] == 'preset')['gold_belief']
        likelihood = voluntary['likelihood_by_preference']
        implied = [p * q for p, q in zip(prior, likelihood)]
        implied = [value / sum(implied) for value in implied]
        assert total_variation(implied, voluntary['gold_belief']) < 1e-9
    return dict(structures=len(structures), matched_cases=len(cases),
        geometry_unique=True, same_state_actions_payoffs=True,
        same_injected_belief_prompt_and_reference=True,
        likelihood_reproduces_posterior=True)


def _stat(values):
    values = [value for value in values if value is not None]
    return dict(valid=len(values), mean=sum(values) / len(values) if values else None)


def row_metric(row, key):
    if key == 'gold_B_planning_regret':
        return row['cells']['correct_B_model_P']['regret']
    if key == 'model_B_conditional_planning_regret':
        return row['cells']['model_B_model_P'].get('input_belief_planning_regret')
    if key == 'end_to_end_P_regret':
        return row['end_to_end_P']['regret']
    return row.get(key)


def summarize(rows, cases, repeats):
    planned_rows = len(cases) * repeats
    metrics = ('B_total_variation', 'gold_B_planning_regret',
        'model_B_conditional_planning_regret', 'end_to_end_P_regret',
        'B_repair_gain', 'P_repair_gain', 'P_repair_given_correct_B',
        'B_repair_with_reference_P', 'interaction_gamma', 'total_gap',
        'planning_assistance_TV_gain')
    row_level = {key: _stat([row_metric(row, key) for row in rows]) for key in metrics}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['structure_id']].append(row)
    structure_values = {key: [] for key in metrics}
    strict_coverage = {}
    for structure_id, selected in grouped.items():
        strict_coverage[structure_id] = dict(rows=len(selected), complete_rows=sum(
            row['four_cells_complete'] and row['end_to_end_P']['utility'] is not None for row in selected))
        for key in metrics:
            values_ = [row_metric(row, key) for row in selected]
            valid = [value for value in values_ if value is not None]
            if valid:
                structure_values[key].append(sum(valid) / len(valid))
    structure_level = {key: _stat(values_) for key, values_ in structure_values.items()}
    by_mode = {}
    for mode in ('binary', 'linear'):
        ids = {case['structure_id'] for case in cases if case['mode'] == mode}
        by_mode[mode] = {key: _stat([
            sum(valid) / len(valid) for structure_id in ids
            if (valid := [row_metric(row, key) for row in grouped.get(structure_id, [])
                          if row_metric(row, key) is not None])]) for key in metrics}
    statuses = {}
    for condition in ('B', 'B_with_planning_assistance', 'correct_B_model_P',
                      'model_B_model_P', 'end_to_end_P'):
        if condition == 'B':
            states = [row['B_status'] for row in rows]
        elif condition == 'B_with_planning_assistance':
            states = [row['B_with_planning_assistance_status'] for row in rows
                      if row['B_with_planning_assistance_status'] != 'not_planned']
        elif condition == 'end_to_end_P':
            states = [row['end_to_end_P']['status'] for row in rows]
        else:
            states = [row['cells'][condition]['status'] for row in rows]
        statuses[condition] = dict(returned=len(states), statuses=dict(Counter(states)))
    return dict(planned_rows=planned_rows, returned_rows=len(rows), missing_rows=planned_rows-len(rows),
        complete_four_cell_rows=sum(row['four_cells_complete'] for row in rows),
        row_level=row_level, structure_level=structure_level, by_mode=by_mode,
        structure_coverage=strict_coverage, condition_coverage=statuses,
        interpretation=('Primary aggregates weight each independent structure equally after averaging its matched cases '
            'and replicas. Each repair gain uses its own valid paired subset; do not subtract means with different coverage. '
            'The two repair paths decompose one total gap, not four additive causal contributions.'))


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
    manifest, cases = load()
    audit = audit_cases(cases)
    args.output.mkdir(parents=True, exist_ok=False)
    config = dict(model=args.model, base_url=args.base_url, repeats=args.repeats,
        temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
        repetition_penalty=1., max_tokens=args.max_tokens, seed=args.seed,
        retry=0, timeout=args.timeout, concurrency_per_endpoint=args.concurrency_per_endpoint,
        independent_contexts=True, manifest_sha256=sha(HERE/'manifest.json'),
        runtime_sha256=sha(Path(__file__)), audit=audit)
    (args.output/'protocol.json').write_text(json.dumps(config, indent=2)+'\n')
    jobs = [(case, replica) for case in cases for replica in range(args.repeats)]
    random.Random(args.seed).shuffle(jobs)
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('OPENAI_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENAI_API_KEY']
    locks = [threading.BoundedSemaphore(args.concurrency_per_endpoint) for _ in args.base_url]
    log_lock = threading.Lock()

    def execute(case, replica):
        endpoint_index = int(hashlib.sha256(f'{case["id"]}:{replica}'.encode()).hexdigest()[:8], 16) % len(args.base_url)
        def call(condition, request):
            seed_condition = 'controlled_P' if condition in ('correct_B_model_P', 'model_B_model_P') else condition
            call_seed = int(hashlib.sha256(
                f'{args.seed}:{case["id"]}:{replica}:{seed_condition}'.encode()).hexdigest()[:8], 16)
            body = dict(request, model=args.model, temperature=args.temperature, top_p=args.top_p,
                        top_k=args.top_k, repetition_penalty=1., max_tokens=args.max_tokens, seed=call_seed)
            started = time.monotonic()
            try:
                with locks[endpoint_index]:
                    req = Request(args.base_url[endpoint_index].rstrip('/') + '/chat/completions',
                        data=json.dumps(body).encode(), headers=headers, method='POST')
                    with urlopen(req, timeout=args.timeout) as response:
                        payload = json.load(response)
                choice = payload['choices'][0]
                completion = dict(raw_message=choice['message'], finish_reason=choice['finish_reason'])
                usage = payload.get('usage')
            except Exception as exc:
                completion = dict(status='infrastructure_failure', error_type=type(exc).__name__,
                                  http_status=getattr(exc, 'code', None))
                usage = None
            record = dict(case_id=case['id'], structure_id=case['structure_id'], replica=replica,
                condition=condition, seed=call_seed, endpoint_index=endpoint_index,
                elapsed_seconds=time.monotonic()-started, request=body, completion=completion, usage=usage)
            with log_lock:
                with (args.output/'calls.jsonl').open('a') as stream:
                    stream.write(json.dumps(record)+'\n')
            return completion
        return dict(run_case(case, call), replica=replica)

    rows = []
    with ThreadPoolExecutor(max_workers=len(args.base_url)*args.concurrency_per_endpoint) as pool:
        futures = [pool.submit(execute, case, replica) for case, replica in jobs]
        for number, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            rows.sort(key=lambda row: (row['structure_id'], row['provenance'], row['replica']))
            (args.output/'results.json').write_text(json.dumps(rows, indent=2)+'\n')
            (args.output/'summary.json').write_text(json.dumps(summarize(rows, cases, args.repeats), indent=2)+'\n')
            print(f'{number}/{len(jobs)} structure replicas complete', flush=True)
    summary = summarize(rows, cases, args.repeats)
    complete = (len(rows) == len(jobs) and all(
        count == 0 for condition in summary['condition_coverage'].values()
        for status, count in condition['statuses'].items() if status == 'infrastructure_failure'))
    (args.output/('COMPLETE.json' if complete else 'INCOMPLETE.json')).write_text(json.dumps(config, indent=2)+'\n')
    if not complete:
        raise SystemExit('Incomplete inference run; inspect infrastructure failures')


if __name__ == '__main__':
    main()
