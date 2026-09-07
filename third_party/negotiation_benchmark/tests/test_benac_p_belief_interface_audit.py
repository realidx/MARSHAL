import json
from copy import deepcopy
from unittest.mock import patch

from benac_p.belief_interface_audit import CLEAR_QUESTION, main, request
from methods.vllm_client import VLLMChatCompletion, VLLMToolCall


def row():
    return dict(id='b0/known/root/belief', category='known_copy',
                task={'kind':'semantic_belief'},
                payload={'question':'original wording','initially_possible_preferences':['avoid'],'history':[]},
                expected={'possible_preferences':['avoid']},
                baseline={'status':'ok','answer':{'possible_preferences':['want','neutral','avoid']},
                          'finish_reason':'tool_calls','reasoning_present':False,
                          'response_protocol':'reasoning_tools','usage':{'completion_tokens':32}})


class Client:
    def __init__(self):self.calls=[]
    def complete_response(self,messages,**kwargs):
        self.calls.append(('text',deepcopy(messages),kwargs))
        assert not kwargs
        return VLLMChatCompletion('The supplied information is sufficient.',(),{}, {'completion_tokens':10},'stop')
    def complete_with_tools(self,messages,**kwargs):
        self.calls.append(('tool',deepcopy(messages),kwargs))
        return VLLMChatCompletion('',(VLLMToolCall('SUBMIT_JUDGMENT',{'possible_preferences':['want','neutral','avoid']}),),{}, {'completion_tokens':32},'tool_calls')


def test_wording_only_changes_question_and_never_supplies_labels():
    r=row();old=deepcopy(r);c=Client()
    result=request(c,r,'clear_auto')
    payload=json.loads(c.calls[0][1][1]['content'])
    assert payload==dict(r['payload'],question=CLEAR_QUESTION)
    assert c.calls[0][2]['tool_choice']=='auto'
    assert 'expected' not in payload and result['answer']!=r['expected']
    assert r==old


def test_staged_delays_tools_and_keeps_wrong_answer_and_cost():
    c=Client();r=request(c,row(),'original_staged')
    assert [call[0] for call in c.calls]==['text','tool']
    assert c.calls[1][2]['max_tokens']==128
    assert c.calls[1][2]['tool_choice']['function']['name']=='SUBMIT_JUDGMENT'
    assert r['usage']['completion_tokens']==42 and r['reasoning_present']
    assert r['first_pass_status']=='reasoning_complete'
    assert r['attempts'][0]['finish_reason']=='stop'
    assert r['answer']!=row()['expected']


def test_audit_export_resume_and_scores_do_not_select_successes(tmp_path):
    source=tmp_path/'source';source.mkdir();out=tmp_path/'out'
    manifest={'model':'mock','max_tokens':1024,'temperature':0}
    c=Client()
    args=['--source-run',str(source),'--output-dir',str(out),'--model','mock']
    with patch('benac_p.belief_interface_audit.prepare',return_value=(manifest,[row()])),patch('methods.vllm_client.OpenAICompatibleNegotiationClient',return_value=c):
        main(args+['--export-only'])
        assert not c.calls
        main(args+['--resume'])
        assert len(c.calls)==5
        main(args+['--resume'])
        assert len(c.calls)==5
    result=json.loads((out/'comparison.json').read_text())
    for variant in ('original_auto','clear_auto','original_staged','clear_staged'):
        assert result[variant]['known_copy']['exact']==0
        assert result[variant]['known_copy']['valid']==1
    assert not list(source.iterdir())
