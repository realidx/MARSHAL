import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from examples.final_evaluation.interaction_scaffold import VERSION, MS_GUIDANCE, action_request
from examples.final_evaluation.calbench_scaffold import MSGuidedTransport, protocol, verify_registration


def test_single_request_changes_only_current_user_and_keeps_generic_guidance():
    messages = [dict(role='system',content='Original rules and JSON output contract'),
                dict(role='user',content='Previous observation'),
                dict(role='assistant',content='Previous final action'),
                dict(role='user',content='Current private observation')]
    before=copy.deepcopy(messages)
    request=action_request(messages)
    assert messages==before and request[:-1]==messages[:-1]
    assert len(request)==len(messages)
    assert request[-1]==dict(role='user',content=messages[-1]['content']+'\n\n'+MS_GUIDANCE)
    assert 'briefly' in MS_GUIDANCE and 'Keep your reasoning brief' in MS_GUIDANCE
    assert not any(word in MS_GUIDANCE.lower() for word in ('calendar','meeting','slot','calbench'))


@pytest.mark.parametrize('messages',[[],[dict(role='system',content='rules')],
    [dict(role='assistant',content='reply')]])
def test_cannot_invent_or_rearrange_native_user_turns(messages):
    with pytest.raises(ValueError,match='ending in a text user message'):action_request(messages)


@pytest.mark.parametrize('budget',[4096,768])
def test_one_generation_cap_without_partition(budget):
    p=protocol(dict(max_tokens=budget))
    assert p['calls_per_native_request']==1 and p['total_output_cap_per_native_call']==budget
    assert 'ms_request_cap' not in p and 'action_request_cap' not in p


@pytest.mark.parametrize('budget',[None,0,-1,True,0.5])
def test_invalid_budget_rejected(budget):
    with pytest.raises(ValueError):protocol(dict(max_tokens=budget))


def test_old_stage_allocation_and_mode_rejected():
    with pytest.raises(ValueError,match='historical two-stage'):
        protocol(dict(max_tokens=4096,ms_max_tokens=512))
    from examples.final_evaluation.calbench_local import run_one
    with pytest.raises(ValueError,match='Historical scaffold'):
        run_one({},dict(scaffold='base-ms'),Path('/unused'))


class FakeTransport:
    def __init__(self,route,config,output,seed,agent_id):
        self.route,self.config,self.output,self.seed,self.agent_id=route,config,Path(output),seed,agent_id
        self.requests=[]
        self.result=dict(text='{"thinking":"brief assessment and choice","actions":[]}',finish_reason='stop',
                         prompt_tokens=10,completion_tokens=5,total_tokens=15)
    def streaming_with_retry(self,messages,**kwargs):
        self.requests.append((copy.deepcopy(messages),kwargs))
        return self.result


def test_one_provider_call_same_seed_raw_result_and_native_options(tmp_path):
    config=dict(max_tokens=4096,temperature=0,chat_template_kwargs={'enable_thinking':False})
    transport=MSGuidedTransport(dict(model='same-checkpoint'),config,tmp_path,123,2,transport_class=FakeTransport)
    native=[dict(role='user',content='visible')]
    result=transport.streaming_with_retry(native)
    assert result is transport.action.result and len(transport.action.requests)==1
    assert transport.action.config==config and transport.action.seed==123
    assert transport.action.requests[0]==(action_request(native),{})
    assert native==[dict(role='user',content='visible')]
    assert not list(tmp_path.iterdir())  # no MS directory or stage receipts


@pytest.mark.parametrize('finish,usage',[('length',None),('stop',None),('stop',5)])
def test_native_truncation_and_missing_usage_pass_through_unchanged(tmp_path,finish,usage):
    transport=MSGuidedTransport({},dict(max_tokens=4096),tmp_path,1,0,transport_class=FakeTransport)
    transport.action.result.update(finish_reason=finish,completion_tokens=usage)
    result=transport.streaming_with_retry([dict(role='user',content='visible')])
    assert result is transport.action.result
    assert result['finish_reason']==finish and result['completion_tokens']==usage


def test_native_client_export_has_one_call_and_original_history(tmp_path):
    from examples.final_evaluation.export_calbench_ms import export
    artifact=export(tmp_path/'export')
    assert len(artifact['examples'])==6
    for example in artifact['examples']:
        request=example['actual_action_request'];native=example['native_messages']
        assert example['provider_calls']==1 and 'actual_ms_request' not in example
        assert request['max_tokens']==4096 and request['messages']==action_request(native)
        assert request['messages'][0]==native[0]
        assert example['native_history_after'][:-1]==native[1:]
        assert example['native_history_after'][-1]['role']=='assistant'
        assert json.loads(example['native_history_after'][-1]['content'])==example['synthetic_action']
        assert MS_GUIDANCE not in json.dumps(native)
        assert not any('minimum_team_cost' in m['content'] or '"optimal"' in m['content'] for m in native)
    initial=artifact['examples'][0]
    assert 'Errand #9' not in json.dumps(initial['actual_action_request'])
    assert 'Meeting ID : 2' not in json.dumps(initial['actual_action_request'])
    assert not (tmp_path/'export/ms').exists()
    assert len((tmp_path/'export/transport-agent-0.jsonl').read_text().splitlines())==6


def test_runner_keeps_infrastructure_failure_separate(tmp_path):
    from urllib.error import URLError
    from examples.final_evaluation.calbench_local import run_one
    routes=dict(scaffold='ms-guided',max_tokens=4096,temperature=0,
                endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='fixture') for a in ('q0','focal')})
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=URLError('offline fixture')):
        result=run_one(dict(game_id='failed',stream_case='loose_uniform_s1',seed=2026091901,focal_seat=0),routes,tmp_path)
    assert not result['engine_finished'] and not result['healthy_transport'] and result['metrics'] is None
    assert result['error_type']=='InfrastructureFailure'
    assert not (tmp_path/'failed/ms').exists()


def test_registered_source_identity():
    assert verify_registration()['version']==VERSION


def test_all24_native_engine_fixed_actions_match_with_one_call(tmp_path):
    """Mechanical parity for fixed actions; no model efficacy inference."""
    from examples.final_evaluation.calbench_stream import load_frozen
    from examples.final_evaluation.calbench_local import run_one
    _,cases=load_frozen()
    native_root,guided_root=tmp_path/'native',tmp_path/'guided'
    native_root.mkdir();guided_root.mkdir()
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):
            return json.dumps(dict(choices=[dict(message=dict(content='{"thinking":"offline fixture","actions":[]}'),
                                   finish_reason='stop')],usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))).encode()
    routes=dict(max_tokens=4096,temperature=0,
                endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='OFFLINE_FIXTURE') for a in ('q0','focal')})
    with patch('examples.final_evaluation.calbench_local.urlopen',return_value=Response()):
        for i,case in enumerate(cases):
            job=dict(game_id=case['id'],stream_case=case['id'],seed=case['scenario_seed'],focal_seat=i)
            native=run_one(job,routes,native_root)
            guided=run_one(job,dict(routes,scaffold='ms-guided'),guided_root)
            assert native['engine_finished'] and guided['engine_finished']
            assert native['diagnostics']==guided['diagnostics']
            assert native['calls']==guided['calls']==guided['scaffold']['physical_calls']
            assert guided['scaffold']['ms_calls']==0
            assert guided['scaffold']['usage']['total_tokens']==2*guided['calls']
            assert not (guided_root/case['id']/'ms').exists()
            a=json.loads((native_root/case['id']/'trace.json').read_text())
            b=json.loads((guided_root/case['id']/'trace.json').read_text())
            assert a['final_state']==b['final_state']
    assert len(cases)==24


def test_launcher_selects_scaffold_explicitly(tmp_path, monkeypatch):
    import sys
    from examples.final_evaluation import launch_calbench_local as launcher
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    output=tmp_path/'run'
    class Process:
        pid=123456
        def poll(self):return None
        def wait(self,timeout=None):return 0
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"data": []}'
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def bind(self,address):pass
    monkeypatch.setattr(launcher.socket,'socket',Socket)
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','GPU-fixture')
    monkeypatch.setattr(launcher.importlib.metadata,'version',lambda name:'0.28.0')
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda *a,**kw:Process())
    monkeypatch.setattr(launcher.subprocess,'run',lambda *a,**kw:None)
    monkeypatch.setattr(launcher,'urlopen',lambda *a,**kw:Response())
    monkeypatch.setattr(launcher.os,'killpg',lambda *a:None)
    monkeypatch.setattr(launcher.signal,'signal',lambda *a:None)
    monkeypatch.setattr(sys,'argv',['launcher','--runtime','soc','--model',str(model),'--output',str(output),
                                  '--suite','stream','--scaffold','ms-guided','--ports','27101'])
    launcher.main()
    routes=json.loads((output/'routes.json').read_text())
    assert routes['scaffold']=='ms-guided' and protocol(routes)['total_output_cap_per_native_call']==4096
    assert 'ms_max_tokens' not in routes


def test_main_records_cli_protocol_and_all24_jobs(tmp_path, monkeypatch):
    import sys
    from concurrent.futures import Future
    from examples.final_evaluation import calbench_local as runner
    routes = tmp_path/'routes.json'
    routes.write_text(json.dumps(dict(max_tokens=4096,temperature=0,
        endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='fixture') for a in ('q0','focal')})))
    seen=[]
    class Executor:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def submit(self,fn,job,config,output):
            seen.append((job,config));future=Future()
            future.set_result(dict(game_id=job['game_id'],healthy_transport=True,healthy_scaffold=True))
            return future
    monkeypatch.setattr(runner,'ProcessPoolExecutor',Executor)
    output=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['calbench_local','--routes',str(routes),'--output',str(output),
        '--suite','stream','--scaffold','ms-guided'])
    runner.main()
    assert len(seen)==24 and all('ms_max_tokens' not in c and c['scaffold']=='ms-guided' for _,c in seen)
    execution=json.loads((output/'execution_protocol.json').read_text())
    assert execution['prompt_changed'] and execution['protocol']==VERSION
    assert execution['scaffold']['calls_per_native_request']==1
    assert execution['scaffold']['total_output_cap_per_native_call']==4096
    snapshot=json.loads((output/'pipeline_snapshot.json').read_text())
    assert 'ms_max_tokens' not in snapshot['cli']['parsed']
    assert snapshot['resolved_routes']['scaffold']=='ms-guided'
    assert snapshot['model_identity'].startswith('未记录')
