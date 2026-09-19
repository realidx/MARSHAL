"""Run the frozen adversarial v2 suite with three paired sampling replicas."""
import argparse,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from examples.final_evaluation.adversarial_suite import load
from examples.final_evaluation.adversarial_runtime import play
from examples.final_evaluation.benac_a import complete

def summarize(rows):
    groups={}
    for split in sorted({r['split'] for r in rows}):
        for mode in ('binary','linear'):
            rs=[r for r in rows if r['split']==split and r['mode']==mode]
            if not rs:continue
            done=[r for r in rs if r['status']=='terminal']
            healthy=all(r['missing_utility_bounds'] is not None for r in rs)
            groups[split+'/'+mode]=dict(scoring_records=len(rs),trajectories=len({r['trajectory_id'] for r in rs}),
                complete=len(done),completion_rate=len(done)/len(rs),
                conditional_focal_mean=sum(r['focal_utility'] for r in done)/len(done) if done else None,
                conditional_total_mean=sum(r['total_utility'] for r in done)/len(done) if done else None,
                full_cohort_bounds=[sum(r['missing_utility_bounds'][k] for r in rs)/len(rs) for k in ('lower','upper')] if healthy else None)
    return dict(strata=groups,note='Conditional means must accompany completion and bounds. Shared Q0 focal rows are correlated; bounds are not confidence intervals.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--routes',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--stage',choices=['smoke','formal'],default='smoke');p.add_argument('--parallel-games',type=int,default=4)
    a=p.parse_args();manifest,resets=load()
    if a.parallel_games<1:p.error('parallel-games must be positive')
    routes=json.loads(a.routes.read_text());shared=routes['focal']==routes['q0']
    if a.stage=='smoke':
        from training.social_mixed.structure_coverage import geometry_id
        path=Path(__file__).resolve().parents[2]/'examples/social_mixed/data_reasoning_v5_candidate/selfplay_validation.jsonl'
        r=next(json.loads(l) for l in path.read_text().splitlines() if json.loads(l)['players']==3)
        r.update(evaluation_split='development',structure_family=geometry_id(r['raw']['game']));resets=[r]
    replicas=range(3) if a.stage=='formal' else range(1)
    jobs=[(r,s,rep) for r in resets for rep in replicas for s in ([0] if shared else range(3))]
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'protocol.json').write_text(json.dumps(dict(suite=manifest,routes=routes,shared_q0=shared,stage=a.stage,
        trajectories=len(jobs),scoring_records=len(resets)*len(replicas)*3),indent=2))
    rows=[]
    with ThreadPoolExecutor(max_workers=a.parallel_games) as pool:
        for start in range(0,len(jobs),a.parallel_games):
            futures=[pool.submit(play,r,s,rep,routes,a.output,complete,shared) for r,s,rep in jobs[start:start+a.parallel_games]]
            for f in futures:rows.extend(f.result())
            (a.output/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            (a.output/'summary.json').write_text(json.dumps(summarize(rows),indent=2))
            print(f'{min(start+a.parallel_games,len(jobs))}/{len(jobs)} trajectories',flush=True)
            if any(r['status']=='infrastructure_failure' for r in rows):
                (a.output/'RUN_FAILED.json').write_text(json.dumps(dict(reason='infrastructure_failure',recorded=len(rows))))
                raise RuntimeError('Infrastructure failure; stop before further batches')
    (a.output/'RUN_FINISHED.json').write_text(json.dumps(dict(recorded=len(rows),trajectories=len(jobs))))
if __name__=='__main__':main()
