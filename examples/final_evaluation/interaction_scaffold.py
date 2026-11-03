"""Environment-independent private belief then action stage protocol."""
from copy import deepcopy

VERSION = 'general-ms-v14-inline-brief'

MS_CORE = 'Before your next action, briefly articulate your own mental states and\nyour beliefs about the mental states of other participants.\n\nWrite from your own perspective: what you believe, want, know, or intend,\nand what you think others believe, want, know, or intend. Include emotions\nonly when relevant to the interaction.\n\nGround these judgments in the available context and history, without\ninventing hidden facts. Write one brief paragraph that can guide your\nnext decision.\n\n'

MS_INSTRUCTION = MS_CORE+"Output only one brief natural-language paragraph about mental states. Nothing written in this stage is executed or delivered to anyone."

ACTION_INSTRUCTION = """ACTION STAGE
Use the context and your preceding assessment to choose your next action.
"""


INLINE_MS_INSTRUCTION = 'Before making a decision, briefly reason about what you want, know,\nand intend to do, and what you think others want, know, and are likely\nto do. Then consider what you should do to achieve your goals.\nGround these judgments in the available context and history, without\ninventing hidden facts.\n\nIn the existing JSON response, use the "thinking" string for this reasoning, then provide the action list in "actions".'


def inline_request(native_messages):
    conversation = deepcopy(native_messages)
    conversation[-1]['content'] += '\n\n'+INLINE_MS_INSTRUCTION
    return conversation


def ms_request(context_messages):
    if not context_messages or context_messages[-1]['role'] != 'user' or not isinstance(context_messages[-1]['content'], str):
        raise ValueError('Belief/MS requires a context ending in a text user message')
    conversation = deepcopy(context_messages)
    conversation.append(dict(role='user', content=MS_INSTRUCTION))
    return conversation


def action_request(ms_messages, ms_output, action_instructions=''):
    conversation = deepcopy(ms_messages)
    conversation.append(dict(role='assistant', content=ms_output))
    conversation.append(dict(role='user', content=ACTION_INSTRUCTION+'\n'+action_instructions))
    return conversation
