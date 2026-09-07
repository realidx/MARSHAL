"""Response protocols for the same frozen diagnostic questions and scoring."""
import json
from collections import Counter
from collections.abc import Mapping
import numpy as np

PROTOCOL_VERSION = 'brief-reasoning-tools-v1'
BRIEF_REASONING = (
    'Give brief free-form reasoning in at most three short sentences, aiming for under 100 words. '
    'Do not restate the problem. Then submit your answer with exactly one of the supplied tool calls. '
    'Do not write anything after the tool call. Keep the reasoning in ordinary text, not in tool arguments.'
)


def system_prompt(base, protocol):
    # Remove the old whole-response JSON instruction in both imported rules and
    # suite suffix; it conflicts with an ordinary-text reasoning prefix.
    base = base.replace('Return only the requested JSON object.', '').replace('Return only the requested JSON.', '')
    return base.strip() + '\n' + (BRIEF_REASONING if protocol == 'reasoning_tools' else 'Return only the requested JSON object.')


def submission_tool(task):
    kind = task['kind']
    if kind == 'planning':
        name, key = 'SUBMIT_ACTION', 'action_index'
        value = {'type': 'integer', 'minimum': 0, 'maximum': len(task['input']['legal_actions'])-1}
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


def generate(client, task, payload, base_system, protocol='reasoning_tools'):
    messages = [{'role': 'system', 'content': system_prompt(base_system, protocol)},
                {'role': 'user', 'content': json.dumps(payload)}]
    tool = submission_tool(task)
    if protocol == 'reasoning_tools':
        completion = client.complete_with_tools(messages, tools=[tool], tool_choice='auto', parallel_tool_calls=False)
    elif protocol == 'json_action':
        completion = client.complete_response(messages, response_format={'type': 'json_object'})
    else:
        raise ValueError('Unknown response protocol.')
    content = completion.content
    calls = [{'name': c.name, 'arguments': c.arguments, 'raw_arguments': c.raw_arguments} for c in completion.tool_calls]
    record = dict(raw=content, raw_message=dict(completion.raw_message), tool_calls=calls,
                  usage=dict(completion.usage), finish_reason=completion.finish_reason,
                  response_protocol=protocol, reasoning=content if protocol == 'reasoning_tools' else '',
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


def protocol_summary(records):
    """Descriptive measurement quality, separate from strategic scores."""
    rows = list(records.values())
    attempted = [r for r in rows if 'finish_reason' in r]
    tokens = [r['usage']['completion_tokens'] for r in attempted
              if isinstance(r.get('usage', {}).get('completion_tokens'), (int, float))]
    reasoning_rows = [r for r in attempted if r.get('response_protocol') == 'reasoning_tools']
    return dict(status_counts=dict(Counter(r['status'] for r in rows)),
                finish_reason_counts=dict(Counter(str(r['finish_reason']) for r in attempted)),
                completed_requests=len(attempted), token_usage_observations=len(tokens),
                mean_completion_tokens=float(np.mean(tokens)) if tokens else None,
                p95_completion_tokens=float(np.percentile(tokens, 95)) if tokens else None,
                truncated_requests=sum(r['status'] == 'truncated' for r in rows),
                reasoning_requests=len(reasoning_rows),
                reasoning_present_requests=sum(r.get('reasoning_present', False) for r in reasoning_rows),
                reasoning_over_100_words=sum(r.get('reasoning_word_count', 0) > 100 for r in reasoning_rows),
                note='Word counts are whitespace-based, not token counts. Reasoning length is a soft constraint; max_tokens caps reasoning plus tool output. No-reasoning valid calls remain scored.')
