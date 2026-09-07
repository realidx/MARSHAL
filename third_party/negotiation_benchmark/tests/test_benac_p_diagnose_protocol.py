"""Short reasoning, auto tools, truncation and measured token usage."""
import json
from unittest.mock import patch
import pytest
from methods.vllm_client import VLLMChatCompletion, VLLMToolCall, OpenAICompatibleNegotiationClient
from benac_p.diagnose_protocol import generate, submission_tool, protocol_summary
from benac_p.diagnose_suite import SYSTEM


def task(kind='planning'):
    return {'kind':kind,'input':{'legal_actions':[{},{}], 'initial_probabilities':[.5,.5],'options':[{},{}]}}


class Client:
    def __init__(self,completion):self.completion=completion
    def complete_with_tools(self,messages,**kwargs):
        assert kwargs['tool_choice']=='auto' and kwargs['parallel_tool_calls'] is False
        assert 'response_format' not in kwargs
        assert 'Return only the requested JSON' not in messages[0]['content']
        assert 'three short sentences' in messages[0]['content'] and '100 words' in messages[0]['content']
        return self.completion
    def complete_response(self,messages,**kwargs):
        assert kwargs['response_format']=={'type':'json_object'}
        assert 'Return only the requested JSON object.' in messages[0]['content']
        return self.completion


def completion(content='A concise justification.',calls=None,finish='tool_calls'):
    return VLLMChatCompletion(content,tuple(calls if calls is not None else [VLLMToolCall('SUBMIT_ACTION',{'action_index':1})]),{}, {'completion_tokens':45},finish)


def test_native_reasoning_and_schema():
    r=generate(Client(completion()),task(),{},SYSTEM)
    assert r['status']=='ok' and r['answer']=={'action_index':1}
    assert r['reasoning_present'] and r['reasoning']=='A concise justification.'
    assert r['usage']['completion_tokens']==45 and r['finish_reason']=='tool_calls'
    assert 'reasoning' not in submission_tool(task())['function']['parameters']['properties']
    for kind,name in [('belief','SUBMIT_BELIEF'),('grounding','SUBMIT_UTILITIES')]:
        assert submission_tool(task(kind))['function']['name']==name


@pytest.mark.parametrize('calls', [[],[VLLMToolCall('WRONG',{})],
    [VLLMToolCall('SUBMIT_ACTION',None)], [VLLMToolCall('SUBMIT_ACTION',{'action_index':0,'reason':'extra'})],
    [VLLMToolCall('SUBMIT_ACTION',{'action_index':0})]*2])
def test_bad_calls_are_protocol_failures(calls):
    r=generate(Client(completion(calls=calls)),task(),{},SYSTEM)
    assert r['status']=='invalid' and 'answer' not in r


@pytest.mark.parametrize('calls',[[],[VLLMToolCall('SUBMIT_ACTION',{'action_index':1})]])
def test_truncation_even_with_parseable_call(calls):
    r=generate(Client(completion(calls=calls,finish='length')),task(),{},SYSTEM)
    assert r['status']=='truncated' and 'answer' not in r
    assert r['usage']['completion_tokens']==45


def test_reasoning_soft_length_and_coverage():
    empty=generate(Client(completion(content='')),task(),{},SYSTEM)
    long=generate(Client(completion(content='word '*110)),task(),{},SYSTEM)
    assert empty['status']==long['status']=='ok' and not empty['reasoning_present']
    summary=protocol_summary({'a':empty,'b':long})
    assert summary['reasoning_present_requests']==1 and summary['reasoning_over_100_words']==1
    assert summary['mean_completion_tokens']==summary['p95_completion_tokens']==45


def test_json_control_retains_metadata():
    r=generate(Client(completion(content='{"action_index":0}',calls=[],finish='stop')),task(),{},SYSTEM,'json_action')
    assert r['status']=='ok' and r['answer']=={'action_index':0}
    assert not r['reasoning_present'] and r['finish_reason']=='stop'


def test_http_preserves_stop_reason_and_budget():
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'choices':[{'message':{'content':'brief','tool_calls':[]},'finish_reason':'length'}],'usage':{'completion_tokens':1024}}).encode()
    def urlopen(request,**kwargs):
        body=json.loads(request.data)
        assert body['max_tokens']==1024 and body['tool_choice']=='auto'
        assert 'response_format' not in body
        return Response()
    client=OpenAICompatibleNegotiationClient('http://unused.invalid','mock',max_tokens=1024)
    with patch('urllib.request.urlopen',urlopen):
        r=client.complete_with_tools([{'role':'user','content':'test'}],tools=[submission_tool(task())],tool_choice='auto',parallel_tool_calls=False)
    assert r.finish_reason=='length' and r.usage['completion_tokens']==1024
