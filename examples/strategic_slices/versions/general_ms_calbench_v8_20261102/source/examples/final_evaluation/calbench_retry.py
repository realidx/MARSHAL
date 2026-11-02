"""Retry individual prompts once; execute each frozen case only once."""
import copy
import json
from pathlib import Path
import time

VERSION = 'calbench-prompt-retry-once-v8'


def retry_policy():
    return dict(version=VERSION, max_attempts_per_prompt=2, max_executions_per_case=1,
        retry_trigger='request/transport failure, empty or unfinished output; MS/action budget validation failure; native semantic/parser retries otherwise unchanged',
        restart='only the failed prompt at the current game position, immediately; no whole-case or previous-stage replay',
        request='identical messages/model/seed/temperature/max_tokens; failed output never appended',
        action_retry='keep the accepted MS and retry only action with the same remaining cap',
        stop_on_case_failure=False,
        budget='accepted MS + accepted action share configured cap (primary4096); failed-generation retries add fully recorded compute beyond that cap',
        exhausted='after two failed attempts abort only this case and continue remaining cases',
        report='one case result; preserve every physical prompt attempt, errors and all costs; incomplete utility remains missing')


def completed(result):
    return bool(result.get('engine_finished') and result.get('healthy_transport')
                and result.get('healthy_scaffold', True))


def usage_from_calls(calls):
    usage = {}
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [((c.get('response') or {}).get('usage') or {}).get(key) for c in calls]
        known = [v for v in values if type(v) is int and v >= 0]
        missing = len(values)-len(known)
        usage[key] = dict(known_sum=sum(known), missing_calls=missing,
                          total=sum(known) if values and not missing else None)
    return usage


def resources(folder):
    """Count all physical calls, including discarded failed prompt generations."""
    folder = Path(folder)
    calls = [json.loads(line) for p in list(folder.glob('transport-*.jsonl'))
             + list((folder/'ms').glob('transport-*.jsonl')) for line in p.read_text().splitlines()]
    retries = [c for c in calls if c.get('prompt_attempt', 1)==2]
    return dict(observed_physical_calls=len(calls), usage=usage_from_calls(calls),
        prompt_retries=len(retries), recovered_prompts=sum(c.get('accepted') is True for c in retries),
        exhausted_prompts=sum(c.get('accepted') is False for c in retries),
        failed_prompt_attempts=sum(c.get('accepted') is False for c in calls),
        had_transport_failures=any(c.get('status')=='infrastructure_failure' for c in calls),
        scope='all recorded physical calls; absent logs/usage remain unknown, not fabricated zeros')


def _dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def run_suite(jobs, routes, output, pool, worker, as_completed, parallel_games):
    """Continue after case failure. Prompt retries happen inside its transport."""
    output = Path(output)
    started = time.monotonic()
    rows = {j['game_id']: dict(case_id=j['game_id'], folder=j['game_id'],
        job=copy.deepcopy(j), result=None, resources=None) for j in jobs}
    results = []

    def persist():
        cases = list(rows.values())
        observed = [c for c in cases if c['result'] is not None]
        usage = {}
        unknown = sum(c['resources']['observed_physical_calls']==0 for c in observed)
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            known = sum(c['resources']['usage'][key]['known_sum'] for c in observed)
            missing = sum(c['resources']['usage'][key]['missing_calls'] for c in observed)
            usage[key] = dict(known_sum=known, missing_calls=missing,
                total=known if observed and not missing and not unknown else None)
        durations = [c['result'].get('elapsed_seconds') for c in observed]
        known_durations = [d for d in durations if type(d) in (int,float) and d>=0]
        summary = dict(cases_expected=len(jobs), cases_attempted=len(observed),
            cases_completed=sum(completed(c['result']) for c in observed), case_executions=len(observed),
            unresolved_cases=[c['case_id'] for c in observed if not completed(c['result'])],
            not_started=[c['case_id'] for c in cases if c['result'] is None],
            suite_elapsed_seconds=time.monotonic()-started)
        costs = dict(observed_physical_calls=sum(c['resources']['observed_physical_calls'] for c in observed),
            cases_without_call_logs=unknown, usage=usage,
            case_elapsed_seconds_known_sum=sum(known_durations),
            cases_missing_elapsed_seconds=len(durations)-len(known_durations),
            case_elapsed_seconds_sum=sum(known_durations) if len(durations)==len(known_durations) else None)
        for key in ('prompt_retries','recovered_prompts','exhausted_prompts','failed_prompt_attempts'):
            costs[key] = sum(c['resources'][key] for c in observed)
        report = dict(schema=2, policy=retry_policy(), summary=summary, cases=cases, resources=costs,
            interpretation='One execution per case; retry only failed prompt in place. Costs include discarded outputs. No aborted task utility is zero-filled.')
        _dump(output/'case_results.json', report)
        _dump(output/'results.json', results)
        return report

    persist()
    for offset in range(0,len(jobs),parallel_games):
        futures = {pool.submit(worker, copy.deepcopy(job), copy.deepcopy(routes), output):job
                   for job in jobs[offset:offset+parallel_games]}
        for future in as_completed(futures):
            job = futures[future]
            folder = output/job['game_id']
            try:
                result = future.result()
            except Exception as exc:
                result = dict(game_id=job['game_id'],engine_finished=False,healthy_transport=False,
                    error_type=type(exc).__name__,error=str(exc),metrics=None)
                folder.mkdir(parents=True,exist_ok=True)
                _dump(folder/'worker_error.json',result)
            rows[job['game_id']].update(result=result,resources=resources(folder))
            results.append(result)
            report = persist()
            print(f"case={job['game_id']} engine_completed={completed(result)} "
                  f"cases={report['summary']['cases_attempted']}/{len(jobs)}",flush=True)
    report = persist()
    _dump(output/'RUN_FINISHED.json',dict(formal_test=True,suite_finished=True,
        all_cases_attempted=report['summary']['cases_attempted']==len(jobs),
        engine_finished=report['summary']['cases_completed']==len(jobs),
        healthy_transport=all(c['result'].get('healthy_transport',False) for c in report['cases']),
        had_transport_failures=any(c['resources']['had_transport_failures'] for c in report['cases']),
        prompt_retry_policy=retry_policy(),**report['summary']))
    return report
