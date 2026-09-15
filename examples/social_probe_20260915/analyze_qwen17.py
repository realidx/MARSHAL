"""Local-only audit of the pinned 1.7B probe; never repairs model answers."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from training.b_sft.social_bp_training import reward
from training.b_sft.build_b_response_bridges import verify_task
from examples.social_probe_20260915 import run_remote


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_present(message):
    return bool((message.get('content') or '').strip())


def natural_text(message):
    return text_present(message) and not message['content'].lstrip().startswith('<tool_call>')


def summarize(samples):
    groups = defaultdict(list)
    for s in samples:
        groups[s['task_id']].append(s)
    assert all(len(ss) == 8 for ss in groups.values())
    return dict(responses=len(samples), correct=sum(s['score']['correct'] for s in samples),
        statuses=dict(Counter(s['score']['status'] for s in samples)),
        with_content=sum(text_present(s['raw_message']) for s in samples),
        natural_text=sum(natural_text(s['raw_message']) for s in samples),
        reasoning_content=sum(bool(s['raw_message'].get('reasoning_content')) for s in samples),
        any_explanation=sum(natural_text(s['raw_message']) or bool(s['raw_message'].get('reasoning_content')) for s in samples),
        truncated_in_thinking=sum(s.get('finish_reason') == 'length' and bool(s['raw_message'].get('reasoning_content'))
                                 and s['raw_message'].get('content') is None and not s['raw_message'].get('tool_calls') for s in samples),
        fullset=sum(s['score'].get('predicted_full_set', False) for s in samples),
        fullset_correct=sum(s['score'].get('predicted_full_set', False) and s['score']['correct'] for s in samples),
        set_only_correct=sum(s['score'].get('set_exact', False) and not s['score']['correct'] for s in samples),
        groups=dict(Counter('all_zero' if not any(s['score']['correct'] for s in ss) else
                            'all_one' if all(s['score']['correct'] for s in ss) else 'mixed'
                            for ss in groups.values())),
        output_tokens=sum(s['usage']['completion_tokens'] for s in samples),
        mean_output_tokens=statistics.mean(s['usage']['completion_tokens'] for s in samples))


def main(run, allow_partial=False):
    probe = run/'probe'; bundle = probe/'bundle'; out = run/'local_analysis'; out.mkdir(exist_ok=True)
    manifest, _, resets = run_remote.verify(bundle)
    selection = json.loads((bundle/'selection_manifest.json').read_text())
    for name, digest in selection['source_sha256'].items():
        assert sha(ROOT/name) == digest, name
    l0_manifest = json.loads((bundle/'l0_probe_manifest.json').read_text())
    assert sha(ROOT/'examples/social_bp/b_l0_isolated_v1/tasks.jsonl') == l0_manifest['tasks_sha256']
    report = dict(run=str(run), bundle_verified=True, source_hashes_verified=True, stages={})
    tasks_by_stage = {}; label_checks = []; all_seeds = set()
    for stage, pack in [('bp','data'), ('bridges','b_response_bridges_v1'), ('l0','b_l0_isolated_v1')]:
        tasks = {t['id']:t for t in read(ROOT/f'examples/social_bp/{pack}/tasks.jsonl')}
        requests = read(bundle/f'{stage}_requests.jsonl'); allowed = {r['task_id'] for r in requests}
        source = ROOT/f'examples/social_bp/{pack}/requests.jsonl'
        if stage == 'bp':
            baseline = ROOT/'examples/bp_pilot_probe_nus/bundle'
            originals = read(baseline/'train_requests.jsonl')+read(baseline/'validation_requests.jsonl')
        else:
            originals = read(source)
        originals = {r['task_id']:r for r in originals}
        assert all(r['request'] == originals[r['task_id']]['request'] for r in requests)
        config = json.loads((probe/stage/'run_config.json').read_text())
        assert config['requests_sha256'] == sha(bundle/f'{stage}_requests.jsonl')
        assert config['script_sha256'] == sha(bundle/'remote_bp_probe.py')
        assert config['group_size'] == 8 and not config['preflight']
        samples = read(probe/stage/'samples.jsonl'); seen = set(); cells = defaultdict(list)
        for s in samples:
            tid, idx = s['task_id'], s['sample_index']
            assert tid in allowed and 0 <= idx < 8 and (tid,idx) not in seen
            assert s['seed'] not in all_seeds
            seen.add((tid,idx)); all_seeds.add(s['seed'])
            t = tasks[tid]; assert t['split'] in ('train', 'validation')
            s['score'] = reward(t,s); assert s['score']['reward'] is not None
            keys = ['all', 'task/'+t['task'], 'split/'+t['split'], 'skill/'+t['pool'],
                    t['task']+'/'+t['split']]
            if 'b_lesson_level' in t: keys.append('level/'+str(t['b_lesson_level']))
            if t['pool'] == 'information': keys.append('information/'+str(t.get('information_positive', False)))
            for key in keys: cells[key].append(s)
        assert len(seen) == len(allowed)*8
        stage_report = dict(cells={k:summarize(ss) for k,ss in cells.items()}, per_question=[])
        for tid in sorted(allowed):
            t = tasks[tid]; ss = [s for s in samples if s['task_id'] == tid]
            stage_report['per_question'].append(dict(task_id=tid, split=t['split'], kind=t['task'],
                pool=t['pool'], level=t.get('b_lesson_level'), gold=t['teacher'].get('gold'),
                acceptable_actions=t['teacher'].get('acceptable_actions'), **summarize(ss)))
            if stage != 'bp': label_checks.append(verify_task(t))
        report['stages'][stage] = stage_report
        tasks_by_stage[stage] = {tid:tasks[tid] for tid in allowed}
        (out/f'{stage}_scored.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in samples))
    save(out/'label_verification.json', label_checks)
    report['new_B_labels_independently_rechecked'] = len(label_checks)

    games = [json.loads(p.read_text()) for p in sorted((probe/'selfplay').glob('group-*-rollout-*.json'))]
    assert len(games) == 48 or (allow_partial and 0 < len(games) < 48)
    by_group = defaultdict(list); invalid = []; calls = []
    with tempfile.TemporaryDirectory(prefix='qwen17-replay-') as temp:
        runtime = run_remote.load_runtime(bundle, Path(temp))
        for g in games:
            assert runtime.verify_episode(g)
            by_group[g['group_id']].append(g)
            for c in g['calls']:
                calls.append(c); response = c['response']; raw = response['raw_message']; tool_calls = raw.get('tool_calls') or []
                decoded = None
                if len(tool_calls) == 1:
                    f = tool_calls[0]['function']; arguments = f['arguments']
                    if isinstance(arguments, str):
                        try: arguments = json.loads(arguments)
                        except ValueError: arguments = None
                    decoded = runtime.readable.decode_call(c['observation'], f['name'], arguments)
                assert decoded == response['action']
                assert c['valid'] == (response['finish_reason'] != 'length' and decoded in c['observation']['legal_actions'])
                if not c['valid']:
                    invalid.append(dict(group_id=g['group_id'], rollout_index=g['rollout_index'],
                        player=c['player'], decision=c['decision'], attempt=c['attempt'],
                        raw_message=raw, failure=c['failure'], observation=c['observation'],
                        tools=response['request_options']['tools']))
    assert set(by_group) == {r['group_id'] for r in resets}
    group_rows = []; categories = Counter()
    for gid, gs in by_group.items():
        indices = {g['rollout_index'] for g in gs}
        assert len(indices) == len(gs) and indices <= set(range(4))
        assert indices == set(range(4)) or allow_partial
        gs.sort(key=lambda g:g['rollout_index'])
        for player in range(len(gs[0]['players'])):
            utility = [g['players'][player]['terminal_reward'] for g in gs]
            combined = [g['players'][player]['combined_reward'] for g in gs]
            category = ('incomplete' if len(gs) != 4 or None in utility else 'utility_varies' if len(set(utility))>1
                        else 'protocol_only' if len(set(combined))>1 else 'constant')
            categories[category] += 1
            group_rows.append(dict(group_id=gid, player=player, utility=utility, combined=combined, category=category))
    # Text containing only malformed tool markup is not a reasoning explanation.
    natural = [c for c in calls if natural_text(c['response']['raw_message'])]
    first = [c for c in calls if c['attempt'] == 0]
    report['selfplay'] = dict(games=len(games), statuses=dict(Counter(g['status'] for g in games)),
        calls=len(calls), first_calls=len(first), first_valid=sum(c['valid'] for c in first),
        retries=sum(c['attempt']>0 for c in calls), retry_valid=sum(c['valid'] for c in calls if c['attempt']>0),
        invalid_calls=len(invalid), truncated=sum(c['response']['finish_reason']=='length' for c in calls),
        with_content=sum(text_present(c['response']['raw_message']) for c in calls),
        natural_text_calls=len(natural), natural_text_first=sum(c['attempt']==0 for c in natural),
        raw_reasoning_content_nonempty=sum(bool(c['response']['raw_message'].get('reasoning_content')) for c in calls),
        any_explanation=sum(natural_text(c['response']['raw_message']) or bool(c['response']['raw_message'].get('reasoning_content')) for c in calls),
        all_replays_verified=True, raw_tool_decoding_verified=True,
        positions=dict(categories), position_groups=group_rows,
        complete_four_game_groups=sum(len(gs)==4 and all(g['status']=='terminal' for g in gs) for gs in by_group.values()),
        valid_actions=dict(Counter(c['response']['action'].get('action',c['response']['action'].get('response')) for c in calls if c['valid'])),
        completion_tokens=sum(c['response']['usage']['completion_tokens'] for c in calls),
        prompt_tokens=sum(c['response']['usage']['prompt_tokens'] for c in calls))
    save(out/'selfplay_invalid_calls.json', invalid)
    save(out/'selfplay_natural_text.json', [dict(player=c['player'],decision=c['decision'],attempt=c['attempt'],
        content=c['response']['raw_message']['content']) for c in natural])
    performance = {}
    for directory in sorted(probe.glob('performance-*')):
        records = read(directory/'samples.jsonl') if (directory/'samples.jsonl').exists() else []
        gpus = defaultdict(list); ports = defaultdict(list)
        for record in records:
            for gpu in csv.DictReader(io.StringIO(record['gpu'].get('stdout','')), skipinitialspace=True):
                gpus[gpu['index']].append(gpu)
            for port,s in record['servers'].items():
                if 'values' in s: ports[port].append(s['values'])
        performance[directory.name] = dict(samples=len(records), gpus={
            gpu:{k:statistics.mean(float(v[k].split()[0]) for v in vs)
                 for k in ('utilization.gpu [%]', 'power.draw [W]', 'memory.used [MiB]')}
            for gpu,vs in gpus.items()}, ports={port:dict(
                running_mean=statistics.mean(v['vllm:num_requests_running'] for v in vs),
                running_max=max(v['vllm:num_requests_running'] for v in vs),
                waiting_max=max(v['vllm:num_requests_waiting'] for v in vs),
                preemption_delta=vs[-1].get('vllm:num_preemptions_total',0)-vs[0].get('vllm:num_preemptions_total',0))
                for port,vs in ports.items()})
    report['performance'] = performance
    # Verify that independent seeds reached the engine, not just the HTTP client log.
    logged_seeds = Counter()
    for path in probe.glob('server-?.log'):
        for line in path.read_text().splitlines():
            if 'params: SamplingParams(' in line:
                params = line.split('params: SamplingParams(', 1)[1]
                value = re.search(r'seed=([^,]+)', params).group(1)
                if value != 'None': logged_seeds[int(value)] += 1
    expected_seeds = Counter(all_seeds)
    expected_seeds.update(c['seed'] for c in calls)
    if allow_partial:
        assert not (expected_seeds-logged_seeds), 'A saved response seed is missing from engine logs'
    else:
        assert logged_seeds == expected_seeds
    report['engine_seeds_verified'] = sum(expected_seeds.values())
    report['extra_engine_requests_not_in_finished_records'] = sum((logged_seeds-expected_seeds).values())
    completion_path = probe/'COMPLETE.json'
    if not allow_partial: assert completion_path.exists()
    report['completion'] = json.loads(completion_path.read_text()) if completion_path.exists() else None
    report['download_snapshot_partial'] = not completion_path.exists() or len(games) != 48
    report['selfplay']['unfinished_record_files'] = [p.name for p in sorted((probe/'selfplay').glob('*.calls.jsonl'))
        if not p.with_name(p.name.replace('.calls.jsonl','.json')).exists()]
    report['startup'] = json.loads((probe/'startup.json').read_text())
    save(out/'analysis_summary.json', report)
    print(json.dumps(dict(stages={k:v['cells']['all'] for k,v in report['stages'].items()},
        selfplay={k:v for k,v in report['selfplay'].items() if k!='position_groups'},
        independent_B_checks=len(label_checks)),indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__); cli.add_argument('--run', type=Path, required=True)
    cli.add_argument('--allow-partial', action='store_true', help='Audit finished records in an incomplete downloaded snapshot')
    args = cli.parse_args()
    main(args.run.resolve(), allow_partial=args.allow_partial)
