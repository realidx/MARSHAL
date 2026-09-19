"""Trace-only diagnostics. Counts preserve failed attempts even after recovery."""
from collections import Counter


def diagnose(trace, scenario, calls=(), replan=False):
    events = trace['events']
    resolutions = [e['data'] for e in events if e['type']=='resolution']
    rows = trace.get('final_state',{}).get('calendars')
    valid = {}
    for m in scenario['meetings']:
        positions = [[i for i,x in enumerate(row) if isinstance(x,dict) and x.get('meeting_id')==m['id']]
                     for row in rows] if rows else []
        selected = [positions[a] for a in m['participants']] if positions else []
        valid[m['id']] = bool(selected) and all(len(p)==1 and p==selected[0] for p in selected) and all(
            not positions[a] for a in range(len(positions)) if a not in m['participants'])
    blocked_intact = rows is not None and all(
        rows[a][s] == item for a,row in enumerate(scenario['calendars'])
        for s,item in enumerate(row) if item and item.get('blocked'))
    # Schema rejections are distinct from state-dependent failures. Keep reasons
    # so future native vocabulary changes remain auditable.
    reasons = {'format':Counter(), 'semantic':Counter()}
    for e in events:
        if e['type'] not in ('batch_rejected','invalid_tool_call'): continue
        d=e['data']; reason=d.get('conflict_description',d.get('reason','unknown'))
        schema = any(x in reason for x in ('missing required field','must be an integer','must be integers',
            'must be a non-empty string','is not an object',"missing integer 'to'"))
        reasons['format' if schema else 'semantic'][reason] += 1
    new_mismatch = sum(len({s for s in r.get('per_agent_slot',{}).values() if s is not None})>1 for r in resolutions)
    old_failures = {(r['round'],mid) for r in resolutions for mid in r.get('consistency_violated_meeting_ids',[])}
    result = dict(
        format_errors=dict(strict_envelope_calls=sum(not c.get('strict_envelope_valid',False) for c in calls),
                           native_schema_rejections=sum(reasons['format'].values())),
        counting_note='Rejection counts and blocked violation records may overlap; do not sum them. Retries remain counted.',
        semantic_invalid_actions=sum(reasons['semantic'].values()),
        blocked_state_violations=sum(len(r.get('blocked_slot_violations',[])) for r in resolutions),
        invalid_action_reasons={k:dict(v) for k,v in reasons.items()},
        coordination_failures=dict(new_meeting_slot_mismatches=new_mismatch,
                                   prior_meeting_inconsistency_rounds=len(old_failures)),
        final_state_available=rows is not None, final_valid_meetings=sum(valid.values()),
        final_meeting_validity=valid, blocked_items_preserved=blocked_intact,
        full_stream_completion=all(valid.values()) and blocked_intact,
        vps=None, vps_status='not_measured_reflection_disabled',
        paper_headline_score=None, disclosure_status='not_measured_no_log_disclosure_estimator',
        communication_observables={k:v for k,v in trace['metrics'].items()
            if k in ('total_dm_chars','total_dms_sent','total_cheap_talk_messages','total_cheap_talk_chars')})
    if replan:
        first=next((r for r in resolutions if r['meeting_id']==1),{})
        entered=bool(first.get('coordinated')) and set(first.get('per_agent_slot',{}).values())=={0}
        contact=any(e['type']=='dm_sent' and e['data'].get('meeting_id')==2 and e['data'].get('to_agent')==0 for e in events)
        second=next((r for r in resolutions if r['meeting_id']==2),{})
        moved=bool(rows) and all(isinstance(rows[a][1],dict) and rows[a][1].get('meeting_id')==1 for a in (0,1,2))
        result['replan_branch']=dict(entered=int(entered),contacted_old_participant=int(entered and contact),
            consistent_revision=int(entered and contact and second.get('coordinated',False) and moved and valid[1]),
            not_entered=int(not entered))
    return result


def summarize_run(root):
    """Offline audit; preserves raw traces/results and includes every case directory."""
    import json
    from pathlib import Path
    root=Path(root)
    cases=[]
    for path in sorted(root.rglob('scenario.json')):
        folder=path.parent
        reference=folder/'case_reference.json'
        if not reference.exists(): continue
        case=json.loads(reference.read_text())
        if 'scenario_seed' not in case: continue
        trace_path=folder/'trace.json'
        result_path=folder/'result.json'
        raw=json.loads(result_path.read_text()) if result_path.exists() else {}
        row=dict(case_id=case['id'],condition=case['structure_group'],scenario_seed=case['scenario_seed'],
                 healthy_transport=raw.get('healthy_transport'),engine_finished=raw.get('engine_finished',False))
        if trace_path.exists():
            trace=json.loads(trace_path.read_text())
            calls=[json.loads(line) for p in folder.glob('transport-*.jsonl') for line in p.read_text().splitlines()]
            row.update(diagnose(trace,case['scenario'],calls,case['family']=='replan'))
            row['realized_cost']=trace['metrics']['realized_cost']
            row['verified_excess_cost']=(row['realized_cost']-case['reference']['minimum_team_cost'] if row['full_stream_completion'] else None)
            row['truncated_calls']=sum(c['status']=='truncated' for c in calls)
            row['calls']=len(calls)
        else:
            row.update(full_stream_completion=None,diagnostic_status='missing_trace')
        cases.append(row)
    protocol=root/'execution_protocol.json'
    return dict(evaluation_claim='homogeneous_team_transfer',
        execution_protocol=json.loads(protocol.read_text()) if protocol.exists() else None,
        expected_cases=24,observed_cases=len(cases),cases=cases,
        replan_totals={k:sum(c.get('replan_branch',{}).get(k,0) for c in cases)
                       for k in ('entered','contacted_old_participant','consistent_revision','not_entered')},
        note='Pair by case_id across models within the same output budget/thinking protocol. Missing traces are not zero-utility outcomes.')


if __name__=='__main__':
    import argparse
    import json
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run_directory')
    args=p.parse_args()
    print(json.dumps(summarize_run(args.run_directory),indent=2))
