import json
from concurrent.futures import Future, as_completed
from pathlib import Path

import pytest

from examples.final_evaluation.calbench_retry import completed, resources, run_suite


class InlinePool:
    def submit(self, fn, *args):
        future=Future()
        try:future.set_result(fn(*args))
        except Exception as exc:future.set_exception(exc)
        return future


def fixture_worker(plan, seen):
    def worker(job, routes, output):
        number=job['suite_attempt'];case=job['game_id']
        seen.append((case,number,job['seed'],routes.copy()))
        outcome=plan.get((case,number),'ok')
        if outcome=='exception':raise ValueError('synthetic worker exception')
        folder=Path(output)/case;folder.mkdir(parents=True)
        (folder/'ms').mkdir()
        # Failed MS costs must remain counted even without an action response.
        count=4096 if outcome=='ms' else 3
        (folder/'ms/transport-agent-0.jsonl').write_text(json.dumps(dict(status='truncated' if outcome=='ms' else 'ok',
            response=dict(usage=dict(prompt_tokens=10,completion_tokens=count,total_tokens=10+count))))+'\n')
        if outcome!='ms':
            (folder/'transport-agent-0.jsonl').write_text(json.dumps(dict(status='ok',
                response=dict(usage=dict(prompt_tokens=20,completion_tokens=5,total_tokens=25))))+'\n')
        result=dict(game_id=case,engine_finished=outcome in ('ok','task_failure'),
            healthy_transport=outcome!='infra',healthy_scaffold=outcome not in ('ms','infra'),
            coordinated_success=outcome=='ok',metrics={} if outcome in ('ok','task_failure') else None,
            elapsed_seconds=1,error_type='ScaffoldFailure' if outcome=='ms' else None)
        (folder/'result.json').write_text(json.dumps(result))
        return result
    return worker


def test_all_cases_first_then_one_retry_keep_failure_and_total_cost(tmp_path):
    jobs=[dict(game_id=c,seed=7+i) for i,c in enumerate(('recover','double_fail','task_fail','healthy','infra'))]
    plan={('recover',1):'ms',('double_fail',1):'ms',('double_fail',2):'ms',
          ('task_fail',1):'task_failure',('infra',1):'infra'}
    seen=[]
    report=run_suite(jobs,dict(model='same',max_tokens=4096),tmp_path,InlinePool(),fixture_worker(plan,seen),as_completed,1)
    assert [(c,n) for c,n,_,_ in seen]==[(j['game_id'],1) for j in jobs]+[('recover',2),('double_fail',2),('infra',2)]
    assert all(seed==next(j['seed'] for j in jobs if j['game_id']==c) for c,_,seed,_ in seen)
    assert report['summary']['cases_attempted']==5 and report['summary']['attempts_total']==8
    assert report['summary']['first_attempt_completed']==2
    assert report['summary']['completed_after_retry']==4
    assert report['summary']['unresolved_cases']==['double_fail']
    rows={c['case_id']:c for c in report['cases']}
    assert rows['recover']['selected_attempt']==2
    assert rows['double_fail']['selected_result'] is None
    assert rows['task_fail']['selected_attempt']==1 and len(rows['task_fail']['attempts'])==1
    assert not rows['task_fail']['selected_result']['coordinated_success']
    assert (tmp_path/'recover/result.json').exists() and (tmp_path/'retries/recover/result.json').exists()
    # Three truncated MS attempts at 4096 + five non-MS-failed attempts at 3+5.
    assert report['resources']['usage']['completion_tokens']['total']==3*4096+5*8
    done=json.loads((tmp_path/'RUN_FINISHED.json').read_text())
    assert done['suite_finished'] and done['all_cases_attempted'] and not done['engine_finished']
    assert not done['healthy_transport']  # recovery must not erase original infra failure


def test_worker_exception_is_missing_but_does_not_stop_later_cases(tmp_path):
    jobs=[dict(game_id=c,seed=1) for c in ('broken','next')];seen=[]
    report=run_suite(jobs,{},tmp_path,InlinePool(),fixture_worker({('broken',1):'exception',('broken',2):'exception'},seen),as_completed,2)
    assert report['summary']['cases_attempted']==2 and report['summary']['attempts_total']==3
    assert report['summary']['completed_after_retry']==1
    assert report['resources']['usage']['completion_tokens']['total'] is None
    assert report['resources']['attempt_elapsed_seconds_sum'] is None
    assert (tmp_path/'broken/worker_error.json').exists()
    assert (tmp_path/'retries/broken/worker_error.json').exists()


@pytest.mark.parametrize('record',[dict(status='infrastructure_failure'),dict(response=None),dict(response=dict(usage=None))])
def test_retry_resource_missing_usage_remains_unknown(tmp_path,record):
    (tmp_path/'transport-agent-0.jsonl').write_text(json.dumps(record)+'\n')
    r=resources(tmp_path)
    assert r['observed_physical_calls']==1
    assert r['usage']['completion_tokens']==dict(known_sum=0,missing_calls=1,total=None)


def test_audit_collapses_retries_not_independent_cases(tmp_path):
    from examples.final_evaluation.calbench_stream_metrics import summarize_run
    jobs=[dict(game_id=c,seed=1) for c in ('recover','failed')];seen=[]
    run_suite(jobs,{},tmp_path,InlinePool(),fixture_worker({('recover',1):'ms',('failed',1):'ms',('failed',2):'ms'},seen),as_completed,1)
    report=summarize_run(tmp_path)
    assert report['expected_cases']==report['observed_cases']==2
    assert report['attempt_summary']['attempts_total']==4
    assert len(report['first_attempt_cases'])==2 and len(report['cases'])==2
    assert report['cases'][0]['selected_attempt']==2
    assert report['cases'][1]['full_stream_completion'] is None
    assert report['all_attempt_resources']['usage']['completion_tokens']['total']==3*4096+8


def test_audit_reads_selected_retry_trace_and_preserves_first_missing(tmp_path):
    from examples.final_evaluation.calbench_stream import load_frozen, FROZEN
    from examples.final_evaluation.calbench_stream_metrics import summarize_run
    _,cases=load_frozen();case=next(c for c in cases if c['id']=='loose_uniform_s1');name=case['id']
    run_suite([dict(game_id=name,seed=case['scenario_seed'])],{},tmp_path,InlinePool(),
              fixture_worker({(name,1):'ms'},[]),as_completed,1)
    for folder in (tmp_path/name,tmp_path/'retries'/name):
        (folder/'scenario.json').write_text(json.dumps(case['scenario']))
        (folder/'case_reference.json').write_text(json.dumps(case))
    trace=json.loads((FROZEN/f'certificates/{name}.json').read_text())[0]['trace']
    (tmp_path/'retries'/name/'trace.json').write_text(json.dumps(trace))
    report=summarize_run(tmp_path)
    assert report['observed_cases']==1
    assert report['first_attempt_cases'][0]['full_stream_completion'] is None
    assert report['cases'][0]['full_stream_completion'] is True
    assert report['cases'][0]['selected_attempt']==2
    assert report['all_attempt_resources']['usage']['completion_tokens']['total']==4096+8
