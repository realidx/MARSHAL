import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from examples.final_evaluation.interaction_scaffold import VERSION, MS_INSTRUCTION, ms_request, action_request
from examples.final_evaluation.calbench_scaffold import BeliefTransport, ScaffoldFailure, protocol, verify_registration
from examples.final_evaluation.calbench_stage_context import stage_context


def test_generic_builders_preserve_only_native_context():
    messages = [dict(role='system', content='Rules and original JSON output contract'),
                dict(role='user', content='MY_PRIVATE_OBSERVATION'),
                dict(role='assistant', content='MY_PREVIOUS_ACTION'),
                dict(role='user', content='RECEIVED_MESSAGE')]
    before = copy.deepcopy(messages)
    ms = ms_request(messages)
    act = action_request(ms, 'TENTATIVE_MS')
    assert messages == before
    assert ms[:-1] == messages
    assert ms[-1] == dict(role='user',content=MS_INSTRUCTION)
    assert len(ms)==len(messages)+1
    assert act[:-2] == ms
    assert act[-2] == dict(role='assistant',content='TENTATIVE_MS')
    assert act[-1]['role']=='user' and act[-1]['content'].startswith('ACTION STAGE')
    assert not any(word in MS_INSTRUCTION.lower() for word in ('calendar', 'slot', 'meeting', 'calbench'))


def test_actual_first_response_is_the_assistant_turn_for_action(tmp_path):
    transport=wrapper(tmp_path)
    transport.ms.analysis='THE_ACTUAL_FIRST_PROVIDER_REPLY'
    native=[dict(role='system',content='native system'),dict(role='user',content='original user prompt')]
    transport.streaming_with_retry(native)
    first=transport.ms.requests[0]
    second=transport.action.requests[0]
    assert [m['role'] for m in first]==['system','user','user']
    assert [m['role'] for m in second]==['system','user','user','assistant','user']
    assert first[:-1]==stage_context(native).messages and second[:-2]==first
    assert 'STAGE PROTOCOL' in first[0]['content']
    assert 'No action or' in second[-1]['content']
    assert second[-2]['content']=='THE_ACTUAL_FIRST_PROVIDER_REPLY'
    assert second[-1]['content'].startswith('ACTION STAGE')


@pytest.mark.parametrize('messages', [[], [dict(role='system',content='rules')],
    [dict(role='assistant',content='past action')]])
def test_ms_does_not_rearrange_or_invent_native_user_turns(messages):
    with pytest.raises(ValueError,match='ending in a text user message'):
        ms_request(messages)


class FakeTransport:
    instances = []
    analysis = 'PRIVATE_MS_MARKER'
    finish_reason = 'stop'
    ms_tokens = 3
    action_tokens = 5

    def __init__(self, route, config, output, seed, agent_id):
        self.route, self.config, self.output, self.seed = route, config, Path(output), seed
        self.requests = []
        self.request_caps = []
        self.instances.append(self)

    def streaming_with_retry(self, messages, **kwargs):
        for attempt in range(2 if self.config.get('prompt_retry_once') else 1):
            self.requests.append(copy.deepcopy(messages))
            self.request_caps.append(kwargs.get('max_tokens',self.config['max_tokens']))
            ms = self.output.name == 'ms'
            tokens = self.ms_tokens if ms else self.action_tokens
            response = dict(text=self.analysis if ms else '{"thinking":"done","actions":[]}',
                        finish_reason=self.finish_reason if ms else 'stop',
                        prompt_tokens=10 if ms else 20, completion_tokens=tokens,
                        total_tokens=(10 if ms else 20)+tokens if type(tokens) is int else None)
            try:
                if kwargs.get('_validate'):kwargs['_validate'](response)
                return response
            except ScaffoldFailure:
                if attempt==1 or not self.config.get('prompt_retry_once'):raise


def wrapper(tmp_path):
    return BeliefTransport(dict(model='same-checkpoint'), dict(max_tokens=4096),
                       tmp_path, 123, 0, transport_class=FakeTransport)


def test_two_stage_same_checkpoint_budgets_usage_and_no_persistent_ms(tmp_path):
    transport = wrapper(tmp_path)
    messages = [dict(role='user', content='VISIBLE_CONTEXT')]
    before = copy.deepcopy(messages)
    result = transport.streaming_with_retry(messages)
    assert transport.ms.route == transport.action.route == dict(model='same-checkpoint')
    assert transport.ms.request_caps == [4096]
    assert transport.action.request_caps == [4093]
    assert transport.action.seed == 123 and transport.ms.seed != 123
    assert (result['prompt_tokens'], result['completion_tokens'], result['total_tokens']) == (30, 8, 38)
    assert 'PRIVATE_MS_MARKER' not in result['text']
    assert transport.action.requests[0][:-2] == transport.ms.requests[0]
    assert transport.action.requests[0][-2] == dict(role='assistant',content='PRIVATE_MS_MARKER')
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


@pytest.mark.parametrize('total', [0,-1,True,0.5,None])
def test_invalid_budgets_fail_before_calls(total):
    with pytest.raises(ValueError): protocol(dict(max_tokens=total))


def test_old_fixed_allocation_cannot_be_silently_reused():
    with pytest.raises(ValueError, match='historical'):
        protocol(dict(max_tokens=4096, ms_max_tokens=512))


def test_action_budget_tracks_actual_ms_usage_on_each_call(tmp_path):
    transport = wrapper(tmp_path)
    transport.ms.ms_tokens = 1000
    transport.streaming_with_retry([dict(role='user', content='visible')])
    transport.ms.ms_tokens = 2000
    transport.streaming_with_retry([dict(role='user', content='new visible')])
    assert transport.ms.request_caps == [4096,4096]
    assert transport.action.request_caps == [3096,2096]
    receipts = [json.loads(s) for s in (tmp_path/'scaffold-agent-0.jsonl').read_text().splitlines()]
    assert [r['budget']['ms_completion_tokens'] for r in receipts] == [1000,2000]


@pytest.mark.parametrize('used', [None, -1, True, 1.5, 4097])
def test_unusable_ms_usage_aborts_without_guessing_tokens(tmp_path, used):
    transport = wrapper(tmp_path)
    transport.ms.ms_tokens = used
    with pytest.raises(ScaffoldFailure, match='completion_tokens'):
        transport.streaming_with_retry([dict(role='user',content='visible')])
    assert not transport.action.requests


def test_ms_may_use_whole_budget_but_action_cannot_overspend(tmp_path):
    transport = wrapper(tmp_path)
    transport.ms.ms_tokens = 4096
    with pytest.raises(ScaffoldFailure, match='exhausted'):
        transport.streaming_with_retry([dict(role='user',content='visible')])
    assert not transport.action.requests
    assert json.loads((tmp_path/'scaffold-agent-0.jsonl').read_text())['status']=='budget_exhausted'


@pytest.mark.parametrize('used', [None, -1, True, 4094])
def test_bad_action_usage_is_not_executed(tmp_path, used):
    transport = wrapper(tmp_path)
    transport.action.action_tokens = used  # remaining cap = 4093
    with pytest.raises(ScaffoldFailure, match='action completion_tokens'):
        transport.streaming_with_retry([dict(role='user',content='visible')])


def test_exact_budget_total_and_zero_remaining_after_action_are_valid(tmp_path):
    transport = wrapper(tmp_path)
    transport.ms.ms_tokens = 4095
    transport.action.action_tokens = 1
    result = transport.streaming_with_retry([dict(role='user',content='visible')])
    assert transport.action.request_caps == [1]
    assert result['completion_tokens'] == 4096


def test_native_client_lifecycle_exports_full_requests_and_keeps_ms_private(tmp_path):
    from examples.final_evaluation.export_calbench_ms import export
    artifact = export(tmp_path/'export')
    assert len(artifact['examples']) == 6
    for example in artifact['examples']:
        ms, act = example['actual_ms_request'], example['actual_action_request']
        assert ms['model'] == act['model'] == 'OFFLINE_FIXTURE_NOT_A_MODEL'
        assert (ms['max_tokens'], act['max_tokens']) == (4096,4093)
        assert act['messages'][:-2] == ms['messages']
        assert act['messages'][-2] == dict(role='assistant', content=example['synthetic_ms'])
        assert ms['messages'][:-1] == stage_context(example['native_messages']).messages
        assert 'Always respond with a JSON object' not in ms['messages'][0]['content']
        assert 'Always respond with a JSON object' in act['messages'][-1]['content']
        assert ms['messages'][-1] == dict(role='user',content=MS_INSTRUCTION)
        assert example['native_history_after'][:-1] == example['native_messages'][1:]
        assert example['native_history_after'][-1]['role'] == 'assistant'
        assert json.loads(example['native_history_after'][-1]['content']) == example['synthetic_action']
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
    routes = dict(scaffold='belief-ms',max_tokens=4096,temperature=0,
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
        is_ms=body['messages'][-1]['content'].endswith(MS_INSTRUCTION)
        return Response('Tentative analysis based only on the current observations.' if is_ms
                        else '{"thinking":"offline empty-action fixture","actions":[]}')
    routes=dict(max_tokens=4096,temperature=0,
                endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='OFFLINE_FIXTURE') for a in ('q0','focal')})
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        for i,case in enumerate(cases):
            job=dict(game_id=case['id'],stream_case=case['id'],seed=case['scenario_seed'],focal_seat=i)
            native=run_one(job,routes,native_root)
            scaffold=run_one(job,dict(routes,scaffold='belief-ms'),ms_root)
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
                                  '--suite','stream','--scaffold','belief-ms','--ports','27101'])
    launcher.main()
    routes=json.loads((output/'routes.json').read_text())
    assert routes['scaffold']=='belief-ms' and protocol(routes)['total_output_cap_per_native_call']==4096
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
            future.set_result(dict(game_id=job['game_id'],engine_finished=True,healthy_transport=True,healthy_scaffold=True))
            return future
    monkeypatch.setattr(runner,'ProcessPoolExecutor',Executor)
    output=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['calbench_local','--routes',str(routes),'--output',str(output),
        '--suite','stream','--scaffold','belief-ms'])
    runner.main()
    assert len(seen)==24 and all('ms_max_tokens' not in c and c['scaffold']=='belief-ms' for _,c in seen)
    execution=json.loads((output/'execution_protocol.json').read_text())
    assert execution['prompt_changed'] and execution['protocol']==VERSION
    assert execution['scaffold']['action_request_cap']=='max_tokens - actual MS usage.completion_tokens'
    snapshot=json.loads((output/'pipeline_snapshot.json').read_text())
    assert 'ms_max_tokens' not in snapshot['cli']['parsed']
    assert snapshot['resolved_routes']['scaffold']=='belief-ms'
    assert snapshot['model_identity'].startswith('未记录')
