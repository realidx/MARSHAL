import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from examples.final_evaluation.interaction_scaffold import MS_INSTRUCTION, ms_request, action_request
from examples.final_evaluation.calbench_scaffold import MSTransport, ScaffoldFailure, protocol, verify_registration


def test_generic_builders_preserve_only_native_context():
    messages = [dict(role='system', content='Rules and original JSON output contract'),
                dict(role='user', content='MY_PRIVATE_OBSERVATION'),
                dict(role='assistant', content='MY_PREVIOUS_ACTION'),
                dict(role='user', content='RECEIVED_MESSAGE')]
    before = copy.deepcopy(messages)
    ms, act = ms_request(messages), action_request(messages, 'TENTATIVE_MS')
    assert messages == before
    assert ms[0]['content'].startswith(messages[0]['content'])
    assert MS_INSTRUCTION in ms[0]['content']
    assert ms[1:-1] == messages[1:]
    assert act[:-1] == messages and 'TENTATIVE_MS' in act[-1]['content']
    assert not any(word in MS_INSTRUCTION.lower() for word in ('calendar', 'slot', 'meeting', 'calbench'))


class FakeTransport:
    instances = []
    analysis = 'PRIVATE_MS_MARKER'
    finish_reason = 'stop'

    def __init__(self, route, config, output, seed, agent_id):
        self.route, self.config, self.output, self.seed = route, config, Path(output), seed
        self.requests = []
        self.instances.append(self)

    def streaming_with_retry(self, messages):
        self.requests.append(copy.deepcopy(messages))
        ms = self.output.name == 'ms'
        return dict(text=self.analysis if ms else '{"thinking":"done","actions":[]}',
                    finish_reason=self.finish_reason if ms else 'stop',
                    prompt_tokens=10 if ms else 20, completion_tokens=3 if ms else 5, total_tokens=13 if ms else 25)


def wrapper(tmp_path):
    return MSTransport(dict(model='same-checkpoint'), dict(max_tokens=4096, ms_max_tokens=512),
                       tmp_path, 123, 0, transport_class=FakeTransport)


def test_two_stage_same_checkpoint_budgets_usage_and_no_persistent_ms(tmp_path):
    transport = wrapper(tmp_path)
    messages = [dict(role='user', content='VISIBLE_CONTEXT')]
    before = copy.deepcopy(messages)
    result = transport.streaming_with_retry(messages)
    assert transport.ms.route == transport.action.route == dict(model='same-checkpoint')
    assert transport.ms.config['max_tokens'] == 512
    assert transport.action.config['max_tokens'] == 3584
    assert transport.action.seed == 123 and transport.ms.seed != 123
    assert (result['prompt_tokens'], result['completion_tokens'], result['total_tokens']) == (30, 8, 38)
    assert 'PRIVATE_MS_MARKER' not in result['text']
    assert 'PRIVATE_MS_MARKER' in transport.action.requests[0][-1]['content']
    transport.streaming_with_retry([dict(role='user',content='NEW_VISIBLE_CONTEXT')])
    assert 'PRIVATE_MS_MARKER' not in json.dumps(transport.ms.requests[1])
    assert messages == before
    assert len((tmp_path/'scaffold-agent-0.jsonl').read_text().splitlines()) == 2


@pytest.mark.parametrize('text,finish', [('', 'stop'), ('  ', 'stop'), ('partial', 'length'), ('partial', 'content_filter'), (None, 'stop')])
def test_analysis_failure_aborts_without_action_or_native_empty_fallback(tmp_path, monkeypatch, text, finish):
    monkeypatch.setattr(FakeTransport, 'analysis', text)
    monkeypatch.setattr(FakeTransport, 'finish_reason', finish)
    transport = wrapper(tmp_path)
    assert not issubclass(ScaffoldFailure, Exception)
    with pytest.raises(ScaffoldFailure):
        transport.streaming_with_retry([dict(role='user',content='visible')])
    assert not transport.action.requests
    receipt = json.loads((tmp_path/'scaffold-agent-0.jsonl').read_text())
    assert receipt['status'] == 'analysis_failure'


@pytest.mark.parametrize('total,ms', [(4096,0),(4096,4096),(4096,5000),(True,1),(4096,0.5)])
def test_invalid_budgets_fail_before_calls(total, ms):
    with pytest.raises(ValueError): protocol(dict(max_tokens=total,ms_max_tokens=ms))


def test_native_client_lifecycle_exports_full_requests_and_keeps_ms_private(tmp_path):
    from examples.final_evaluation.export_calbench_ms import export
    artifact = export(tmp_path/'export')
    assert len(artifact['examples']) == 6
    for example in artifact['examples']:
        ms, act = example['actual_ms_request'], example['actual_action_request']
        assert ms['model'] == act['model'] == 'OFFLINE_FIXTURE_NOT_A_MODEL'
        assert (ms['max_tokens'], act['max_tokens']) == (512,3584)
        assert act['messages'][:-1] == example['native_messages']
        assert 'internal analysis stage' not in json.dumps(example['native_messages']).lower()
        assert 'Tentative private analysis (JSON string' not in json.dumps(example['native_messages'])
        assert all('"optimal"' not in m['content'] and 'minimum_team_cost' not in m['content']
                   for m in example['native_messages'])
    initial = artifact['examples'][0]
    assert 'Errand #9' not in json.dumps(initial['actual_ms_request'])  # another player's private item
    assert 'Meeting ID : 2' not in json.dumps(initial['actual_ms_request'])  # future request
    assert initial['native_parsed_actions'] == initial['synthetic_action']['actions']
    assert len(list((tmp_path/'export/ms').glob('transport-*.jsonl'))) == 1
    assert len((tmp_path/'export/transport-agent-0.jsonl').read_text().splitlines()) == 6
    assert len((tmp_path/'export/ms/transport-agent-0.jsonl').read_text().splitlines()) == 6


def test_runner_aborts_ms_failure_as_missing_game_not_model_score(tmp_path):
    from examples.final_evaluation.calbench_local import run_one, verify_source
    verify_source()
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self):
            return json.dumps(dict(choices=[dict(message=dict(content='partial'),finish_reason='length')])).encode()
    routes = dict(scaffold='base-ms',max_tokens=4096,temperature=0,
                  endpoints={a:dict(base_url='http://127.0.0.1:1/v1', model='fixture') for a in ('q0','focal')})
    with patch('examples.final_evaluation.calbench_local.urlopen',return_value=Response()):
        result = run_one(dict(game_id='failed', stream_case='loose_uniform_s1', seed=2026091901, focal_seat=0), routes, tmp_path)
    assert not result['engine_finished'] and not result['healthy_scaffold']
    assert result['healthy_transport'] and result['error_type'] == 'ScaffoldFailure'
    assert result['metrics'] is None
    assert not list((tmp_path/'failed').glob('transport-agent-*.jsonl'))
    snapshot=json.loads((tmp_path/'failed/pipeline_snapshot.json').read_text())
    assert snapshot['game_config']['num_agents']==4
    assert snapshot['job']['stream_case']=='loose_uniform_s1'


def test_registered_source_identity():
    registered=verify_registration()
    assert registered['status']=='IMPLEMENTED_OFFLINE_VALIDATED_NOT_MODEL_EVALUATED'


def test_all24_native_engine_fixture_actions_match_with_and_without_ms(tmp_path):
    """Mechanical parity for fixed empty actions, not a policy/performance test."""
    from examples.final_evaluation.calbench_stream import load_frozen
    from examples.final_evaluation.calbench_local import run_one
    _, cases = load_frozen()
    native_root, ms_root = tmp_path/'native', tmp_path/'scaffold'
    native_root.mkdir(); ms_root.mkdir()
    requests = []
    class Response:
        def __init__(self, content): self.content=content
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self):
            return json.dumps(dict(choices=[dict(message=dict(content=self.content),finish_reason='stop')],
                                   usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))).encode()
    def provider(request, **kwargs):
        body=json.loads(request.data);requests.append(body)
        is_ms=MS_INSTRUCTION in body['messages'][0]['content']
        return Response('Tentative analysis based only on the current observations.' if is_ms
                        else '{"thinking":"offline empty-action fixture","actions":[]}')
    routes=dict(max_tokens=4096,temperature=0,
                endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='OFFLINE_FIXTURE') for a in ('q0','focal')})
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        for i,case in enumerate(cases):
            job=dict(game_id=case['id'],stream_case=case['id'],seed=case['scenario_seed'],focal_seat=i)
            native=run_one(job,routes,native_root)
            scaffold=run_one(job,dict(routes,scaffold='base-ms',ms_max_tokens=512),ms_root)
            assert native['engine_finished'] and scaffold['engine_finished'] and scaffold['healthy_scaffold']
            assert native['diagnostics']==scaffold['diagnostics']
            assert native['calls']==scaffold['calls']==scaffold['scaffold']['ms_calls']
            assert scaffold['strict_envelope_failures']==0
            assert scaffold['scaffold']['physical_calls']==2*scaffold['calls']
            assert scaffold['scaffold']['usage']['total_tokens']==4*scaffold['calls']
            native_trace=json.loads((native_root/case['id']/'trace.json').read_text())
            ms_trace=json.loads((ms_root/case['id']/'trace.json').read_text())
            assert native_trace['final_state']==ms_trace['final_state']
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
                                  '--suite','stream','--scaffold','base-ms','--ms-max-tokens','640','--ports','27101'])
    launcher.main()
    routes=json.loads((output/'routes.json').read_text())
    assert routes['scaffold']=='base-ms' and protocol(routes)['action_max_tokens']==3456


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
        '--suite','stream','--scaffold','base-ms','--ms-max-tokens','640'])
    runner.main()
    assert len(seen)==24 and all(c['ms_max_tokens']==640 and c['scaffold']=='base-ms' for _,c in seen)
    execution=json.loads((output/'execution_protocol.json').read_text())
    assert execution['prompt_changed'] and execution['protocol']=='general-ms-conditioning-v1'
    assert execution['scaffold']['action_max_tokens']==3456
    snapshot=json.loads((output/'pipeline_snapshot.json').read_text())
    assert snapshot['cli']['parsed']['ms_max_tokens']==640
    assert snapshot['resolved_routes']['scaffold']=='base-ms'
    assert snapshot['model_identity'].startswith('未记录')
