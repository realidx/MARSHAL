"""Bounded whole-case retry; keep all attempts and finish the frozen suite."""
import copy
import json
from pathlib import Path
import time

VERSION = 'calbench-case-retry-once-v7'


def retry_policy():
    return dict(version=VERSION, max_attempts_per_case=2,
        order='all first attempts, then exactly one retry of each aborted case',
        retry_trigger='engine abort, scaffold failure, infrastructure failure or worker exception; not an ordinary completed game with poor task outcome',
        restart='whole case from the frozen initial state with fresh player histories',
        seed='same original scenario and sampling seeds; no new temperature or hidden reseeding',
        stop_on_case_failure=False, budget='original per-native-call budget on each attempt; all attempt costs retained',
        report='first attempt and post-retry outcomes separately; incomplete utility remains missing')


def completed(result):
    return bool(result.get('engine_finished') and result.get('healthy_transport')
                and result.get('healthy_scaffold', True))


def resources(folder):
    """Count logged calls from both stages, including failed attempts."""
    folder = Path(folder)
    calls = [json.loads(line) for p in list(folder.glob('transport-*.jsonl'))
             + list((folder/'ms').glob('transport-*.jsonl')) for line in p.read_text().splitlines()]
    usage = {}
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [((c.get('response') or {}).get('usage') or {}).get(key) for c in calls]
        known = [v for v in values if type(v) is int and v >= 0]
        missing = len(values)-len(known)
        usage[key] = dict(known_sum=sum(known), missing_calls=missing,
                          total=sum(known) if values and not missing else None)
    return dict(observed_physical_calls=len(calls), usage=usage,
        scope='recorded provider calls only; absent logs or absent usage are not fabricated token counts')


def _dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def run_suite(jobs, routes, output, pool, worker, as_completed, parallel_games):
    """Runs in the parent process. Worker outputs never overwrite earlier attempts."""
    output = Path(output)
    started = time.monotonic()
    rows = {j['game_id']: dict(case_id=j['game_id'], job=copy.deepcopy(j), attempts=[]) for j in jobs}
    attempts = []

    def persist():
        cases = []
        for row in rows.values():
            available = row['attempts']
            selected = next((a for a in available if completed(a['result'])), None)
            cases.append(dict(row, first_attempt_completed=bool(available and completed(available[0]['result'])),
                completed_after_retry=selected is not None,
                selected_attempt=selected['attempt'] if selected else None,
                selected_folder=selected['folder'] if selected else None,
                selected_result=selected['result'] if selected else None))
        usage = {}
        unknown_attempts = sum(a['resources']['observed_physical_calls']==0 for a in attempts)
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            known = sum(a['resources']['usage'][key]['known_sum'] for a in attempts)
            missing = sum(a['resources']['usage'][key]['missing_calls'] for a in attempts)
            usage[key] = dict(known_sum=known, missing_calls=missing,
                              total=known if attempts and not missing and not unknown_attempts else None)
        summary = dict(cases_expected=len(jobs), cases_attempted=sum(bool(c['attempts']) for c in cases),
            first_attempt_completed=sum(c['first_attempt_completed'] for c in cases),
            completed_after_retry=sum(c['completed_after_retry'] for c in cases),
            recovered_on_retry=sum(c['selected_attempt']==2 for c in cases),
            failed_attempts=sum(not completed(a['result']) for a in attempts),
            retried_cases=sum(len(c['attempts'])==2 for c in cases), attempts_total=len(attempts),
            unresolved_cases=[c['case_id'] for c in cases if c['attempts'] and not c['completed_after_retry']],
            not_started=[c['case_id'] for c in cases if not c['attempts']],
            suite_elapsed_seconds=time.monotonic()-started)
        durations = [a['result'].get('elapsed_seconds') for a in attempts]
        known_durations = [d for d in durations if type(d) in (int,float) and d >= 0]
        missing_durations = len(durations)-len(known_durations)
        report = dict(policy=retry_policy(), summary=summary, cases=cases,
            resources=dict(observed_physical_calls=sum(a['resources']['observed_physical_calls'] for a in attempts),
                attempts_without_call_logs=unknown_attempts, usage=usage,
                attempt_elapsed_seconds_known_sum=sum(known_durations),
                attempts_missing_elapsed_seconds=missing_durations,
                attempt_elapsed_seconds_sum=sum(known_durations) if not missing_durations else None,
                note='Includes first and retry attempts; summed attempt durations are not parallel suite wall time'),
            interpretation='Engine completion is not scheduling success. Selected result is the first non-aborted attempt, never selected by reward. Missing task utility is not zero.')
        _dump(output/'attempts.json', attempts)
        _dump(output/'case_results.json', report)
        # Historical results.json is now explicitly an attempt list, with identity fields.
        _dump(output/'results.json', [dict(a['result'], case_id=a['case_id'], attempt=a['attempt'], attempt_folder=a['folder']) for a in attempts])
        return report

    persist()  # Write the full planned case list even if a process is interrupted.
    pending_retry = []
    for number, pending in ((1, jobs), (2, pending_retry)):
        if number == 2:
            order = {job['game_id']: i for i, job in enumerate(jobs)}
            pending.sort(key=lambda job: order[job['game_id']])
        for offset in range(0, len(pending), parallel_games):
            batch = pending[offset:offset+parallel_games]
            output_base = output if number==1 else output/'retries'
            futures = {}
            for original in batch:
                job = dict(original, suite_attempt=number, original_case_id=original['game_id'])
                futures[pool.submit(worker, job, copy.deepcopy(routes), output_base)] = job
            for future in as_completed(futures):
                job = futures[future]
                folder = output_base/job['game_id']
                try:
                    result = future.result()
                except Exception as exc:
                    # Configuration/source checks happen before scheduling. Unexpected
                    # worker exceptions still leave explicit missing results, not zeros.
                    result = dict(game_id=job['game_id'], engine_finished=False, healthy_transport=False,
                        error_type=type(exc).__name__, error=str(exc), metrics=None)
                    folder.mkdir(parents=True, exist_ok=True)
                    _dump(folder/'worker_error.json', result)
                record = dict(case_id=job['game_id'], attempt=number,
                    folder=str(folder.relative_to(output)), job=job, result=result, resources=resources(folder))
                rows[job['game_id']]['attempts'].append(record)
                attempts.append(record)
                if number==1 and not completed(result):
                    pending_retry.append(rows[job['game_id']]['job'])
                report = persist()
                print(f"case={job['game_id']} attempt={number} engine_completed={completed(result)} "
                      f"first_cases={report['summary']['cases_attempted']}/{len(jobs)}", flush=True)
    report = persist()
    _dump(output/'RUN_FINISHED.json', dict(formal_test=True, suite_finished=True,
        all_cases_attempted=report['summary']['cases_attempted']==len(jobs),
        engine_finished=report['summary']['completed_after_retry']==len(jobs),
        healthy_transport=all(a['result'].get('healthy_transport', False) for a in attempts),
        retry_policy=retry_policy(), **report['summary']))
    return report
