import copy
import json
from concurrent.futures import Future, as_completed
from pathlib import Path
from unittest.mock import patch

import pytest

from examples.final_evaluation.calbench_retry import resources, run_suite
from examples.final_evaluation.calbench_local import Transport, InfrastructureFailure
from examples.final_evaluation.calbench_scaffold import BeliefTransport, ScaffoldFailure


class Response:
    def __init__(self, text, tokens=3, finish='stop'):
        self.raw=dict(choices=[dict(message=dict(content=text),finish_reason=finish)],
            usage=dict(prompt_tokens=10,completion_tokens=tokens,total_tokens=10+tokens) if type(tokens) is int else {})
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.raw).encode()


def stage(body):
    return 'ms' if body['messages'][-1]['content'].startswith('BELIEF / MS STAGE') else 'action'


def call_wrapper(tmp_path, provider):
    transport=BeliefTransport(dict(base_url='http://127.0.0.1:1/v1',model='FIXTURE'),dict(max_tokens=4096),tmp_path,77,0)
    original=[dict(role='user',content='ORIGINAL_POSITION')];before=copy.deepcopy(original)
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        result=transport.streaming_with_retry(original)
    assert original==before
    return transport,result


@pytest.mark.parametrize('failure',['length','empty','network','usage','exhausted'])
def test_retry_only_failed_ms_identical_prompt_before_one_action(tmp_path,failure):
    seen=[]
    def provider(request,**kwargs):
        body=json.loads(request.data);seen.append(body)
        if len(seen)==1:
            if failure=='network':raise TimeoutError('synthetic network error')
            if failure=='usage':return Response('bad usage',tokens=None)
            if failure=='exhausted':return Response('too long',tokens=4096)
            return Response('' if failure=='empty' else 'partial',tokens=4096,finish='length' if failure=='length' else 'stop')
        return Response('ACCEPTED_MS' if stage(body)=='ms' else '{"thinking":"done","actions":[]}',tokens=3 if stage(body)=='ms' else 5)
    transport,result=call_wrapper(tmp_path,provider)
    assert [stage(b) for b in seen]==['ms','ms','action']
    assert seen[0]==seen[1]  # includes exact model/seed/cap/messages
    assert seen[2]['messages'][-2]==dict(role='assistant',content='ACCEPTED_MS')
    assert seen[2]['max_tokens']==4093
    r=resources(tmp_path)
    assert r['prompt_retries']==r['recovered_prompts']==1 and r['exhausted_prompts']==0
    if failure in ('network','usage'):assert result['completion_tokens'] is None
    else:assert result['completion_tokens']==4096+3+5
    assert r['observed_physical_calls']==3
    logs=[json.loads(line) for line in (tmp_path/'ms/transport-agent-0.jsonl').read_text().splitlines()]
    assert [(x['call_index'],x['prompt_attempt'],x['accepted']) for x in logs]==[(0,1,False),(0,2,True)]
    # A subsequent native request advances the logical index by one, not by retries.
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        transport.streaming_with_retry([dict(role='user',content='NEXT_POSITION')])
    assert transport.ms.index==transport.action.index==2
    assert seen[3]['seed']!=seen[0]['seed']


@pytest.mark.parametrize('failure',['length','network','usage'])
def test_action_retry_keeps_successful_ms_and_remaining_budget(tmp_path,failure):
    seen=[]
    def provider(request,**kwargs):
        body=json.loads(request.data);seen.append(body)
        if len(seen)==2:
            if failure=='network':raise TimeoutError('synthetic')
            return Response('bad action',tokens=None if failure=='usage' else 4093,finish='length' if failure=='length' else 'stop')
        return Response('KEEP_THIS_MS' if stage(body)=='ms' else '{"thinking":"done","actions":[]}',tokens=3 if stage(body)=='ms' else 5)
    _,result=call_wrapper(tmp_path,provider)
    assert [stage(b) for b in seen]==['ms','action','action']
    assert seen[1]==seen[2] and seen[2]['max_tokens']==4093
    assert seen[2]['messages'][-2]['content']=='KEEP_THIS_MS'
    assert resources(tmp_path)['prompt_retries']==1
    assert result['completion_tokens']==(4101 if failure=='length' else None)


@pytest.mark.parametrize('fail_stage',['ms','action'])
def test_repeated_failure_tries_only_that_prompt_twice(tmp_path,fail_stage):
    seen=[]
    def provider(request,**kwargs):
        body=json.loads(request.data);seen.append(body)
        return Response('bad',tokens=4096 if stage(body)=='ms' else 4093,finish='length') if stage(body)==fail_stage else Response('ACCEPTED_MS')
    with pytest.raises(ScaffoldFailure):call_wrapper(tmp_path,provider)
    assert [stage(b) for b in seen]==(['ms','ms'] if fail_stage=='ms' else ['ms','action','action'])
    assert resources(tmp_path)['exhausted_prompts']==1


def test_native_transport_retry_same_request_and_counts_failed_cost(tmp_path):
    seen=[]
    def provider(request,**kwargs):
        seen.append(json.loads(request.data))
        return Response('partial' if len(seen)==1 else '{"thinking":"ok","actions":[]}',tokens=4096 if len(seen)==1 else 5,finish='length' if len(seen)==1 else 'stop')
    transport=Transport(dict(base_url='http://127.0.0.1:1/v1',model='F'),dict(max_tokens=4096,prompt_retry_once=True),tmp_path,7,0)
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        result=transport.streaming_with_retry([dict(role='user',content='CURRENT')])
    assert seen[0]==seen[1] and result['completion_tokens']==4101
    assert resources(tmp_path)['recovered_prompts']==1


class InlinePool:
    def submit(self,fn,*args):
        f=Future()
        try:f.set_result(fn(*args))
        except Exception as exc:f.set_exception(exc)
        return f


def test_failed_prompt_exhaustion_continues_all24_without_replaying_game(tmp_path):
    from examples.final_evaluation.calbench_stream import load_frozen
    from examples.final_evaluation.calbench_local import run_one
    from examples.final_evaluation.calbench_stream_metrics import summarize_run
    _,cases=load_frozen();seen_jobs=[];seen_requests=[]
    def worker(job,routes,output):
        seen_jobs.append(job['game_id'])
        return run_one(job,routes,output)
    def provider(request,**kwargs):
        body=json.loads(request.data);seen_requests.append(body)
        # First case's first prompt fails twice. All subsequent cases complete
        # with fixed empty actions, which is not successful scheduling.
        if len(seen_requests)<=2:return Response('loop',tokens=4096,finish='length')
        return Response('Belief fixture.' if stage(body)=='ms' else '{"thinking":"fixture","actions":[]}',tokens=1)
    routes=dict(scaffold='belief-ms',max_tokens=4096,temperature=0,endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='F') for a in ('q0','focal')})
    jobs=[dict(game_id=c['id'],stream_case=c['id'],seed=c['scenario_seed'],focal_seat=i) for i,c in enumerate(cases)]
    with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
        report=run_suite(jobs,routes,tmp_path,InlinePool(),worker,as_completed,2)
    assert seen_jobs==[j['game_id'] for j in jobs] and len(set(seen_jobs))==24
    assert seen_requests[0]==seen_requests[1]
    assert report['summary']['case_executions']==24 and report['summary']['cases_completed']==23
    assert not report['summary']['not_started']
    assert not (tmp_path/'retries').exists()
    assert report['resources']['prompt_retries']==report['resources']['exhausted_prompts']==1
    assert report['resources']['usage']['completion_tokens']['total']==8192+23*54
    assert (tmp_path/jobs[0]['game_id']/'events.jsonl').exists()
    assert json.loads((tmp_path/jobs[0]['game_id']/'result.json').read_text())['metrics'] is None
    done=json.loads((tmp_path/'RUN_FINISHED.json').read_text())
    assert done['suite_finished'] and done['all_cases_attempted'] and not done['engine_finished']
    audit=summarize_run(tmp_path)
    assert audit['observed_cases']==24 and len(audit['cases'])==24
    assert audit['cases'][0]['full_stream_completion'] is None
    assert audit['all_attempt_resources']==report['resources']


def test_worker_exception_continues_without_whole_case_retry(tmp_path):
    seen=[]
    def worker(job,routes,output):
        seen.append(job['game_id'])
        if job['game_id']=='broken':raise ValueError('synthetic worker failure')
        return dict(game_id=job['game_id'],engine_finished=True,healthy_transport=True)
    report=run_suite([dict(game_id=c) for c in ('broken','next')],{},tmp_path,InlinePool(),worker,as_completed,1)
    assert seen==['broken','next'] and report['summary']['case_executions']==2
    assert report['summary']['cases_completed']==1
    assert report['resources']['usage']['completion_tokens']['total'] is None
    assert report['resources']['case_elapsed_seconds_sum'] is None
    assert (tmp_path/'broken/worker_error.json').exists() and not (tmp_path/'retries').exists()


@pytest.mark.parametrize('record',[dict(status='infrastructure_failure'),dict(response=None),dict(response=dict(usage=None))])
def test_retry_resource_missing_usage_remains_unknown(tmp_path,record):
    (tmp_path/'transport-agent-0.jsonl').write_text(json.dumps(record)+'\n')
    assert resources(tmp_path)['usage']['completion_tokens']==dict(known_sum=0,missing_calls=1,total=None)


def test_recover_later_prompt_preserves_prior_game_progress(tmp_path):
    from examples.final_evaluation.calbench_local import run_one
    from examples.final_evaluation.calbench_stream import load_frozen
    _,cases=load_frozen();case=cases[0]
    job=dict(game_id=case['id'],stream_case=case['id'],seed=case['scenario_seed'],focal_seat=0)
    routes=dict(scaffold='belief-ms',max_tokens=4096,temperature=0,endpoints={a:dict(base_url='http://127.0.0.1:1/v1',model='F') for a in ('q0','focal')})
    sequences=[];results=[]
    for inject,name in ((False,'normal'),(True,'with_retry')):
        seen=[]
        def provider(request,**kwargs):
            body=json.loads(request.data);seen.append(body)
            if inject and len(seen)==8:return Response('partial',tokens=4093,finish='length')
            return Response('SAVED_MS' if stage(body)=='ms' else '{"thinking":"fixture","actions":[]}',tokens=1)
        with patch('examples.final_evaluation.calbench_local.urlopen',side_effect=provider):
            results.append(run_one(job,routes,tmp_path/name))
        sequences.append(seen)
    baseline,retried=sequences
    assert retried[:8]==baseline[:8] and retried[7]==retried[8]
    assert retried[9:]==baseline[8:]
    assert len(retried)==len(baseline)+1
    assert results[0]['engine_finished'] and results[1]['engine_finished']
    # Diagnostics keep the failed generation; state/actions must still agree.
    d0=copy.deepcopy(results[0]['diagnostics']);d1=copy.deepcopy(results[1]['diagnostics'])
    assert d1['format_errors']['strict_envelope_calls']==d0['format_errors']['strict_envelope_calls']+1
    d0['format_errors'].pop('strict_envelope_calls');d1['format_errors'].pop('strict_envelope_calls')
    assert d0==d1
    traces=[json.loads((tmp_path/name/case['id']/'trace.json').read_text()) for name in ('normal','with_retry')]
    assert traces[0]['final_state']==traces[1]['final_state']
    r=resources(tmp_path/'with_retry'/case['id'])
    assert r['prompt_retries']==r['recovered_prompts']==1
