"""Offline audit of frozen BP99 CalBench artifacts; no model calls or writes to inputs."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = {
    'old': 'old-bp99-860494-biinv-v1-stream-868934',
    'new': 'new-bp99-866677-biinv-v1-stream-868933',
}
DIAG = {'old': 'old-bp99-v6s-biinv-v1-870332', 'new': 'new-bp99-v6s-biinv-v1-870333'}


def read(p):
    return json.loads(p.read_text())


def lines(p):
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def aggregate(rows):
    return dict(
        games=len(rows), success=sum(r['coordinated_success'] for r in rows),
        optimal=sum(r['successful_and_optimal'] for r in rows),
        meetings=sum(r['metrics']['meetings_scheduled'] for r in rows),
        headline=sum(r['metrics']['headline_score'] for r in rows)/len(rows),
        messages=sum(r['metrics']['total_dms_sent'] for r in rows),
        calls=sum(r['calls'] for r in rows),
        statuses=dict(sum((Counter(r['call_statuses']) for r in rows), Counter())),
        strict_envelope_failures=sum(r['strict_envelope_failures'] for r in rows),
        semantic_invalid=sum(r['diagnostics']['semantic_invalid_actions'] for r in rows),
        mismatched_rounds=sum(r['diagnostics']['coordination_failures']['new_meeting_slot_mismatches'] for r in rows),
        prior_inconsistency_rounds=sum(r['diagnostics']['coordination_failures']['prior_meeting_inconsistency_rounds'] for r in rows),
        all_healthy_transport=all(r['healthy_transport'] for r in rows),
        all_engine_finished=all(r['engine_finished'] for r in rows),
    )


def main():
    data, identities, detail, artifact_hashes = {}, {}, {}, {}
    out = {'scope': 'Four agents routed to the same BP export per run; not focal BP with Q0 partners.',
           'weight_verification': 'Recorded SHA256 identities compared; weight bytes unavailable locally.',
           'models': {}, 'checks': {}}
    for tag, name in RUNS.items():
        p = ROOT/'runs/calbench_soc'/name
        identity = read(p/'execution_identity.json')
        identities[tag] = identity
        rows = read(p/'games/results.json')
        data[tag] = {r['game_id']: r for r in rows}
        assert len(data[tag]) == 24
        assert (p/'EXIT_CODE').read_text().strip() == '0'
        assert read(p/'games/RUN_FINISHED.json')['engine_finished']
        export = ROOT/'new/bp99_checkpoint_results_20260921/exports'/f'{tag}_bp99'
        checks = {f: digest(export/f) == info['sha256'] for f, info in identity['files'].items() if (export/f).is_file()}
        recorded_weight = (export/'model.safetensors.sha256').read_text().split()[0]
        protocol = read(ROOT/'runs/diagnostic'/DIAG[tag]/'structure_v6/protocol.json')
        checks['weight_identity_across_calbench_diagnostic_export'] = recorded_weight == identity['files']['model.safetensors']['sha256'] == protocol['checkpoint_hash']
        assert all(checks.values()), checks
        detail[tag] = {}
        behavior = Counter()
        for case, row in data[tag].items():
            g = p/'games'/case
            assert read(g/'result.json') == row
            events = lines(g/'events.jsonl')
            assert events == read(g/'trace.json')['events']
            transports = [x for f in sorted(g.glob('transport-agent-*.jsonl')) for x in lines(f)]
            assert len(transports) == row['calls'], (tag, case)
            resolutions, rejected, compact = [], [], []
            for line, e in enumerate(events, 1):
                d = e['data']; kind = e['type']
                if kind == 'resolution':
                    resolutions.append({'line': line, **d})
                if kind == 'batch_rejected':
                    rejected.append({'line': line, **d})
                if kind in ('turn_end', 'decide_end'):
                    actions = d.get('tool_calls', [])
                    behavior[f"{d['phase']}_calls"] += 1
                    behavior[f"{d['phase']}_empty"] += not actions
                    for a in actions:
                        behavior['action_'+a['type']] += 1
                        if a['type'] == 'reschedule':
                            behavior['reschedule_same_slot'] += a.get('from_slot') == a.get('to_slot')
                    compact.append(dict(line=line, round=d['round'], turn=d['turn'], phase=d['phase'],
                                        agent=d['agent_id'], actions=actions, thinking=d.get('thinking', '')))
            assert len(resolutions) == 3
            detail[tag][case] = dict(resolutions=resolutions, rejected=rejected, calls=compact)
            for f in ['result.json', 'scenario.json', 'events.jsonl', 'trace.json']:
                artifact_hashes[str((g/f).relative_to(ROOT))] = digest(g/f)
        out['models'][tag] = dict(identity_checks=checks, overall=aggregate(rows),
            families={f: aggregate([r for r in rows if r['family'] == f]) for f in sorted({r['family'] for r in rows})},
            coordinated_by_round=[sum(x['resolutions'][i]['coordinated'] for x in detail[tag].values()) for i in range(3)],
            failed_resolution_types=dict(Counter(
                'null_calendar_outcome' if any(v is None for v in r['per_agent_slot'].values()) else 'different_slots'
                for x in detail[tag].values() for r in x['resolutions'] if not r['coordinated'])),
            behavior_event_counts=dict(behavior), routes=read(p/'routes.json'),
            caveat='Behavior event counts exclude retry outputs that lack turn_end/decide_end; rejection totals include retries.')
    out['checks']['same_case_ids'] = set(data['old']) == set(data['new'])
    for f in ['versions', 'scripts']:
        out['checks']['same_'+f] = identities['old'][f] == identities['new'][f]
    for f in ['runtime_environment.json', 'games/execution_protocol.json', 'games/frozen_manifest.json']:
        out['checks']['same_'+f] = read(ROOT/'runs/calbench_soc'/RUNS['old']/f) == read(ROOT/'runs/calbench_soc'/RUNS['new']/f)
    out['checks']['same_scenarios'] = all(
        read(ROOT/'runs/calbench_soc'/RUNS['old']/'games'/c/'scenario.json') ==
        read(ROOT/'runs/calbench_soc'/RUNS['new']/'games'/c/'scenario.json') for c in data['old'])
    pairs, outcomes = [], Counter()
    for c in sorted(data['old']):
        a, b = data['old'][c], data['new'][c]
        diff = b['metrics']['meetings_scheduled'] - a['metrics']['meetings_scheduled']
        outcomes['new_more' if diff > 0 else 'old_more' if diff < 0 else 'equal'] += 1
        pairs.append(dict(case=c, old_meetings=a['metrics']['meetings_scheduled'], new_meetings=b['metrics']['meetings_scheduled'],
                          old_headline=a['metrics']['headline_score'], new_headline=b['metrics']['headline_score'],
                          old_semantic_invalid=a['diagnostics']['semantic_invalid_actions'], new_semantic_invalid=b['diagnostics']['semantic_invalid_actions']))
    out['case_pairs'] = pairs
    out['meeting_count_pair_outcomes'] = dict(outcomes)
    # Compare identical full request bodies, within case and agent, excluding only routing model alias.
    matched = []
    for c in sorted(data['old']):
        for agent in range(4):
            by_tag = {}
            for tag in RUNS:
                p = ROOT/'runs/calbench_soc'/RUNS[tag]/'games'/c/f'transport-agent-{agent}.jsonl'
                grouped = defaultdict(list)
                for line, x in enumerate(lines(p), 1):
                    request = dict(x['request']); request.pop('model', None)
                    key = json.dumps(request, sort_keys=True, ensure_ascii=False)
                    grouped[key].append((line, x))
                by_tag[tag] = grouped
            for key in sorted(by_tag['old'].keys() & by_tag['new'].keys()):
                for (ol, o), (nl, n) in zip(by_tag['old'][key], by_tag['new'][key]):
                    matched.append(dict(case=c, agent=agent, old_line=ol, new_line=nl,
                                        same_output=o['normalized_text'] == n['normalized_text'],
                                        old_output=o['normalized_text'], new_output=n['normalized_text']))
    out['identical_request_comparisons'] = dict(count=len(matched), identical_outputs=sum(x['same_output'] for x in matched),
        interpretation='Selection-conditioned natural overlap, not randomized fixed-state evaluation; exact request equality includes history and decoding.')
    (OUT/'summary.json').write_text(json.dumps(out, indent=2, ensure_ascii=False)+'\n')
    (OUT/'artifact_hashes.json').write_text(json.dumps(artifact_hashes, indent=2)+'\n')
    (OUT/'same_input_outputs.json').write_text(json.dumps(matched, indent=2, ensure_ascii=False)+'\n')
    (OUT/'trace_extracts.json').write_text(json.dumps(detail, indent=2, ensure_ascii=False)+'\n')
    md = ['# CalBench BP99: all 24 paired outcomes', '', '| Case | Old meetings | New meetings | Old score | New score | Old/new semantic invalid |', '|---|---:|---:|---:|---:|---:|']
    for r in pairs:
        md.append(f"| {r['case']} | {r['old_meetings']} | {r['new_meetings']} | {r['old_headline']:.6f} | {r['new_headline']:.6f} | {r['old_semantic_invalid']}/{r['new_semantic_invalid']} |")
    (OUT/'case_comparison.md').write_text('\n'.join(md)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('case_pairs','models')},indent=2))
    for tag, v in out['models'].items():
        print(tag, json.dumps(v['overall']), json.dumps(v['behavior_event_counts']))


if __name__ == '__main__':
    main()
