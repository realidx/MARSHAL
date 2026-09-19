"""Native CalBench evaluation runner with explicit OpenAI-compatible transport."""
import argparse
import copy
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'third_party/calbench'


def verify_source():
    manifest = json.loads(Path(__file__).with_name('calbench_source.json').read_text())
    for name, expected in manifest['files'].items():
        path = SOURCE / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'CalBench source mismatch: {name}')
    sys.path[:0] = [str(SOURCE), str(SOURCE / 'vendor/a2a-engine')]
    return manifest['archive_sha256']


def load_routes(path):
    config = json.loads(Path(path).read_text())
    all_routes = [config['endpoints'][alias] for alias in ('focal', 'q0')] + config.get('equivalent_replicas', [])
    for route in all_routes:
        url = urlparse(route['base_url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('Invalid endpoint URL')
        if config.get('local_only', True) and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Nonlocal endpoint requires local_only=false')
        if not route['model']:
            raise ValueError('Missing model')
    return config


def separate_reasoning(text):
    """Normalize a leading Qwen reasoning block before native action parsing.

    Raw provider output remains in transport logs. An unfinished reasoning
    block contains no final answer and must never be repaired into an action.
    """
    stripped = (text or '').lstrip()
    if not stripped.startswith('<think>'):
        return text or '', None, 'plain'
    end = stripped.find('</think>', len('<think>'))
    if end < 0:
        return '', stripped[len('<think>'):], 'unfinished_reasoning'
    return stripped[end+len('</think>'):].lstrip(), stripped[len('<think>'):end], 'separated_reasoning'


class InfrastructureFailure(BaseException):
    """Bypass the native client's broad Exception-to-empty-action fallback."""


class Transport:
    """Only transport is adapted; native prompts, parsing and rules remain intact."""
    def __init__(self, route, config, output, seed, agent_id):
        self.route, self.config, self.output = route, config, output
        self.seed, self.agent_id, self.index = seed, agent_id, 0

    def streaming_with_retry(self, messages, **kwargs):
        index = self.index
        self.index += 1
        started = time.monotonic()
        seed = int(hashlib.sha256(f'{self.seed}:{self.agent_id}:{index}'.encode()).hexdigest()[:8], 16)
        body = dict(model=self.route['model'], messages=messages,
                    temperature=self.config.get('temperature', 0.0),
                    max_tokens=kwargs.get('max_tokens') or self.config.get('max_tokens', 768), seed=seed)
        if 'chat_template_kwargs' in self.config:
            body['chat_template_kwargs'] = self.config['chat_template_kwargs']
        record = dict(agent_id=self.agent_id, call_index=index, base_url=self.route['base_url'], request=body)
        try:
            key = os.environ.get(self.route.get('api_key_env', ''), 'EMPTY')
            request = Request(self.route['base_url'].rstrip('/') + '/chat/completions',
                              data=json.dumps(body).encode(),
                              headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
            with urlopen(request, timeout=self.config.get('timeout_seconds', 120)) as response:
                raw = json.load(response)
            record['response'] = raw
            choice = raw['choices'][0]
            raw_text = choice['message']['content']
            text, reasoning, normalization = separate_reasoning(raw_text)
            record['output_normalization'] = normalization
            record['normalized_text'] = text
            record['status'] = 'truncated' if choice.get('finish_reason') == 'length' else 'ok'
            try:
                parsed = json.loads(text)
                record['strict_envelope_valid'] = (isinstance(parsed, dict)
                    and set(parsed) == {'thinking', 'actions'}
                    and isinstance(parsed['thinking'], str)
                    and isinstance(parsed['actions'], list)
                    and all(isinstance(a, dict) for a in parsed['actions']))
            except (ValueError, TypeError):
                record['strict_envelope_valid'] = False
            usage = raw.get('usage', {})
            return dict(text=text, reasoning=reasoning, duration_s=time.monotonic()-started,
                        finish_reason=choice.get('finish_reason'), _raw_response=raw,
                        **{k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
        except Exception as exc:
            record['status'] = 'infrastructure_failure'
            record['error_type'] = type(exc).__name__
            raise InfrastructureFailure(f'Agent {self.agent_id}: {type(exc).__name__}: {exc}') from exc
        finally:
            record['elapsed_seconds'] = time.monotonic() - started
            with (self.output / f'transport-agent-{self.agent_id}.jsonl').open('a') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
            print(f"agent={self.agent_id} call={index} status={record['status']} seconds={record['elapsed_seconds']:.1f}", flush=True)


def run_one(job, routes, output):
    routes = copy.deepcopy(routes)
    if routes.get('equivalent_replicas'):
        route = routes['equivalent_replicas'][job['focal_seat'] % len(routes['equivalent_replicas'])]
        routes['endpoints'] = {alias: dict(route) for alias in ('focal', 'q0')}
    source_hash = verify_source()
    from calendar_game.game import CalendarGame
    import calendar_game.game as game_module
    from calendar_game.scenario import generate_scenario
    from a2a_engine import EventLog

    folder = Path(output) / job['game_id']
    folder.mkdir(parents=True, exist_ok=False)
    cfg = dict(game_name='calendar', seed=job['seed'], num_agents=4, num_slots=8,
               num_meetings=2, num_participants=3, density=0.5, pref_level=3,
               errand_cost_level=3, meeting_cost_level=1, max_turns_per_round=2,
               decision_retries=1, enable_fallback=False, enable_reflection=False,
               communication_protocol='dm', agents=[dict(type='llm', model='q0', agent_id=i) for i in range(4)])
    if not job.get('case') and not job.get('formal_case') and not job.get('stream_case'):
        cfg['agents'][job['focal_seat']]['model'] = 'focal'
    # Two overlapping participant sets exercise native multi-meeting transitions.
    scenario = generate_scenario(job['seed'], 4, 8, .5, 3, 2,
                                 participant_lists=[[0, 1, 2], [1, 2, 3]], errand_cost_level=3)
    case=None
    if job.get('case'):
        from examples.final_evaluation.calbench_development_cases import build_case
        case=build_case(job['case'])
        scenario=case['scenario']
        cfg.update(num_meetings=1,max_turns_per_round=4,errand_cost_level=8)
        (folder/'case_reference.json').write_text(json.dumps(case,indent=2)+'\n')
    if job.get('formal_case') or job.get('stream_case'):
        if job.get('stream_case'):
            from examples.final_evaluation.calbench_stream import load_frozen
        else:
            from examples.final_evaluation.calbench_formal import load_frozen
        frozen, cases = load_frozen()
        case = next(c for c in cases if c['id'] == job.get('formal_case', job.get('stream_case')))
        scenario = copy.deepcopy(case['scenario'])
        cfg.update(frozen['config'], seed=scenario['seed'])
        (folder/'case_reference.json').write_text(json.dumps(case,indent=2)+'\n')
    (folder / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n')
    (folder / 'manifest.json').write_text(json.dumps(dict(stage='formal' if job.get('formal_case') or job.get('stream_case') else 'development', formal_test=bool(job.get('formal_case') or job.get('stream_case')),
        source_hash=source_hash, config=cfg, routes=routes, job=job), indent=2) + '\n')
    original = game_module.make_llm_client
    def factory(spec):
        aid = spec['agent_id']
        return Transport(routes['endpoints'][spec['model']], routes, folder, job['seed'], aid)
    game_module.make_llm_client = factory
    class LiveEvents(EventLog):
        def append(self, type, data=None, **extra):
            event = super().append(type, data, **extra)
            with (folder / 'events.jsonl').open('a') as f:
                f.write(event.model_dump_json() + '\n')
            if type in ('round_start', 'resolution', 'game_end', 'batch_rejected'):
                print(job['game_id'], type, (data or {}).get('round'), flush=True)
            return event
    started = time.monotonic()
    try:
        game = CalendarGame(cfg)
        game.events = LiveEvents()
        trace = game.run_with_scenario(scenario)
        trace.ended_at = datetime.now(timezone.utc)
        (folder / 'trace.json').write_text(trace.model_dump_json(indent=2))
        calls = [json.loads(line) for p in folder.glob('transport-*.jsonl') for line in p.read_text().splitlines()]
        counts = Counter(c['status'] for c in calls)
        events = Counter(e.type for e in trace.events)
        result = dict(game_id=job['game_id'], engine_finished=True, calls=len(calls),
                      elapsed_seconds=time.monotonic()-started, call_statuses=dict(counts),
                      strict_envelope_failures=sum(not c.get('strict_envelope_valid', False) for c in calls),
                      event_counts=dict(events), metrics=json.loads(trace.model_dump_json())['metrics'],
                      healthy_transport=bool(calls) and counts['infrastructure_failure']==0,
                      all_generations_untruncated=counts['truncated']==0)
        if case:
            result['reference' if job.get('formal_case') or job.get('stream_case') else 'development_reference']=case['reference']
            result['native_oracle_scores_valid']=not bool(case['scenario'].get('prior_meetings'))
            result['verified_reference_excess_cost']=(trace.metrics['realized_cost']-case['reference']['minimum_team_cost']
                if trace.metrics['meetings_scheduled']==len(scenario['meetings']) else None)
        if job.get('formal_case'):
            succeeded = trace.metrics['meetings_scheduled']==1
            result.update(formal_test=True,family=case['family'],structure_group=case['structure_group'],
                          coordinated_success=succeeded,
                          successful_and_optimal=succeeded and trace.metrics['realized_cost']==case['reference']['minimum_team_cost'])
        if job.get('stream_case'):
            n = len(scenario['meetings'])
            from examples.final_evaluation.calbench_stream_metrics import diagnose
            diagnostics = diagnose(json.loads(trace.model_dump_json()),scenario,calls,case['family']=='replan')
            result['diagnostics'] = diagnostics
            complete = diagnostics['full_stream_completion']
            result['verified_reference_excess_cost'] = (trace.metrics['realized_cost']-case['reference']['minimum_team_cost'] if complete else None)
            result.update(formal_test=True, suite='calbench_stream_v1', family=case['family'],
                structure_group=case['structure_group'], scenario_seed=case['scenario_seed'],
                cost_regime=case['cost_regime'], meetings_requested=n,
                meeting_completion_rate=diagnostics['final_valid_meetings']/n,
                coordinated_success=complete,
                successful_and_optimal=complete and trace.metrics['realized_cost']==case['reference']['minimum_team_cost'],
                oracle_scope='Full-stream hindsight; not an online-policy oracle')
        (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    except InfrastructureFailure as exc:
        result=dict(game_id=job['game_id'],formal_test=bool(job.get('formal_case') or job.get('stream_case')),engine_finished=False,
                    healthy_transport=False,error_type='InfrastructureFailure',error=str(exc),
                    elapsed_seconds=time.monotonic()-started,metrics=None)
        (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    finally:
        game_module.make_llm_client = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routes', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--games', type=int, default=2)
    parser.add_argument('--parallel-games', type=int, default=2)
    parser.add_argument('--seed', type=int, default=2026091800)
    parser.add_argument('--suite',choices=['smoke','structures','formal','stream'],default='smoke')
    args = parser.parse_args()
    if not 1 <= args.games <= 4 or args.parallel_games < 1:
        parser.error('Development run: games=1..4, parallel-games>=1')
    routes = load_routes(args.routes)
    verify_source()
    args.output.mkdir(parents=True, exist_ok=False)
    jobs = [dict(game_id=f'dev_{i}', seed=args.seed, focal_seat=i) for i in range(args.games)]
    if args.suite=='structures':
        from examples.final_evaluation.calbench_development_cases import validate_cases
        validation=validate_cases()
        (args.output/'structure_validation.json').write_text(json.dumps(validation,indent=2)+'\n')
        jobs=[dict(game_id=name,case=name,seed=args.seed,focal_seat=i) for i,name in enumerate(('cost_conflict','prior_commitment'))]
    if args.suite in ('formal','stream'):
        if args.suite == 'stream':
            from examples.final_evaluation.calbench_stream import load_frozen, FROZEN
        else:
            from examples.final_evaluation.calbench_formal import load_frozen, FROZEN
        frozen, cases = load_frozen()
        if routes.get('temperature')!=frozen['sampling']['temperature']:
            raise ValueError('Formal temperature differs from frozen protocol')
        budget=routes.get('max_tokens')
        if budget not in (768,4096):
            raise ValueError('Supported formal output budgets: 768 or 4096')
        if budget!=frozen['sampling']['max_tokens'] and routes.get('execution_protocol')!=f'reasoning-separated-v2-tokens-{budget}':
            raise ValueError('Output budget override requires an explicit execution protocol')
        (args.output/'execution_protocol.json').write_text(json.dumps(dict(
            protocol=routes.get('execution_protocol','reasoning-separated-v2-tokens-768'),
            result_role=('primary' if budget==frozen['sampling']['max_tokens'] else 'diagnostic_budget'),
            max_tokens=budget,original_frozen_max_tokens=frozen['sampling']['max_tokens'],
            temperature=routes['temperature'],prompt_changed=False,
            chat_template_kwargs=routes.get('chat_template_kwargs',{}),
            model_chat_template_changed=bool(routes.get('chat_template_kwargs')),
            reasoning_normalization='separate leading think block; preserve raw output'),indent=2)+'\n')
        jobs=[dict(game_id=c['id'],seed=c['scenario']['seed'],focal_seat=i,
                   **{('stream_case' if args.suite=='stream' else 'formal_case'):c['id']}) for i,c in enumerate(cases)]
        (args.output/'frozen_manifest.json').write_bytes((FROZEN/'manifest.json').read_bytes())
    results = []
    with ProcessPoolExecutor(max_workers=args.parallel_games, mp_context=mp.get_context('spawn')) as pool:
        # Submit one bounded batch at a time: a dead server must not consume
        # the rest of the frozen suite as fabricated model failures.
        for offset in range(0,len(jobs),args.parallel_games):
            pending=[pool.submit(run_one,job,routes,args.output) for job in jobs[offset:offset+args.parallel_games]]
            batch=[]
            for future in as_completed(pending):
                result=future.result();results.append(result);batch.append(result)
                (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
                print(f'Finished {len(results)}/{len(jobs)}',flush=True)
            if any(not r['healthy_transport'] for r in batch):
                (args.output/'RUN_FAILED.json').write_text(json.dumps(dict(reason='infrastructure_failure',
                    attempted=[r['game_id'] for r in results],not_started=[j['game_id'] for j in jobs[offset+args.parallel_games:]]),indent=2)+'\n')
                raise RuntimeError('Infrastructure failure; remaining games were not started')
    (args.output / 'RUN_FINISHED.json').write_text(json.dumps(dict(formal_test=args.suite in ('formal','stream'),
        engine_finished=True, healthy_transport=all(r['healthy_transport'] for r in results))) + '\n')


if __name__ == '__main__':
    main()
