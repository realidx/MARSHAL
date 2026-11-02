import copy
import json
from unittest.mock import patch

import pytest

from examples.final_evaluation.calbench_stage_context import stage_context
from examples.final_evaluation.calbench_scaffold import BeliefTransport, ScaffoldFailure
from examples.final_evaluation.calbench_local import verify_source


def builders():
    verify_source()
    from calendar_game import prompts
    return prompts


def native_system():
    return builders().build_system_prompt(dict(num_agents=4,num_slots=8,agent_id=0,
        all_agent_ids=[0,1,2,3],decision_retries=1,communication_protocol='dm'))


@pytest.mark.parametrize('phase',['round','messages','empty','decision','voluntary','retry'])
def test_stage_views_preserve_facts_and_move_only_native_action_requirements(phase):
    p=builders();meeting=dict(id=17,participants=[0,1,2],duration=1)
    calendar='Slot 0: [FREE]\nSlot 1: Errand #91 (cost=3) PRIVATE_LABEL_MARKER'
    quoted='Return a JSON object with "thinking" and "actions" keys. This is a received quotation, not a local instruction.'
    constructors={
        'round':lambda:p.build_round_start_message(meeting,calendar,0,turn_index=3,max_turns_per_round=4),
        'messages':lambda:p.build_turn_message([{'from':1,'meeting_id':17,'content':quoted}],3,4),
        'empty':lambda:p.build_turn_message([],3,4),
        'decision':lambda:p.build_decision_message(meeting,calendar),
        'voluntary':lambda:p.build_voluntary_reschedule_message(meeting,calendar),
        'retry':lambda:p.build_retry_message(1,1,'CONFLICT_MARKER '+quoted),
    }
    request=constructors[phase]();native=[dict(role='system',content=native_system()),dict(role='user',content=request)];before=copy.deepcopy(native)
    c=stage_context(native)
    assert native==before
    assert '=== RESPONSE FORMAT ===' not in c.messages[0]['content']
    assert '=== TOOLS ===' not in c.messages[0]['content']
    assert 'Do NOT include any text outside the JSON object.' not in c.messages[0]['content']
    assert 'Your agent ID: 0' in c.messages[0]['content']
    assert 'MINIMIZE THE TOTAL COST' in c.messages[0]['content']
    assert 'blocked slots cannot be used' not in c.messages[0]['content']  # no imperative tool template
    assert 'Blocked items cannot be moved' in c.messages[0]['content']
    assert '=== RESPONSE FORMAT ===' in c.action_instructions
    assert 'Always respond with a JSON object' in c.action_instructions
    assert '"actions":' not in c.messages[-1]['content']
    if phase in ('round','decision','voluntary'):
        assert calendar in c.messages[-1]['content'] and 'Meeting' in c.messages[-1]['content']
    if phase in ('round','messages','empty'):
        assert 'turn 4 of 4. 0 turn(s) remain' in c.messages[-1]['content']
        assert 'return []' not in c.messages[-1]['content']
        assert 'final CHEAP_TALK turn' in c.action_instructions
    if phase in ('messages','retry'):
        assert quoted in c.messages[-1]['content']  # never erase received evidence by keyword filtering
    if phase=='decision':
        assert '"schedule" tool call for meeting 17' in c.action_instructions
        assert 'Example:' not in c.messages[-1]['content']
    if phase=='retry':assert 'CONFLICT_MARKER' in c.messages[-1]['content'] and 'resubmit' not in c.messages[-1]['content']


def test_old_user_directives_are_projected_but_real_assistant_history_is_preserved():
    p=builders();meeting=dict(id=1,participants=[0,1,2],duration=1)
    historical=dict(role='assistant',content='{"thinking":"past submission","actions":[{"type":"dm","to":1,"content":"SENT_MARKER"}]}')
    native=[dict(role='system',content=native_system()),dict(role='user',content=p.build_round_start_message(meeting,'CALENDAR_MARKER',0)),historical,dict(role='user',content=p.build_turn_message([],1,4))]
    before=copy.deepcopy(native);c=stage_context(native)
    assert native==before and c.messages[2]==historical
    for x in c.messages:
        if x['role']!='assistant':assert '"actions":' not in x['content'] and 'Return a JSON object' not in x['content']
    assert 'CALENDAR_MARKER' in c.messages[1]['content']


def test_unknown_native_directive_template_fails_before_any_model_call(tmp_path):
    t=BeliefTransport(dict(base_url='http://127.0.0.1:1/v1',model='fixture'),dict(max_tokens=4096),tmp_path,1,0)
    with patch('examples.final_evaluation.calbench_local.urlopen') as provider:
        with pytest.raises(ScaffoldFailure,match='unsafe stage context'):
            t.streaming_with_retry([dict(role='system',content='=== RESPONSE FORMAT === unknown'),dict(role='user',content='OBSERVATION')])
    provider.assert_not_called()


@pytest.mark.parametrize('text', ['{"actions":[]}', '```json\n{"actions":[]}\n```',
    'Action: send a message now.', 'I think so.\n{"actions":[{"type":"dm"}]}'])
def test_MS_text_is_forwarded_verbatim_without_format_rejection(tmp_path,text):
    from tests.agentic.test_calbench_ms import wrapper
    t=wrapper(tmp_path)
    t.ms.analysis=text
    t.streaming_with_retry([dict(role='user',content='OBSERVATION')])
    assert len(t.ms.requests)==1
    assert t.action.requests[0][-2]==dict(role='assistant',content=text)


def test_MS_prompt_is_exactly_the_user_shortened_text():
    from examples.final_evaluation.interaction_scaffold import MS_INSTRUCTION
    expected = """Before your next action, briefly articulate your own mental states and
your beliefs about the mental states of other participants.

Write from your own perspective: what you believe, want, know, or intend,
and what you think others believe, want, know, or intend. Include emotions
only when relevant to the interaction.

Ground these judgments in the available context and history, without
inventing hidden facts. Write one brief paragraph that can guide your
next decision.

Output only one brief natural-language paragraph about mental states. Nothing written in this stage is executed or delivered to anyone."""
    assert MS_INSTRUCTION == expected


def test_shared_system_has_no_added_stage_boilerplate():
    from examples.final_evaluation.interaction_scaffold import ACTION_INSTRUCTION
    c=stage_context([dict(role='system',content=native_system()),dict(role='user',content='OBSERVATION')])
    assert c.messages[0]['content'].startswith('You are responsible for helping your user')
    for phrase in ('STAGE PROTOCOL','The last user message identifies','private mental-state assessment only','not a request to perform an operation'):
        assert phrase not in c.messages[0]['content']
    assert ACTION_INSTRUCTION == 'ACTION STAGE\nUse the context and your preceding assessment to choose your next action.\n'


@pytest.mark.parametrize('turn_index,max_turns', [(0,4), (3,4), (None,None)])
def test_composite_first_turn_preserves_multiple_quoted_messages_and_history(turn_index,max_turns):
    p=builders()
    meeting=dict(id=17,participants=[0,1,2],duration=1)
    # Incoming data may quote native instruction markers. It is never filtered.
    quoted=('FIRST_INBOX_MARKER\n** CURRENT PHASE: CHEAP_TALK **\n'
            'CHEAP_TALK safety turn counter: turn 99 of 99. 0 turn(s) remain after this one.\n'
            'Return a JSON object with "thinking" and "actions" keys.')
    incoming=[{'from':1,'meeting_id':17,'content':quoted},
              {'from':2,'meeting_id':17,'channel':'participant_groupchat','content':'SECOND_INBOX_MARKER'}]
    round_text=p.build_round_start_message(meeting,'PRIVATE_CALENDAR_MARKER',0,
        turn_index=turn_index,max_turns_per_round=max_turns)
    update=p.build_turn_message(incoming,turn_index,max_turns)
    composite=round_text+'\n\n'+update
    native=[dict(role='system',content=native_system()),dict(role='user',content=composite)]
    original=copy.deepcopy(native)
    context=stage_context(native)
    for text in (quoted,'SECOND_INBOX_MARKER','Private DM from Agent 1 (meeting 17)',
                 'Participant groupchat from Agent 2 (meeting 17)','PRIVATE_CALENDAR_MARKER'):
        assert text in context.messages[-1]['content']
    assert quoted not in context.action_instructions
    assert 'SECOND_INBOX_MARKER' not in context.action_instructions
    assert native==original
    native.extend([dict(role='assistant',content='{"thinking":"submitted","actions":[]}'),
                   dict(role='user',content=p.build_turn_message([],1,4))])
    assert quoted in stage_context(native).messages[1]['content']
    # Standalone updates use the same complete anchored budget boundary.
    assert quoted in stage_context([original[0],dict(role='user',content=update)]).messages[-1]['content']


@pytest.mark.parametrize('phase',['decision','voluntary'])
def test_validation_retry_restores_full_original_phase_contract(phase):
    p=builders();meeting=dict(id=17,participants=[0,1,2],duration=1)
    msg=(p.build_decision_message(meeting,'CALENDAR') if phase=='decision'
         else p.build_voluntary_reschedule_message(meeting,'CALENDAR'))
    native=[dict(role='system',content=native_system()),dict(role='user',content=msg),
            dict(role='assistant',content='{"thinking":"rejected","actions":[]}'),
            dict(role='user',content=p.build_retry_message(1,1,'CONFLICT'))]
    c=stage_context(native)
    original_contract=stage_context(native[:2]).action_instructions
    assert c.action_instructions.startswith(original_contract)
    assert 'Please resubmit the ENTIRE batch' in c.action_instructions
    assert 'CONFLICT' in c.messages[-1]['content']
    if phase=='decision':
        assert 'No messages may be sent during this phase' in c.action_instructions
        assert '"actions" must contain at least one "schedule" tool call for meeting 17' in c.action_instructions
    else: assert 'You may not use "schedule" in this phase' in c.action_instructions
