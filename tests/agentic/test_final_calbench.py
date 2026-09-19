import json
from unittest.mock import patch
import pytest
from examples.final_evaluation.calbench_local import Transport, load_routes, verify_source


def test_source_matches_pinned_manifest():
    assert len(verify_source()) == 64


def test_remote_routes_require_explicit_opt_in(tmp_path):
    path=tmp_path/'routes.json'
    config={'endpoints':{a:{'base_url':'https://example.com/v1','model':'test'} for a in ('focal','q0')}}
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='local_only'):load_routes(path)
    config['local_only']=False;path.write_text(json.dumps(config))
    assert load_routes(path)==config


def test_transport_records_truncation_and_leaves_native_parsing_intact(tmp_path):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return json.dumps({'choices':[{'message':{'content':'{"actions": ['},'finish_reason':'length'}],'usage':{'completion_tokens':768}}).encode()
    route={'base_url':'http://127.0.0.1:1234/v1','model':'test'}
    transport=Transport(route,{},tmp_path,10,2)
    with patch('examples.final_evaluation.calbench_local.urlopen',return_value=Response()):
        result=transport.streaming_with_retry([{'role':'user','content':'native prompt'}])
    record=json.loads((tmp_path/'transport-agent-2.jsonl').read_text())
    assert result['text']=='{"actions": ['
    assert record['status']=='truncated'
    assert not record['strict_envelope_valid']
    assert record['elapsed_seconds']>=0
    assert 'Authorization' not in record


def test_frozen_suite_certificates_and_costs():
    from examples.final_evaluation.calbench_formal import FROZEN, load_frozen
    manifest,cases=load_frozen()
    assert len(cases)==12 and manifest['structure_group_count']==10
    assert [c['reference']['minimum_team_cost'] for c in cases]==[0,0,0,0,6,3,1,4,3,3,1,3]
    successes=failures=0
    for case in cases:
        certificates=json.loads((FROZEN/f"certificates/{case['id']}.json").read_text())
        for cert in certificates:
            metrics=cert['trace']['metrics']
            if cert['kind']=='success':
                assert metrics['meetings_scheduled']==1
                assert metrics['realized_cost']==cert['plan']['cost']
                actions=cert['plan']['actions']
                expected=sum(case['scenario']['calendars'][a][x['from_slot']]['cost']
                             for a,batch in enumerate(actions) for x in batch if x['type']=='reschedule')
                assert metrics['realized_cost']==expected
                successes+=1
            else:
                assert metrics['meetings_scheduled']==0
                assert any(e['type']=='consistency_violation' for e in cert['trace']['events'])
                failures+=1
    assert (successes,failures)==(30,4)


def test_frozen_suite_rejects_tampering(tmp_path):
    import shutil
    from examples.final_evaluation.calbench_formal import FROZEN, load_frozen
    clone=tmp_path/'suite';shutil.copytree(FROZEN,clone)
    path=clone/'cases/F1.json';path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError,match='mismatch'):load_frozen(clone)


def test_transport_infrastructure_failure_cannot_become_empty_action(tmp_path):
    from urllib.error import URLError
    from examples.final_evaluation.calbench_local import InfrastructureFailure
    transport=Transport({'base_url':'http://127.0.0.1:1234/v1','model':'test'}, {},tmp_path,10,2)
    assert not issubclass(InfrastructureFailure,Exception)
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=URLError('connection refused')):
        with pytest.raises(InfrastructureFailure):
            transport.streaming_with_retry([{'role':'user','content':'native prompt'}])
    record=json.loads((tmp_path/'transport-agent-2.jsonl').read_text())
    assert record['status']=='infrastructure_failure'


def test_reasoning_wrapper_separated_before_native_json_repair():
    from examples.final_evaluation.calbench_local import separate_reasoning
    answer='{"thinking":"agree","actions":[{"type":"schedule","meeting_id":1,"slot":4}]}'
    raw='<think>Example: {"slot": 3}. Actual choice is 4.</think>\n'+answer
    text,thought,kind=separate_reasoning(raw)
    assert text==answer and kind=='separated_reasoning'
    assert json.loads(text)['actions'][0]['slot']==4
    assert 'Actual choice' in thought
    assert separate_reasoning(answer)==(answer,None,'plain')


def test_unfinished_reasoning_never_becomes_an_action():
    from examples.final_evaluation.calbench_local import separate_reasoning
    raw='<think>Maybe {"actions":[{"type":"schedule","meeting_id":1,"slot":4}]}'
    text,thought,kind=separate_reasoning(raw)
    assert text=='' and thought and kind=='unfinished_reasoning'


@pytest.mark.parametrize('gpu_count',[1,2])
@pytest.mark.parametrize('suite',['formal','stream'])
def test_soc_launcher_uses_slurm_devices_and_v1_flags(tmp_path,monkeypatch,gpu_count,suite):
    import sys
    from examples.final_evaluation import launch_calbench_local as launcher
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    output=tmp_path/'run';commands=[];runner=[]
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
    def spawn(cmd,**kwargs):commands.append((cmd,kwargs['env']));return Process()
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES',','.join(f'GPU-test-{i}' for i in range(gpu_count)))
    monkeypatch.setenv('VLLM_USE_V1','0')
    monkeypatch.setenv('VLLM_ATTENTION_BACKEND','XFORMERS')
    monkeypatch.setenv('TRITON_PTXAS_PATH','/obsolete/cuda11/ptxas')
    monkeypatch.setattr(launcher.importlib.metadata,'version',lambda name:'0.28.0')
    monkeypatch.setattr(launcher.subprocess,'Popen',spawn)
    monkeypatch.setattr(launcher.subprocess,'run',lambda cmd,**kw:runner.append(cmd))
    monkeypatch.setattr(launcher,'urlopen',lambda *a,**kw:Response())
    monkeypatch.setattr(launcher.os,'killpg',lambda *a:None)
    monkeypatch.setattr(launcher.signal,'signal',lambda *a:None)
    monkeypatch.setattr(sys,'argv',['launcher','--runtime','soc','--model',str(model),'--output',str(output),
                                  '--suite',suite,'--max-tokens','4096','--ports']+[str(27101+i) for i in range(gpu_count)])
    launcher.main()
    assert len(commands)==gpu_count
    for i,(cmd,env) in enumerate(commands):
        assert env['CUDA_VISIBLE_DEVICES']==f'GPU-test-{i}'
        assert not any(k in env for k in ('VLLM_USE_V1','VLLM_ATTENTION_BACKEND','TRITON_PTXAS_PATH'))
        assert '--enforce-eager' in cmd
        assert '--disable-frontend-multiprocessing' not in cmd
        assert '--max-seq-len-to-capture' not in cmd
    config=json.loads((output/'routes.json').read_text())
    assert len(config['equivalent_replicas'])==gpu_count
    assert config['max_tokens']==4096 and config['timeout_seconds']==600
    assert runner and (output/'EXIT_CODE').read_text()=='0\n'


def test_stream_suite_native_replays_and_seed_coverage():
    from collections import defaultdict
    from examples.final_evaluation.calbench_stream import load_frozen, plans, replay
    verify_source()
    manifest, cases = load_frozen()
    assert len(cases) == 24
    assert manifest['sampling']['temperature'] == 0
    groups = defaultdict(list)
    for case in cases:
        groups[case['structure_group']].append(case)
        scenario = case['scenario']
        cost, slots = plans(scenario)[0]
        trace = replay(scenario, slots)
        assert trace.metrics['meetings_scheduled'] == 3
        assert trace.metrics['realized_cost'] == cost == case['reference']['minimum_team_cost']
        if case['family'] == 'replan':
            valid = replay(scenario, (1,0,2), replan=True)
            invalid = replay(scenario, (1,0,2), replan=True, contact=False)
            assert valid.metrics['meetings_scheduled'] == 3
            assert valid.metrics['realized_cost'] == 3
            assert invalid.metrics['meetings_scheduled'] < 3
            assert any(e.type == 'consistency_violation' for e in invalid.events)
    assert len(groups) == 8
    for cases in groups.values():
        assert {c['scenario_seed'] for c in cases} == set(manifest['scenario_seeds'])
        # Distinct initial calendars, not just distinct seed labels.
        assert len({json.dumps(c['scenario']['calendars'],sort_keys=True) for c in cases}) == 3


def test_stream_runner_uses_homogeneous_team_and_three_meeting_reference(tmp_path, monkeypatch):
    from examples.final_evaluation.calbench_stream import load_frozen, plans, replay
    from examples.final_evaluation.calbench_local import run_one
    verify_source()
    from calendar_game.game import CalendarGame
    _, cases = load_frozen()
    case = next(c for c in cases if c['id']=='dense_uniform_s1')
    cost, slots = plans(case['scenario'])[0]
    trace = replay(case['scenario'], slots)
    def fake_run(game, scenario):
        assert game.config.num_meetings == 3
        assert [a.model for a in game.config.agents] == ['q0']*4
        return trace
    monkeypatch.setattr(CalendarGame, 'run_with_scenario', fake_run)
    result = run_one(dict(game_id=case['id'],stream_case=case['id'],seed=case['scenario_seed'],focal_seat=23),
                     {'endpoints':{'q0':{},'focal':{}}},tmp_path)
    assert result['coordinated_success']
    assert result['successful_and_optimal']
    assert result['meeting_completion_rate'] == 1
    assert result['verified_reference_excess_cost'] == 0

    trace.metrics['meetings_scheduled'] = 3  # Historical successes must not mask final corruption.
    for row in trace.final_state['calendars']:
        for i,item in enumerate(row):
            if item and item.get('meeting_id') in (2,3): row[i]=None
    result = run_one(dict(game_id='incomplete',stream_case=case['id'],seed=case['scenario_seed'],focal_seat=23),
                     {'endpoints':{'q0':{},'focal':{}}},tmp_path)
    assert not result['coordinated_success']
    assert result['verified_reference_excess_cost'] is None
    assert result['meeting_completion_rate'] == 1/3


def test_stream_diagnostics_replan_and_final_consistency():
    from examples.final_evaluation.calbench_stream import load_frozen, FROZEN
    from examples.final_evaluation.calbench_stream_metrics import diagnose
    _,cases=load_frozen()
    case=next(c for c in cases if c['id']=='replan_uniform_s1')
    certificates=json.loads((FROZEN/'certificates/replan_uniform_s1.json').read_text())
    expected=[(0,0,0,1),(1,1,1,0),(1,0,0,0)]
    for cert,counts in zip(certificates,expected):
        trace=cert['trace']
        d=diagnose(trace,case['scenario'],replan=True)
        assert tuple(d['replan_branch'].values())==counts
        assert d['vps'] is None
        assert d['full_stream_completion']==(cert['kind']!='replan_missing_contact')
    assert d['coordination_failures']['prior_meeting_inconsistency_rounds']==2
    trace=certificates[0]['trace']
    trace['events'].extend([
        dict(type='batch_rejected',data={'conflict_description':'Schedule action missing required field slot'}),
        dict(type='batch_rejected',data={'conflict_description':'Cannot move blocked errand'}),
        dict(type='batch_applied',data={})])
    d=diagnose(trace,case['scenario'],[{'strict_envelope_valid':False}])
    assert d['format_errors']==dict(strict_envelope_calls=1,native_schema_rejections=1)
    assert d['semantic_invalid_actions']==1
    assert d['full_stream_completion']
