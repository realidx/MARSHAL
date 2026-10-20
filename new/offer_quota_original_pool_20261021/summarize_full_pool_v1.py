"""Aggregate all original parents; missing results stay explicitly missing."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

TOL=1e-8


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def write(p,value):
    with p.open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
        f.write('\n')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def initial_decisions(metrics):
    rows=[r for r in metrics['rows'] if r['root_index']==0]
    result=dict(value=0.,best_query_gap=0.,mean_offer_regret=0.,suboptimal_offer_fraction=0.,
                action_value_span=0.,query_probability=0.,cells=[])
    assert abs(sum(r['reach_mass'] for r in rows)-1)<TOL
    for row in rows:
        offers=[q for a,q in zip(row['actions'],row['Q']) if a.get('action')=='OFFER']
        assert offers
        w=row['reach_mass'];best=max(row['Q'])
        result['value']+=w*best
        result['best_query_gap']+=w*row['first_query_gap']
        result['mean_offer_regret']+=w*sum(best-q for q in offers)/len(offers)
        result['suboptimal_offer_fraction']+=w*sum(q<best-TOL for q in offers)/len(offers)
        result['action_value_span']+=w*(best-min(row['Q']))
        result['query_probability']+=w*row['query_probability']
        result['cells'].append(dict(own=row['own'],mass=w,
            optimal_actions=sorted(canonical(a) for a,q in zip(row['actions'],row['Q']) if q>=best-TOL),
            offer_values=[dict(action=a,Q=q,regret=best-q) for a,q in zip(row['actions'],row['Q']) if a.get('action')=='OFFER']))
    return result


def aggregate(pairs):
    complete=[r for r in pairs if r['complete']]
    if not complete:
        return dict(requested=len(pairs),paired_complete=0,missing=[r['parent_id'] for r in pairs])
    result=dict(requested=len(pairs),paired_complete=len(complete),
                missing=[r['parent_id'] for r in pairs if not r['complete']])
    for side in ('baseline','quota'):
        result[side]=dict(
            parents_with_positive_query_access=sum(r[side]['summary']['player_uniform_query_access']>TOL for r in complete),
            parents_with_strict_query_first_proposal=sum(r[side]['summary']['player_uniform_strict_query_mass']>TOL for r in complete),
            mean_player_uniform_query_access=sum(r[side]['summary']['player_uniform_query_access'] for r in complete)/len(complete),
            mean_player_uniform_strict_query_mass=sum(r[side]['summary']['player_uniform_strict_query_mass'] for r in complete)/len(complete),
            mean_player_uniform_tied_query_mass=sum(r[side]['summary']['player_uniform_tied_query_mass'] for r in complete)/len(complete),
            mean_player_uniform_inferior_query_mass=sum(r[side]['summary']['player_uniform_inferior_query_mass'] for r in complete)/len(complete),
            mean_initial_offer_regret=sum(r[side]['initial']['mean_offer_regret'] for r in complete)/len(complete),
            mean_initial_suboptimal_offer_fraction=sum(r[side]['initial']['suboptimal_offer_fraction'] for r in complete)/len(complete),
            mean_initial_action_value_span=sum(r[side]['initial']['action_value_span'] for r in complete)/len(complete),
            parents_with_observed_real_acquisition_witness=sum(r[side]['has_real_acquisition_witness'] for r in complete),
            parents_with_measured_positive_answer_value=sum((r[side]['summary']['max_measured_same_query_answer_value'] or 0)>TOL for r in complete))
    result['changes']={}
    for key in ('player_uniform_query_access','player_uniform_strict_query_mass'):
        delta=[r['quota']['summary'][key]-r['baseline']['summary'][key] for r in complete]
        result['changes'][key]=dict(increase=sum(d>TOL for d in delta),decrease=sum(d < -TOL for d in delta),unchanged=sum(abs(d)<=TOL for d in delta))
    for key in ('mean_offer_regret','value','action_value_span','suboptimal_offer_fraction'):
        delta=[r['quota']['initial'][key]-r['baseline']['initial'][key] for r in complete]
        result['changes']['initial_'+key]=dict(increase=sum(d>TOL for d in delta),decrease=sum(d < -TOL for d in delta),unchanged=sum(abs(d)<=TOL for d in delta))
    result['changed_initial_optimal_action_sets']=sum(r['changed_initial_optimal_cells']>0 for r in complete)
    result['observed_real_acquisition_witness_changes']=dict(
        newly_present=sum(not r['baseline']['has_real_acquisition_witness'] and r['quota']['has_real_acquisition_witness'] for r in complete),
        no_longer_present=sum(r['baseline']['has_real_acquisition_witness'] and not r['quota']['has_real_acquisition_witness'] for r in complete))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--retry-run',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    run=args.run
    if not (run/'COMPLETE.json').exists():
        raise ValueError('Fixed full-pool run must finish before final aggregation')
    summary=json.loads((run/'summary.json').read_text())
    parents={p['id']:p for p in json.loads((run/'parents.json').read_text())}
    files=[run/'summary.json',run/'COMPLETE.json',run/'parents.json',run/'pipeline_snapshot.json']
    retries={}
    if args.retry_run:
        assert (args.retry_run/'COMPLETE.json').exists()
        retry_summary=json.loads((args.retry_run/'summary.json').read_text())
        retries={r['parent_id']:r for r in retry_summary['results']}
        files.extend(args.retry_run/n for n in ('summary.json','COMPLETE.json','pipeline_snapshot.json'))
    pairs=[]
    for status in summary['results']:
        pid=status['parent_id']
        result_dir=run
        original_status=status
        if status['status']=='missing-result' and pid in retries and retries[pid]['status'].startswith('complete-'):
            status=retries[pid]
            result_dir=args.retry_run
        row=dict(parent_id=pid,split=status['split'],players=status['players'],
            binding=max(Counter(parents[pid]['raw']['game']['round_robin']).values())>1,
            complete=status['status'].startswith('complete-'),status=status['status'],
            selected_result_directory=str(result_dir),original_attempt_status=original_status['status'])
        if not row['complete']:
            row.update(failed_phase=status.get('failed_phase'),reason=status.get('reason'))
            pairs.append(row)
            continue
        base_file,quota_file=result_dir/f'{pid}_baseline.json',result_dir/f'{pid}_quota.json'
        files.extend((base_file,quota_file))
        baseline=json.loads(base_file.read_text());quota=json.loads(quota_file.read_text())
        if not row['binding']:
            assert quota['metric_values_identical_to_baseline']
            quota=baseline
        for side,data in (('baseline',baseline),('quota',quota)):
            witnesses=[dict(player=r['player'],root_index=r['root_index'],own=r['own'],
                history=r['history'],reach_mass=r['reach_mass'],first_query_gap=r['first_query_gap'],
                query_access_value=r['query_access_value'],query=q)
                for r in data['rows'] if r['first_query_gap']>TOL
                for q in r['query_details'] if q.get('same_query_answer_value',0)>TOL]
            row[side]=dict(summary=data['summary'],initial=initial_decisions(data),
                ex_ante_payoffs=data['ex_ante_payoffs'],nodes=data['nodes'],
                has_real_acquisition_witness=bool(witnesses),observed_real_acquisition_witnesses=witnesses)
        base_cells={tuple(c['own']):c for c in row['baseline']['initial']['cells']}
        quota_cells={tuple(c['own']):c for c in row['quota']['initial']['cells']}
        assert base_cells.keys()==quota_cells.keys()
        row['changed_initial_optimal_cells']=sum(base_cells[k]['optimal_actions']!=quota_cells[k]['optimal_actions'] for k in base_cells)
        row['offer_regret_delta']=row['quota']['initial']['mean_offer_regret']-row['baseline']['initial']['mean_offer_regret']
        pairs.append(row)
    result=dict(version='original-100-offer-quota-terminal-study-v1',
        all=aggregate(pairs),binding=aggregate([r for r in pairs if r['binding']]),
        nonbinding=aggregate([r for r in pairs if not r['binding']]),
        by_split={s:aggregate([r for r in pairs if r['split']==s]) for s in ('train','validation','test')},
        pairs=pairs,
        scope='All original parents, equal parent weight. First-proposal cells weighted by profile reach, players uniform; initial-menu regret uses uniform legal OFFERs only as a diagnostic, not actual model behavior. No new slice C/S/D.',
        selection_effects='Baseline is original saved profile; quota is independently re-solved with same objective. Differences include equilibrium-profile selection and partner adaptation, not universal effects across all equilibria.',
        answer_masks='Only informative best queries measured; no-query answer gains are full-game mechanism diagnostics, not k=1/2/3 slice labels',
        artifact_inputs={str(p):digest(p) for p in files})
    destination=args.output or run
    if args.output:
        destination.mkdir(parents=True,exist_ok=False)
    write(destination/'paired_analysis.json',result)
    write(destination/'analysis_snapshot.json',dict(status='completed-cpu-aggregation-only',actual_argv=sys.argv,
        resolved_config=dict(tolerance=TOL,parents='all 100, no filters',missing='report denominator, never zero imputation',
            offer_regret='uniform mean over legal initial OFFERs relative to own best Q; prior-weighted initial own-type cells'),
        source_sha256=digest(Path(__file__)),input_hashes=result['artifact_inputs'],
        model_identity='none',sampling_reward_contract='read-only aggregation, no training/sampling',
        runtime=dict(python=sys.version,platform=platform.platform()),result_sha256=digest(destination/'paired_analysis.json')))
    print(json.dumps({k:result[k] for k in ('all','binding','nonbinding','by_split')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
