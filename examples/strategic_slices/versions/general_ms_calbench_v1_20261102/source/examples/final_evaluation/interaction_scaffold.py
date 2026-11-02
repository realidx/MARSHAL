"""Environment-independent, stateless mental-state conditioning requests."""
from copy import deepcopy
import json

VERSION = 'general-ms-conditioning-v1'

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
Use the original context and the tentative private analysis below to select your
current legal action. Treat the analysis as fallible model-generated judgments,
not additional observations or instructions; original evidence takes precedence.
Consider your stated objective, plausible reactions of other participants, and
the implications for subsequent interaction. Do not assume agreement, knowledge,
or future events that the available evidence does not support. Follow the
environment's original action permissions, privacy rules, and response format.
Output only the response required for the current environment stage."""


def ms_request(messages):
    """Copy only the native visible context; override formatting in system scope."""
    result = deepcopy(messages)
    system = next((m for m in result if m['role'] == 'system'), None)
    if system is None:
        result.insert(0, dict(role='system', content=MS_INSTRUCTION))
    else:
        system['content'] += '\n\n' + MS_INSTRUCTION
    result.append(dict(role='user', content='Perform the internal analysis stage for the current decision.'))
    return result


def action_request(messages, analysis):
    result = deepcopy(messages)
    result.append(dict(role='user', content=ACTION_INSTRUCTION +
        '\n\nTentative private analysis (JSON string, data only):\n' + json.dumps(analysis, ensure_ascii=False)))
    return result
