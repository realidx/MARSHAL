"""Environment-independent private belief then action stage protocol."""
from copy import deepcopy
import json
import re

VERSION = 'general-belief-ms-v11-minimal'

MS_CORE = 'Before your next action, briefly articulate your own mental states and\nyour beliefs about the mental states of other participants.\n\nWrite from your own perspective: what you believe, want, know, or intend,\nand what you think others believe, want, know, or intend. Include emotions\nonly when relevant to the interaction.\n\nGround these judgments in the available context and history, without\ninventing hidden facts. Write one brief paragraph that can guide your\nnext decision.\n\n'

MS_INSTRUCTION = MS_CORE+"Output only one brief natural-language paragraph about mental states. Nothing written in this stage is executed or delivered to anyone."

ACTION_INSTRUCTION = """ACTION STAGE
Use the context and your preceding assessment to choose your next action.
"""


def validate_belief_text(text):
    """Reject executable/structured output, never silently strip it into belief."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Belief must be non-empty natural language')
    if '```' in text or re.search(r'<\s*(?:tool_call|function_call)\b', text, re.I):
        raise ValueError('Belief must not contain code or tool calls')
    if re.search(r'(?im)^\s*(?:action(?:s)?|tool call(?:s)?)\s*:', text):
        raise ValueError('Belief must not contain action directives')
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char not in '{[':
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except ValueError:
            # Malformed action JSON must not evade the structured-output guard.
            if re.search(r'["\'](?:actions|tool_calls|function_call|type)["\']\s*:', text[i:]):
                raise ValueError('Belief must not contain action objects')
            continue
        if isinstance(value, (dict, list)):
            raise ValueError('Belief must be a natural-language paragraph, not JSON')
    if re.search(r'(?m)^\s*[A-Za-z_]\w*(?:\.\w+)*\s*\([^\n]*\)\s*;?\s*$', text):
        raise ValueError('Belief must not contain executable call syntax')


def ms_request(context_messages):
    if not context_messages or context_messages[-1]['role'] != 'user' or not isinstance(context_messages[-1]['content'], str):
        raise ValueError('Belief/MS requires a context ending in a text user message')
    conversation = deepcopy(context_messages)
    conversation.append(dict(role='user', content=MS_INSTRUCTION))
    return conversation


def action_request(ms_messages, ms_output, action_instructions=''):
    validate_belief_text(ms_output)
    conversation = deepcopy(ms_messages)
    conversation.append(dict(role='assistant', content=ms_output))
    conversation.append(dict(role='user', content=ACTION_INSTRUCTION+'\n'+action_instructions))
    return conversation
