"""Environment-independent MS-guided instructions inside a single action request."""
from copy import deepcopy

VERSION = 'general-ms-guided-action-v4-single-call'

MS_GUIDANCE = """Before choosing your action, briefly assess the other participants'
decision-relevant goals, knowledge, constraints, or intentions using only
the available evidence. Use these judgments to plan and choose your next
legal action. Keep your reasoning brief and follow the original response format."""


def action_request(messages):
    """Leave native system/history intact; extend only the current user message."""
    if not messages or messages[-1]['role'] != 'user' or not isinstance(messages[-1]['content'], str):
        raise ValueError('MS-guided action requires a native request ending in a text user message')
    result = deepcopy(messages)
    result[-1]['content'] += '\n\n' + MS_GUIDANCE
    return result
