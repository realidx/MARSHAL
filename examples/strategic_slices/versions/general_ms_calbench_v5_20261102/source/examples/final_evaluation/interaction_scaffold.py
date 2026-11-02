"""Independent belief/MS then action, continued within each native action request."""
from copy import deepcopy

VERSION = 'general-belief-ms-v5-two-call'

MS_INSTRUCTION = """BELIEF / MS STAGE
Using only the context above, briefly describe the participants' decision-relevant
goals, knowledge, constraints, or intentions. Distinguish known facts from
uncertain inferences. For this stage, output only that mental-state assessment in
concise natural language; do not choose, describe, or execute an action."""

ACTION_INSTRUCTION = """ACTION STAGE
Use your preceding mental-state assessment as a fallible judgment to briefly plan
and choose your next legal action. Follow the original environment rules and
return only the original required action-response format. Do not repeat the MS
assessment or narrate future execution."""


def ms_request(native_messages):
    """Finish the original user prompt, then add a distinct user MS prompt."""
    if not native_messages or native_messages[-1]['role'] != 'user' or not isinstance(native_messages[-1]['content'], str):
        raise ValueError('Belief/MS requires a native request ending in a text user message')
    conversation = deepcopy(native_messages)
    conversation.append(dict(role='user', content=MS_INSTRUCTION))
    return conversation


def action_request(ms_messages, ms_output):
    """The assistant entry is the real first model response, not an instruction."""
    conversation = deepcopy(ms_messages)
    conversation.append(dict(role='assistant', content=ms_output))
    conversation.append(dict(role='user', content=ACTION_INSTRUCTION))
    return conversation
