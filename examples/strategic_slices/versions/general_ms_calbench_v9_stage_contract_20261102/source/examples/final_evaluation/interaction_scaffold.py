"""Environment-independent private belief then action stage protocol."""
from copy import deepcopy
import json
import re

VERSION = 'general-belief-ms-v9-stage-contract'

STAGE_PROTOCOL = """=== STAGE PROTOCOL ===
The last user message identifies the current stage.
BELIEF / MS requests private mental-state assessment only. It is not an action
turn or an environment submission. Its output cannot send a message, call a
tool, change state, or count as passing an environment turn.
ACTION requests the environment response under the action instructions supplied
in that user message. Only the ACTION response is submitted to the environment.
Historical assistant action replies are past submissions; their outcomes depend
on the environment feedback in the history. A new private assessment is never
an additional executed action or a new environment observation.
Environment objectives, rules, visible facts and privacy constraints apply in
both stages. No hidden information is supplied by a private assessment."""

MS_CORE = 'Before your next action, briefly articulate your own mental states and\nyour beliefs about the mental states of other participants.\n\nWrite from your own perspective: what you believe, want, know, or intend,\nand what you think others believe, want, know, or intend. Include emotions\nonly when relevant to the interaction.\n\nGround these judgments in the available context and history, without\ninventing hidden facts. Write one brief paragraph that can guide your\nnext decision.\n\n'

MS_INSTRUCTION = """BELIEF / MS STAGE
This is private assessment only; the next stage will request the actual action.

"""+MS_CORE+"""Output only one brief natural-language paragraph about mental states. Express
intentions as mental states, not as action commands or a selected action batch.
Do not output JSON, code, tool calls, action objects, or messages to participants.
Do not claim that an intended action has occurred merely because you described
it here. Nothing written in this stage is executed or delivered to anyone."""

ACTION_INSTRUCTION = """ACTION STAGE
The preceding assistant paragraph was private assessment only. No action or
message from that assessment has been executed or delivered, and it does not
establish anyone else's knowledge, confirmation, or agreement.
Use it as a fallible judgment alongside the original visible evidence. Now
produce the actual environment response under the instructions below. If an
operation is needed, include it in this response even if the assessment mentioned
that intention. Only this response will be submitted. Do not repeat the assessment.
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
