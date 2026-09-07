"""Response protocols for the same frozen diagnostic questions and scoring."""
import json
from collections import Counter
from collections.abc import Mapping
import numpy as np

PROTOCOL_VERSION = 'brief-reasoning-tools-v2'
BRIEF_REASONING = (
    'Briefly reason about the task before submitting your answer. '
    'Do not restate the problem. Then submit your answer with exactly one of the supplied tool calls. '
    'Do not write anything after the tool call. Keep the reasoning in ordinary text, not in tool arguments.'
)
REASONING_PROFILE_VERSION = 'reasoning-budgets-v1'
REASONING_PROFILES = ('open', 'compact', 'balanced')


def reasoning_instruction(profile):
    if profile not in REASONING_PROFILES:
        raise ValueError('Unknown reasoning profile.')
    if profile == 'open':
        return BRIEF_REASONING  # Exact historical v2 baseline, for matched comparisons.
    target = (
        'Aim for about 80 words or fewer before the tool call. '
        if profile == 'compact' else
        'For a partner-judgment question, aim for about 120 words or fewer; '
        'for an action-selection question, aim for about 240 words or fewer. '
    )
    return (BRIEF_REASONING + target +
            'These are brevity targets, not a required length: finish sooner when possible. '
            'Do not repeat a comparison or restart an analysis after reaching a conclusion. '
            'If several actions are equally best, choose one and submit; do not keep searching for a unique winner. '
            'For a judgment, retain every supported possibility rather than forcing a unique answer.')


def system_prompt(base, protocol, reasoning_profile='open'):
    # Remove the old whole-response JSON instruction in both imported rules and
    # suite suffix; it conflicts with an ordinary-text reasoning prefix.
    base = base.replace('Return only the requested JSON object.', '').replace('Return only the requested JSON.', '')
    return base.strip() + '\n' + (reasoning_instruction(reasoning_profile) if protocol == 'reasoning_tools' else 'Return only the requested JSON object.')


def submission_tool(task):
    kind = task['kind']
    if kind == 'planning':
        name, key = 'SUBMIT_ACTION', 'action_index'
        value = {'type': 'integer', 'minimum': 0, 'maximum': len(task['input']['legal_actions'])-1}
    elif kind == 'semantic_belief':
        name, key = 'SUBMIT_JUDGMENT', 'possible_preferences'
        value = {'type': 'array', 'minItems': 1, 'maxItems': 3, 'uniqueItems': True,
                 'items': {'type': 'string', 'enum': ['want', 'neutral', 'avoid']}}
    else:
        if kind == 'belief':
            name, key = 'SUBMIT_BELIEF', 'probabilities'
            size = len(task['input']['initial_probabilities'])
            items = {'type': 'number', 'minimum': 0, 'maximum': 1}
        else:
            name, key = 'SUBMIT_UTILITIES', 'utilities'
            size = len(task['input']['options'])
            items = {'type': 'number'}
        value = {'type': 'array', 'items': items, 'minItems': size, 'maxItems': size}
    return {'type': 'function', 'function': {
        'name': name, 'description': 'Submit the final answer to this diagnostic question.',
        'strict': True, 'parameters': {'type': 'object', 'properties': {key: value},
                                     'required': [key], 'additionalProperties': False}}}


def generate(client, task, payload, base_system, protocol='reasoning_tools', reasoning_profile='open', finalization_tokens=0):
    if finalization_tokens < 0 or (finalization_tokens and protocol != 'reasoning_tools'):
        raise ValueError('Finalization requires a nonnegative budget and reasoning_tools.')
    messages = [{'role': 'system', 'content': system_prompt(base_system, protocol, reasoning_profile)},
                {'role': 'user', 'content': json.dumps(payload)}]
    tool = submission_tool(task)
    if protocol == 'reasoning_tools':
        completion = client.complete_with_tools(messages, tools=[tool], tool_choice='auto', parallel_tool_calls=False)
    elif protocol == 'json_action':
        completion = client.complete_response(messages, response_format={'type': 'json_object'})
    else:
        raise ValueError('Unknown response protocol.')
    record = parse_completion(completion, tool, protocol, reasoning_profile)
    if finalization_tokens and protocol == 'reasoning_tools' and record['status'] == 'truncated':
        return finalize(client, task, payload, base_system, record, finalization_tokens)
    return record


def parse_completion(completion, tool, protocol, reasoning_profile):
    content = completion.content
    calls = [{'name': c.name, 'arguments': c.arguments, 'raw_arguments': c.raw_arguments} for c in completion.tool_calls]
    record = dict(raw=content, raw_message=dict(completion.raw_message), tool_calls=calls,
                  usage=dict(completion.usage), finish_reason=completion.finish_reason,
                  response_protocol=protocol, reasoning=content if protocol == 'reasoning_tools' else '',
                  reasoning_profile=reasoning_profile,
                  reasoning_present=bool(content.strip()) if protocol == 'reasoning_tools' else False,
                  reasoning_word_count=len(content.split()) if protocol == 'reasoning_tools' else 0)
    # Even if a call happens to parse, a length-stopped completion is not a
    # normal completed decision. Never treat missing calls as strategic PASS.
    if completion.finish_reason == 'length':
        return dict(record, status='truncated', error='Output token limit reached.')
    try:
        if protocol == 'reasoning_tools':
            if len(calls) != 1:
                raise ValueError(f'Expected exactly one tool call; received {len(calls)}.')
            if calls[0]['name'] != tool['function']['name']:
                raise ValueError('Unexpected submission tool.')
            answer = calls[0]['arguments']
            if not isinstance(answer, Mapping):
                raise ValueError('Tool arguments are not a JSON object.')
            if set(answer) != set(tool['function']['parameters']['required']):
                raise ValueError('Unexpected or missing tool argument fields.')
        else:
            answer = json.loads(content)
        return dict(record, status='ok', answer=answer)
    except (ValueError, TypeError) as exc:
        return dict(record, status='invalid', error=str(exc))


FINALIZATION_VERSION = 'bounded-submission-v1'
FINALIZATION_INSTRUCTION = (
    'The previous analysis reached its output limit. Submit your best final answer now '
    'using exactly the supplied tool. Do not continue the analysis or add explanatory text.'
)


def finalize(client, task, payload, base_system, first, max_tokens=128):
    """One bounded submission attempt. Never sees labels or repairs reasoning."""
    if max_tokens < 1:
        raise ValueError('Finalization budget must be positive.')
    if first.get('status') != 'truncated' or first.get('response_protocol') != 'reasoning_tools' or 'attempts' in first:
        raise ValueError('Only an unrecovered native-tool truncation can be finalized.')
    profile = first.get('reasoning_profile', 'open')
    tool = submission_tool(task)
    messages = [
        {'role': 'system', 'content': system_prompt(base_system, 'reasoning_tools', profile)},
        {'role': 'user', 'content': json.dumps(payload)},
    ]
    # Carry text only: an incomplete tool call is not a valid conversation turn.
    if first.get('reasoning'):
        messages.append({'role': 'assistant', 'content': first['reasoning']})
    messages.append({'role': 'user', 'content': FINALIZATION_INSTRUCTION})
    try:
        completion = client.complete_with_tools(messages, tools=[tool],
            tool_choice={'type': 'function', 'function': {'name': tool['function']['name']}},
            parallel_tool_calls=False, max_tokens=max_tokens)
        last = parse_completion(completion, tool, 'reasoning_tools', profile)
    except Exception as exc:
        last = dict(status='transport_error', error=type(exc).__name__, usage={})
    usage = {key: sum(r.get('usage', {}).get(key, 0) for r in (first, last))
             for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
             if any(key in r.get('usage', {}) for r in (first, last))}
    result = dict(last, attempts=[first, last], usage=usage,
        finalization_version=FINALIZATION_VERSION, finalization_tokens=max_tokens,
        finalization_attempted=True, first_pass_status=first['status'],
        first_finish_reason=first['finish_reason'],
        reasoning=first.get('reasoning', ''), reasoning_present=first.get('reasoning_present', False),
        reasoning_word_count=first.get('reasoning_word_count', 0), reasoning_profile=profile,
        response_protocol='reasoning_tools')
    # Persist failed submission attempts without rerunning the original question.
    if last['status'] == 'transport_error':
        result.update(status='finalization_error', error=last['error'])
    return result


def protocol_summary(records):
    """Descriptive measurement quality, separate from strategic scores."""
    rows = list(records.values())
    attempts = [a for r in rows for a in r.get('attempts', [r])
                if 'finish_reason' in a or a.get('status') == 'transport_error']
    attempted = [r for r in attempts if 'finish_reason' in r]
    task_tokens = [r['usage']['completion_tokens'] for r in rows if 'completion_tokens' in r.get('usage', {})]
    tokens = [r['usage']['completion_tokens'] for r in attempted
              if isinstance(r.get('usage', {}).get('completion_tokens'), (int, float))]
    first_passes = [r.get('attempts', [r])[0] for r in rows]
    reasoning_rows = [r for r in first_passes if 'finish_reason' in r and r.get('response_protocol') == 'reasoning_tools']
    return dict(total_request_attempts=len(attempts),
                first_pass_truncated_tasks=sum(r.get('first_pass_status', r['status']) == 'truncated' for r in rows),
                finalization_attempted_tasks=sum(r.get('finalization_attempted', False) for r in rows),
                finalization_protocol_successes=sum(r.get('finalization_attempted', False) and r['status'] == 'ok' for r in rows),
                mean_total_completion_tokens_per_task=float(np.mean(task_tokens)) if task_tokens else None,
                total_prompt_tokens=sum(r.get('usage', {}).get('prompt_tokens', 0) for r in rows),
                total_completion_tokens=sum(task_tokens),
                status_counts=dict(Counter(r['status'] for r in rows)),
                finish_reason_counts=dict(Counter(str(r['finish_reason']) for r in attempted)),
                completed_requests=len(attempted), token_usage_observations=len(tokens),
                request_attempts_without_usage=sum(not a.get('usage') for a in attempts),
                mean_completion_tokens=float(np.mean(tokens)) if tokens else None,
                p95_completion_tokens=float(np.percentile(tokens, 95)) if tokens else None,
                truncated_requests=sum(r['status'] == 'truncated' for r in attempted),
                reasoning_requests=len(reasoning_rows),
                reasoning_present_requests=sum(r.get('reasoning_present', False) for r in reasoning_rows),
                mean_reasoning_words=float(np.mean([r.get('reasoning_word_count', 0) for r in reasoning_rows])) if reasoning_rows else None,
                p95_reasoning_words=float(np.percentile([r.get('reasoning_word_count', 0) for r in reasoning_rows],95)) if reasoning_rows else None,
                reasoning_profiles=dict(Counter(r.get('reasoning_profile','open') for r in reasoning_rows)),
                note='Request token means include each completed attempt separately; per-task totals include both attempts. Reasoning statistics describe first passes. Finalization protocol successes still require task-level validation. Word counts are whitespace-based, not token counts. Profile word targets are soft, not validity gates; max_tokens caps reasoning plus tool output. No-reasoning valid calls remain scored.')
