"""Run the clean-state native-semantic B/P diagnostic.

The B and end-to-end calls retain the visible history.  The two controlled P
calls receive the same history-free decision state and differ only in the
supplied semantic judgment.
"""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from urllib.request import Request, urlopen
import argparse
import hashlib
import json
import os
import random
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from new.diagnostic_v5 import experiment as v5
from new.diagnostic_v6.semantic_sufficiency import certify


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
    return v5.b_request(case, assisted=assisted)


def p_request(case, judgment):
    """Insert semantic B into a history-free, state-sufficient P request."""
    request = deepcopy(case['requests']['P_clean'])
    text = request['messages'][1]['content']
    marker = '\nRESPONSE INSTRUCTIONS'
    before, after = text.split(marker, 1)
    request['messages'][1]['content'] = before + (
        '\n\nSUPPLIED PARTNER JUDGMENT\n'
        'This is the complete output of the partner-inference stage. Use it '
        'directly; do not reconstruct a different judgment. possible_preferences '
        'retains every supported value; favored is the uniquely most supported '
        'value under the stated rule or undetermined. No posterior probability is '
        'available to the agent.\n' + v5._judgment_text(case, judgment) +
        marker + after)
    return request


def run_case(case, call):
    b_completion = call('B', b_request(case))
    model_judgment, b_status = v5.parse_b(case, b_completion)
    assisted_judgment = None
    assisted_status = 'not_planned'
    if case['planning_assisted_B']:
        assisted_judgment, assisted_status = v5.parse_b(
            case, call('B_with_qualitative_partner_plan',
                       b_request(case, assisted=True)))

    correct_p = v5.model_value(case, call(
        'correct_B_model_P', p_request(case, case['gold_judgment'])))
    end_to_end = v5.model_value(case, call(
        'end_to_end_P', deepcopy(case['requests']['P_infer'])))
    if model_judgment is None:
        model_p = dict(status='blocked_by_' + b_status,
                       utility=None, regret=None)
    else:
        model_p = v5.model_value(case, call(
            'model_B_model_P', p_request(case, model_judgment)))
    oracle = v5.reference(case)
    b = v5.belief_scores(model_judgment, case['gold_judgment'])
    assisted = v5.belief_scores(assisted_judgment, case['gold_judgment'])

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
        controlled_P_history_free=True,
        action_changed_under_B_repair=(
            None if model_p.get('action_index') is None or
            correct_p.get('action_index') is None else
            model_p['action_index'] != correct_p['action_index']))
    row['qualitative_partner_plan_exact_gain'] = (
        None if b['exact'] is None or assisted['exact'] is None else
        int(assisted['exact']) - int(b['exact']))
    local = v5.values(case)
    lower = [value for value in local if max(local) - value > 1e-9]
    row['decision_gap'] = max(local) - max(lower) if lower else None
    return row


def _strip_judgment_prompt(request):
    text = request['messages'][1]['content']
    before, rest = text.split('\n\nSUPPLIED PARTNER JUDGMENT\n', 1)
    _, after = rest.split('\nRESPONSE INSTRUCTIONS', 1)
    clean = deepcopy(request)
    clean['messages'][1]['content'] = (
        before + '\nRESPONSE INSTRUCTIONS' + after)
    return clean


def audit_cases(cases):
    grouped = defaultdict(list)
    forbidden_history = ('events in order', 'observed player choice',
                         'preset event', 'voluntary', 'imposed setup',
                         'displayed history')
    for case in cases:
        grouped[case['structure_id']].append(case)
        saved_certificate = case.get('semantic_decision_certificate')
        if not saved_certificate or not saved_certificate.get('decision_sufficient'):
            raise AssertionError('Uncertified semantic planning case')
        reproduced = certify(case['gold_judgment'],
                             case['task']['teacher']['per_world_payoffs'])
        if any(reproduced.get(key) != value
               for key, value in saved_certificate.items()):
            raise AssertionError('Semantic decision certificate changed')
        base = case['requests']['P_clean']
        base_text = json.dumps(base).lower()
        if any(token in base_text for token in forbidden_history):
            raise AssertionError('Behavioral evidence leaked into controlled P')
        prompt = base['messages'][1]['content']
        for required in ('CURRENT BINDING STATE', 'KNOWN PREFERENCES',
                         'GOAL REQUIREMENTS BY PLAYER',
                         'Investigation uses remaining'):
            if required not in prompt:
                raise AssertionError('Planning state missing: ' + required)
        if _strip_judgment_prompt(
                p_request(case, case['gold_judgment'])) != base:
            raise AssertionError('Judgment injection changed the planning state')
        serialized = json.dumps(
            [b_request(case), p_request(case, case['gold_judgment'])])
        for forbidden in ('joint_distribution', 'preference_weights',
                          'SUBMIT_DISTRIBUTION', 'want=', 'neutral=', 'avoid='):
            if forbidden in serialized:
                raise AssertionError('Forbidden numeric belief: ' + forbidden)

    if len(grouped) != 16 or len(cases) != 32:
        raise AssertionError('Unexpected inventory')
    if len({case['structure_family'] for case in cases}) != 16:
        raise AssertionError('Structures are not independent')
    if Counter(case['mode'] for case in cases) != {'binary': 16, 'linear': 16}:
        raise AssertionError('Game modes are not balanced')
    for pair in grouped.values():
        if {case['provenance'] for case in pair} != {'voluntary', 'preset'}:
            raise AssertionError('Missing matched provenance')
        first, second = pair
        if first['gold_judgment'] == second['gold_judgment']:
            raise AssertionError('Semantic B did not change')
        if first['task']['input']['current_state'] != second['task']['input']['current_state']:
            raise AssertionError('Physical state changed')
        if first['task']['input']['legal_actions'] != second['task']['input']['legal_actions']:
            raise AssertionError('Legal actions changed')
        if (first['task']['teacher']['per_world_payoffs'] !=
                second['task']['teacher']['per_world_payoffs']):
            raise AssertionError('Per-world payoffs changed')
        if first['requests']['P_clean'] != second['requests']['P_clean']:
            raise AssertionError('Controlled-P base requests differ across pair')
        if not set(v5.reference(first)['action_indices']).isdisjoint(
                v5.reference(second)['action_indices']):
            raise AssertionError('Reference-optimal actions overlap')
        semantic_sets = [set(case['semantic_decision_certificate'][
            'invariant_optimal_action_indices']) for case in pair]
        if semantic_sets[0] & semantic_sets[1]:
            raise AssertionError('Invariant semantic-optimal actions overlap')
        if first['requests']['P_clean']['tools'] != second['requests']['P_clean']['tools']:
            raise AssertionError('Controlled-P tools differ')
    return dict(
        structures=16, matched_cases=32, native_semantic_contract=True,
        no_numeric_belief_in_model_requests=True,
        same_state_actions_payoffs=True, semantic_labels_differ=True,
        exact_reference_actions_disjoint=True,
        all_semantic_regions_decision_sufficient=True,
        semantic_certificate_method='exact-rational-polytope-vertices-v1',
        invariant_semantic_optimal_actions_disjoint=True,
        controlled_P_history_free=True,
        controlled_P_pair_base_byte_identical=True,
        end_to_end_history_retained=all(
            'EVENTS IN ORDER' in case['requests']['P_infer']['messages'][1]['content']
            for case in cases))


def summarize(rows, cases, repeats):
    result = v5.summarize(rows, cases, repeats)
    paired = [row for row in rows
              if row['model_B_model_P'].get('regret') is not None
              and row['correct_B_model_P'].get('regret') is not None
              and row.get('B_repair_gain') is not None]
    residuals = [
        row['B_repair_gain'] - (
            row['model_B_model_P']['regret'] -
            row['correct_B_model_P']['regret'])
        for row in paired]
    grouped = defaultdict(list)
    for row in paired:
        grouped[row['structure_id']].append(row)

    def paired_macro(getter):
        values = [sum(getter(row) for row in selected) / len(selected)
                  for selected in grouped.values()]
        return None if not values else sum(values) / len(values)

    paired_model = paired_macro(
        lambda row: row['model_B_model_P']['regret'])
    paired_correct = paired_macro(
        lambda row: row['correct_B_model_P']['regret'])
    paired_repair = paired_macro(lambda row: row['B_repair_gain'])
    result['paired_scoring_identity'] = {
        'rows': len(paired), 'structures': len(grouped),
        'scoring_belief': 'teacher_posterior',
        'reference_value': 'same per-case exact teacher optimum',
        'normalization': 'raw terminal own utility; no normalization',
        'model_B_regret': paired_model,
        'correct_semantic_B_regret': paired_correct,
        'regret_difference': (None if paired_model is None else
                              paired_model-paired_correct),
        'repair_gain': paired_repair,
        'aggregate_identity_residual': (
            None if paired_repair is None else
            paired_repair-(paired_model-paired_correct)),
        'row_identity_failures': sum(abs(value) > 1e-9
                                     for value in residuals),
        'max_abs_row_identity_residual':
            max((abs(value) for value in residuals), default=None),
        'note': (
            'These three means use the identical paired rows and structure '
            'weights. Condition-specific means in structure_level may use '
            'different valid subsets and must not be subtracted.')}
    result['interpretation'] = (
        'B is scored on the native semantic contract. Correct B means the '
        'correct possible_preferences/favored summary, not a complete posterior. '
        'Every retained semantic summary is certified to induce one invariant '
        'exact optimal-action set over all compatible posteriors. Controlled P '
        'receives no behavioral chronology, so correct-B regret isolates action '
        'selection given a sufficient deployed B interface, while B_repair_gain '
        'is a paired intervention on that interface. End-to-end P separately '
        'retains the native history.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True, nargs='+')
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--temperature', type=float, default=0.)
    parser.add_argument('--top-p', type=float, default=1.)
    parser.add_argument('--top-k', type=int, default=-1)
    parser.add_argument('--concurrency-per-endpoint', type=int, default=16)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=float, default=180.)
    parser.add_argument('--checkpoint-hash')
    args = parser.parse_args()
    if (args.repeats < 1 or args.max_tokens < 1 or args.temperature < 0 or
            not 0 < args.top_p <= 1 or args.concurrency_per_endpoint < 1):
        parser.error('Invalid sampling settings')
    manifest, cases = load()
    audit = audit_cases(cases)
    args.output.mkdir(parents=True, exist_ok=False)
    config = dict(
        model=args.model, base_url=args.base_url, repeats=args.repeats,
        temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
        repetition_penalty=1., max_tokens=args.max_tokens, seed=args.seed,
        retry=0, timeout=args.timeout,
        concurrency_per_endpoint=args.concurrency_per_endpoint,
        independent_contexts=True, controlled_P_history_free=True,
        checkpoint_hash=args.checkpoint_hash,
        manifest_sha256=sha(HERE / 'manifest.json'),
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
        endpoint = int(hashlib.sha256(
            f'{case["id"]}:{replica}'.encode()).hexdigest()[:8], 16) % len(args.base_url)

        def call(condition, request):
            seed_condition = ('semantic_controlled_P' if condition in
                              ('correct_B_model_P', 'model_B_model_P')
                              else condition)
            call_seed = int(hashlib.sha256(
                f'{args.seed}:{case["id"]}:{replica}:{seed_condition}'.encode()
                ).hexdigest()[:8], 16)
            body = dict(
                request, model=args.model, temperature=args.temperature,
                top_p=args.top_p, top_k=args.top_k, repetition_penalty=1.,
                max_tokens=args.max_tokens, seed=call_seed)
            started = time.monotonic()
            try:
                with locks[endpoint]:
                    req = Request(
                        args.base_url[endpoint].rstrip('/') + '/chat/completions',
                        data=json.dumps(body).encode(), headers=headers,
                        method='POST')
                    with urlopen(req, timeout=args.timeout) as response:
                        payload = json.load(response)
                choice = payload['choices'][0]
                completion = dict(raw_message=choice['message'],
                                  finish_reason=choice['finish_reason'])
                usage = payload.get('usage')
            except Exception as exc:
                completion = dict(
                    status='infrastructure_failure',
                    error_type=type(exc).__name__,
                    http_status=getattr(exc, 'code', None))
                usage = None
            record = dict(
                case_id=case['id'], structure_id=case['structure_id'],
                replica=replica, condition=condition, seed=call_seed,
                endpoint_index=endpoint,
                elapsed_seconds=time.monotonic() - started,
                request=body, completion=completion, usage=usage)
            with log_lock:
                with (args.output / 'calls.jsonl').open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
            return completion

        return dict(run_case(case, call), replica=replica)

    rows = []
    with ThreadPoolExecutor(
            max_workers=len(args.base_url) * args.concurrency_per_endpoint) as pool:
        futures = [pool.submit(execute, case, replica)
                   for case, replica in jobs]
        for number, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            rows.sort(key=lambda row: (
                row['structure_id'], row['provenance'], row['replica']))
            (args.output / 'results.json').write_text(
                json.dumps(rows, indent=2) + '\n')
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
