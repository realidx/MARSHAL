"""Separate pinned CalBench observations/rules from current action instructions.

This adapter changes prompt presentation, not the native client/history or game.
Unknown instruction-bearing templates fail closed rather than silently dropping
observations. Received messages and calendar labels are never regex-filtered.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

# Descriptive action constraints, without executable schemas or output examples.
# Original schemas, phase directives and response format are restored for ACTION.
OPERATION_RULES = """=== ENVIRONMENT OPERATION RULES ===
CHEAP_TALK permits communication through the configured native channel(s). A
private direct message has one recipient; multiple messages can be submitted in
a communication turn. Calendar edits are not permitted during CHEAP_TALK. The
communication phase ends when no further communication actions are submitted.
VOLUNTARY permits a non-participant who received coordination messages to move
existing items on their own calendar to honor commitments; it does not permit
placing the current meeting.
DECISION permits placing the requested meeting and moving existing items on the
player's own calendar. A decision batch includes a placement for that meeting.
The target must be free after the batch's moves. Blocked items cannot be moved
or used for meetings. Existing errands and meetings have their native item IDs;
moves require a non-empty justification grounded in the coordination context.
A batch is atomic and its order does not change the result. Other participants
submit independently. RESOLUTION checks their submitted placements; it is passive."""

COUNTER = re.compile(r'CHEAP_TALK safety turn counter: turn \d+ of \d+\. \d+ turn\(s\) remain after this one\.')
TURN_TAIL = re.compile(
    r'Only the [^\n]+ tool\(s\) are valid right now\. CHEAP_TALK phase is still active\. '
    r'Return a JSON object with "thinking" and "actions" keys\. Use \[\] for actions to pass\.$')
ROUND_END = 'Return a JSON object with "thinking" and "actions" keys. "actions" should be a list of communication tool calls, or [] to pass.\n'
BUDGET_END = re.compile(
    r'\n(?P<counter>CHEAP_TALK safety turn counter: turn \d+ of \d+\. \d+ turn\(s\) remain after this one\.) '
    r'If all necessary coordination is complete, return \[\] to end cheap-talk\.'
    r'(?:\nThis is the final CHEAP_TALK turn before DECISION\. Do not ask open-ended '
    r'questions; state your final proposed slot or return \[\] if coordination is complete\.)?\n$')


FORMAT_REMINDER = 'Do NOT include any text outside the JSON object.'


@dataclass
class StageContext:
    messages: list
    action_instructions: str
    transformations: list


def _phase(name):
    details = {
        'CHEAP_TALK': 'Only communication is permitted in this environment phase; calendar edits are not permitted.',
        'DECISION': 'Communication is closed and no new messages are available. The next environment submission is a decision batch.',
        'VOLUNTARY': 'This player is not a participant in the current meeting. Only moves of existing own items are permitted.',
    }
    return f'\n\nCURRENT ENVIRONMENT PHASE: {name}\n{details[name]}'


def _counter(text):
    found = COUNTER.search(text)
    return '\n'+found.group(0) if found else ''


def _system(text):
    if '=== TOOLS ===' not in text:
        if '=== RESPONSE FORMAT ===' in text or FORMAT_REMINDER in text:
            raise ValueError('Unrecognized instruction-bearing system template')
        return text, ''
    before, rest = text.split('=== TOOLS ===', 1)
    if '=== IDENTITY ===' not in rest or '=== RESPONSE FORMAT ===' not in rest:
        raise ValueError('Pinned CalBench system sections changed')
    action, tail = rest.split('=== IDENTITY ===', 1)
    tail = '=== IDENTITY ==='+tail
    if not tail.rstrip().endswith(FORMAT_REMINDER):
        raise ValueError('Pinned CalBench final format reminder changed')
    tail = tail.rstrip()[:-len(FORMAT_REMINDER)].rstrip()
    common = before+OPERATION_RULES+'\n\n'+tail
    return common, '=== TOOLS ==='+action


def _turn_parts(text):
    match = TURN_TAIL.search(text)
    if match is None:
        raise ValueError('Pinned communication trailer changed')
    prefix = text[:match.start()]
    budget = BUDGET_END.search(prefix)
    cut = budget.start() if budget else match.start()
    counter = '\n'+budget.group('counter') if budget else ''
    return text[:cut], counter, text[cut:]


def _user(text):
    if re.match(r'^=== ROUND \d+ START ===', text):
        # Native first turn appends a full inbox update AFTER the round footer.
        # Bound the round template before splitting phase directives, so received
        # quotations (including template-like strings) remain ordinary data.
        round_text, footer, appended = text.partition(ROUND_END)
        if not footer:
            raise ValueError('Pinned round-start format footer missing')
        marker = '** CURRENT PHASE: CHEAP_TALK **'
        if marker not in round_text:
            raise ValueError('Pinned round-start phase marker missing')
        observation, directives = round_text.rsplit(marker, 1)
        counter = _counter(directives)
        actions = marker+directives+footer
        if appended:
            if not appended.startswith('\n\nNew messages received:\n'):
                raise ValueError('Pinned first-turn inbox composition changed')
            inbox, counter, turn_actions = _turn_parts(appended[2:])
            observation += '\n\n'+inbox
            actions += '\n\n'+turn_actions
        return observation+_phase('CHEAP_TALK')+counter, actions
    if text.startswith(('New messages received:', 'No new messages in your inbox.')):
        observation, counter, directives = _turn_parts(text)
        return observation+_phase('CHEAP_TALK')+counter, directives
    if text.startswith('=== DECISION PHASE ==='):
        marker = '** MEETING TO SCHEDULE **'
        if marker not in text or '** INSTRUCTIONS **' not in text:
            raise ValueError('Pinned decision sections changed')
        intro, rest = text.split(marker, 1)
        observation, directives = rest.rsplit('** INSTRUCTIONS **', 1)
        return '=== DECISION PHASE ===\n\n'+marker+observation+_phase('DECISION'), intro+'** INSTRUCTIONS **'+directives
    if text.startswith('=== VOLUNTARY RESCHEDULE PHASE ==='):
        marker = 'If you made any commitments to free up a slot or move items on your calendar, do so now'
        if marker not in text or '** YOUR CALENDAR **' not in text:
            raise ValueError('Pinned voluntary sections changed')
        observation, rest = text.split(marker, 1)
        directives, calendar = rest.rsplit('** YOUR CALENDAR **', 1)
        calendar, formatting = calendar.rsplit('Return a JSON object with "thinking" and "actions" keys.', 1)
        return observation+'** YOUR CALENDAR **'+calendar+_phase('VOLUNTARY'), marker+directives+'Return a JSON object with "thinking" and "actions" keys.'+formatting
    if text.startswith('[RETRY '):
        marker = '\n\nPlease resubmit the ENTIRE batch from scratch, correcting the issue above.'
        if marker not in text:
            raise ValueError('Pinned validation-retry trailer changed')
        observation, directives = text.rsplit(marker, 1)
        return observation, marker+directives
    # Plain observations are usable by transport fixtures and other callers.
    # Unexpected native instructions must not silently enter the belief request.
    if any(x in text for x in ('Return a JSON object', '=== RESPONSE FORMAT ===', FORMAT_REMINDER)):
        raise ValueError('Unrecognized instruction-bearing user template')
    return text, ''


def stage_context(native_messages):
    if not native_messages or native_messages[-1].get('role') != 'user':
        raise ValueError('Stage context requires a native request ending in user')
    messages = deepcopy(native_messages)
    transformations = []
    system_actions = ''
    current_actions = ''
    for i, message in enumerate(messages):
        if not isinstance(message.get('content'), str):
            raise ValueError('Expected text-only pinned CalBench context')
        original = message['content']
        if message['role'] == 'system':
            message['content'], system_actions = _system(original)
        elif message['role'] == 'user':
            message['content'], directives = _user(original)
            if i == len(messages)-1:
                current_actions = directives
        elif message['role'] != 'assistant':
            raise ValueError('Unexpected native message role')
        if message['content'] != original:
            transformations.append(dict(index=i, role=message['role'], original=original,
                                        observation_view=message['content']))
    action = '\n\n'.join(x for x in (system_actions, current_actions) if x)
    return StageContext(messages, action, transformations)
