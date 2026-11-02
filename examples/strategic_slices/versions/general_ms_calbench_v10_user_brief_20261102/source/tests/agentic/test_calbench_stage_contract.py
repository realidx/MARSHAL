import copy
import json
from unittest.mock import patch

import pytest

from examples.final_evaluation.calbench_stage_context import stage_context
from examples.final_evaluation.interaction_scaffold import validate_belief_text
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


@pytest.mark.parametrize('text',[
    '{"thinking":"belief","actions":[]}',
    'I believe they are uncertain.\n{"actions":[{"type":"dm","to":1,"content":"draft"}]}',
    '{"actions": [{"type": "dm", "content": "unfinished',
    '```json\n{"actions":[]}\n```',
    '<tool_call>{"name":"send"}</tool_call>',
    'Action: send a message now.',
    'send_message(to=1, text="draft")',
    '[]',
])
def test_executable_or_structured_MS_is_rejected(text):
    with pytest.raises(ValueError):validate_belief_text(text)


def test_intentions_are_allowed_as_mental_states_without_executable_output():
    validate_belief_text('I want a feasible agreement. I believe the others have not confirmed their availability, and I intend to learn their constraints.')


def test_unknown_native_directive_template_fails_before_any_model_call(tmp_path):
    t=BeliefTransport(dict(base_url='http://127.0.0.1:1/v1',model='fixture'),dict(max_tokens=4096),tmp_path,1,0)
    with patch('examples.final_evaluation.calbench_local.urlopen') as provider:
        with pytest.raises(ScaffoldFailure,match='unsafe stage context'):
            t.streaming_with_retry([dict(role='system',content='=== RESPONSE FORMAT === unknown'),dict(role='user',content='OBSERVATION')])
    provider.assert_not_called()


def test_invalid_actionful_MS_retries_only_MS_and_is_never_forwarded(tmp_path):
    from examples.final_evaluation.interaction_scaffold import MS_INSTRUCTION
    from examples.final_evaluation.calbench_retry import resources
    seen=[]
    class Response:
        def __init__(self,value):self.value=value
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return json.dumps(self.value).encode()
    def provider(request,**kwargs):
        body=json.loads(request.data);seen.append(body)
        content='{"thinking":"draft","actions":[{"type":"dm","to":1,"content":"BAD_DRAFT"}]}' if len(seen)==1 else ('I believe their availability remains uncertain.' if body['messages'][-1]['content']==MS_INSTRUCTION else '{"thinking":"Ask now","actions":[{"type":"dm","to":1,"content":"ACTUAL_MESSAGE"}]}')
        return Response(dict(choices=[dict(message=dict(content=content),finish_reason='stop')],usage=dict(prompt_tokens=10,completion_tokens=3,total_tokens=13)))
    t=BeliefTransport(dict(base_url='http://127.0.0.1:1/v1',model='fixture'),dict(max_tokens=4096),tmp_path,77,0)
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        result=t.streaming_with_retry([dict(role='system',content=native_system()),dict(role='user',content=builders().build_turn_message([],0,4))])
    assert len(seen)==3 and seen[0]==seen[1]
    assert 'BAD_DRAFT' not in json.dumps(seen[2])
    assert 'No action or' in seen[2]['messages'][-1]['content']
    assert json.loads(result['text'])['actions'][0]['content']=='ACTUAL_MESSAGE'
    assert result['completion_tokens']==9  # all failed+accepted outputs retained
    assert resources(tmp_path)['recovered_prompts']==1


def test_two_actionful_MS_failures_abort_without_any_action_request(tmp_path):
    from examples.final_evaluation.interaction_scaffold import MS_INSTRUCTION
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return json.dumps(dict(choices=[dict(message=dict(content='{"actions":[]}'),finish_reason='stop')],usage=dict(completion_tokens=3))).encode()
    seen=[]
    def provider(request,**kwargs):seen.append(json.loads(request.data));return Response()
    t=BeliefTransport(dict(base_url='http://127.0.0.1:1/v1',model='fixture'),dict(max_tokens=4096),tmp_path,77,0)
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        with pytest.raises(ScaffoldFailure,match='invalid belief output'):
            t.streaming_with_retry([dict(role='user',content='VISIBLE_CONTEXT')])
    assert len(seen)==2 and all(x['messages'][-1]['content']==MS_INSTRUCTION for x in seen)
    assert not list(tmp_path.glob('transport-*.jsonl'))


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
