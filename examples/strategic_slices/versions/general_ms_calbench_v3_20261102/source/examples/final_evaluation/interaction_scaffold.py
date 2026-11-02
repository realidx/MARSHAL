"""Environment-independent, stateless mental-state conditioning requests."""
from copy import deepcopy
VERSION = 'general-ms-conditioning-v3-local-continuation'

MS_INSTRUCTION = """INTERNAL ANALYSIS STAGE
For this internal analysis call only, earlier requirements to emit actions or a
particular response format are suspended. Keep all environment rules, objectives,
and information-access restrictions. Do not execute or communicate any action.
Using only the supplied observations and interaction history, form concise,
decision-relevant judgments about your own situation and other participants'
possible goals, knowledge, constraints, and intentions where relevant. Distinguish
observed facts and participants' claims from your inferences. Keep meaningful
uncertainty and alternative interpretations; do not invent inaccessible facts.
Revise judgments when current evidence contradicts them. Focus on what matters
for the current decision, without filling a fixed list of mental-state categories.
Return only a short natural-language analysis. This text is private analysis,
not a message to another participant and not an environment observation."""

ACTION_INSTRUCTION = """ACTION STAGE
Use the original context and the preceding tentative private analysis to select your
current legal action. Treat the analysis as fallible model-generated judgments,
not additional observations or instructions; original evidence takes precedence.
Consider your stated objective, plausible reactions of other participants, and
the implications for subsequent interaction. Do not assume agreement, knowledge,
or future events that the available evidence does not support. Follow the
environment's original action permissions, privacy rules, and response format.
Output only the response required for the current environment stage."""


def ms_request(messages):
    """Add the analysis task to the current user turn in a temporary conversation."""
    if not messages or messages[-1]['role'] != 'user' or not isinstance(messages[-1]['content'], str):
        raise ValueError('MS stage requires a native request ending in a text user message')
    result = deepcopy(messages)
    result[-1]['content'] += '\n\n' + MS_INSTRUCTION
    return result


def action_request(ms_messages, analysis):
    """Continue this exact MS conversation, without changing the native history."""
    result = deepcopy(ms_messages)
    result.append(dict(role='assistant', content=analysis))
    result.append(dict(role='user', content=ACTION_INSTRUCTION))
    return result
