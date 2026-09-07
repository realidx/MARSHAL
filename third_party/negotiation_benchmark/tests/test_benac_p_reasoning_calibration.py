"""Budget comparisons preserve inputs, oracle targets, and failed-call coverage."""
import json
import pytest
from benac_p.semantic_suite import Suite, SYSTEM
from benac_p.diagnose_suite import dump, digest
from benac_p.diagnose_protocol import system_prompt, reasoning_instruction
from benac_p.reasoning_calibration import prepare, evaluate, summarize, main
from methods.vllm_client import VLLMChatCompletion, VLLMToolCall


@pytest.fixture
def source(tmp_path):
    out=tmp_path/'source';out.mkdir()
    suite=Suite(2,20000).build();static=list(suite.tasks);records={}
    for t in static:
        answer=suite.oracle_answer(t,records)
        if t['kind']=='semantic_belief' and '/after_assess_menu/' in t['id']:
            true=answer['possible_preferences'][0]
            answer={'possible_preferences':[next(p for p in ('want','neutral','avoid') if p!=true)]}
        records[t['id']]=dict(status='ok',answer=answer,finish_reason='tool_calls',usage={'completion_tokens':200},
                             payload_hash=digest(suite.payload(t,records)),response_protocol='reasoning_tools')
    dump(out/'manifest.json',dict(oracle_check=False,response_protocol='reasoning_tools',bundles=2,seed=20000,
                                task_hash=digest(static),max_tokens=1024,temperature=0.,model='mock'))
    dump(out/'tasks.json',dict(system=system_prompt(SYSTEM,'reasoning_tools','open'),tasks=static))
    dump(out/'answers.json',records)
    return out


def test_profile_keeps_historical_baseline_and_budget_is_soft():
    from benac_p.diagnose_protocol import BRIEF_REASONING
    assert reasoning_instruction('open')==BRIEF_REASONING
    assert '120 words' in reasoning_instruction('balanced') and '240 words' in reasoning_instruction('balanced')
    assert 'required length' in reasoning_instruction('balanced')
    assert 'equally best' in reasoning_instruction('balanced')
    assert '80 words' in reasoning_instruction('compact')
    with pytest.raises(ValueError):reasoning_instruction('unlimited')


def test_only_discovery_and_model_judgments_are_frozen(source):
    suite,manifest,selected=prepare(source,1)
    assert selected and all(suite.labels[r['id']]['split']=='discovery' for r in selected)
    rows=[r for r in selected if '/after_assess_menu/' in r['id'] and r['id'].endswith('/plan_model') and '/unknown_relevant/' in r['id']]
    assert rows
    for row in rows:
        label=suite.labels[row['id']]
        assert row['payload']['partner_judgment']['possible_preferences']!=label['possible_preferences']
        assert evaluate(row,row['baseline'])['success']==1
        idx=row['baseline']['answer']['action_index']
        assert max(label['q'])-label['q'][idx]>0  # True-judgment scoring would unfairly penalize this answer.


def test_failed_calls_cannot_win_by_disappearing(source):
    _,_,selected=prepare(source,1);records={}
    for row in selected:
        for p,tokens in [('open',200),('balanced',150),('compact',80)]:
            records[p+'/'+row['id']]=dict(row['baseline'],usage={'completion_tokens':tokens})
        if row['task']['kind']=='planning':records['compact/'+row['id']]=dict(status='truncated',finish_reason='length',usage={'completion_tokens':80})
    result=summarize(selected,records)
    assert result['profiles']['compact']['planning_valid_and_optimal_rate']==0
    assert result['recommended_profile']=='balanced'
    assert result['profiles']['balanced']['paired_vs_open']['token_delta']['mean']==-50


def test_cli_mock_uses_same_cap_and_preserves_source(source,tmp_path,monkeypatch):
    import methods.vllm_client
    before=(source/'answers.json').read_bytes();calls=[]
    class Client:
        def __init__(self,*args,**kwargs):assert kwargs['max_tokens']==1024
        def complete_with_tools(self,messages,**kwargs):
            calls.append(messages)
            assert kwargs['tool_choice']=='auto'
            p=json.loads(messages[1]['content']);name=kwargs['tools'][0]['function']['name']
            answer={'possible_preferences':p['initially_possible_preferences']} if name=='SUBMIT_JUDGMENT' else {'action_index':0}
            return VLLMChatCompletion('Brief.',(VLLMToolCall(name,answer),),{}, {'completion_tokens':100},'tool_calls')
    monkeypatch.setattr(methods.vllm_client,'OpenAICompatibleNegotiationClient',Client)
    out=tmp_path/'calibration';args=['--source-run',str(source),'--output-dir',str(out),'--per-stratum','1','--model','mock']
    main(args+['--export-only']);assert not calls
    n=len(json.loads((out/'tasks.json').read_text()))
    main(args+['--resume']);assert len(calls)==2*n
    assert (out/'report.md').exists() and (out/'comparison.json').exists()
    assert (source/'answers.json').read_bytes()==before
    main(args+['--resume']);assert len(calls)==2*n
    assert any('240 words' in m[0]['content'] for m in calls)
    assert any('80 words' in m[0]['content'] for m in calls)
