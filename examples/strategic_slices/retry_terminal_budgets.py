"""Paired 30s/120s retries of the original 15 time-budget failures.

Only time budget changes. Each attempt starts from scratch. Instrumentation is
process-local; solver source and acceptance criteria remain unchanged.
"""
import argparse,json,os,subprocess,sys,time,traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import Counter
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import write_json,file_hash,save_reference
from training.strategic_slices.freeze import source_identity
import training.strategic_slices.equilibrium as equilibrium


def classify(message):
    if 'Joint equilibrium candidate' in message and ('zero probability mass' in message or 'nonfinite probabilities' in message):
        return 'invalid_equilibrium_candidate'
    if 'wall budget exceeded' in message:return 'solver_time_budget'
    if 'information-cell budget exceeded' in message:return 'joint_cell_budget'
    if 'node budget exceeded' in message:return 'node_budget'
    if 'did not pass complete deviation/tie checks' in message:return 'uncertified_reference'
    return 'error'


def worker(source,out,index,budget):
    record=dict(index=index,budget_seconds=budget,raw_sha256=file_hash(source/f'raw_{index}.json'),
        status='started',oracle_label=None,timings={})
    path=out/f'result_{budget}_{index}.json';write_json(path,record)
    stats=dict(equilibrium_seconds=0.,certification_seconds=0.,certification_calls=0)
    original_certify=equilibrium.certify_policy;original_solve=equilibrium.solve_equilibrium
    def certify(*args,**kwargs):
        started=time.monotonic()
        try:return original_certify(*args,**kwargs)
        finally:
            stats['certification_seconds']+=time.monotonic()-started;stats['certification_calls']+=1
    def solve(*args,**kwargs):
        started=time.monotonic()
        try:return original_solve(*args,**kwargs)
        finally:stats['equilibrium_seconds']+=time.monotonic()-started
    equilibrium.certify_policy=certify;equilibrium.solve_equilibrium=solve
    start=time.monotonic();phase='setup';phase_start=start;tree=None;solve_time=0.
    try:
        raw=json.loads((source/f'raw_{index}.json').read_text());rules=PrivateInvestigationRules(raw)
        record.update(players=rules.spec.n_players,worlds=len(rules.worlds),remaining_proposals=len(rules.spec.round_robin))
        record['timings']['setup_seconds']=time.monotonic()-phase_start
        phase='construction';phase_start=time.monotonic()
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),
            lookahead_rr=3,max_nodes=30000,seconds=budget)
        record['timings']['construction_seconds']=time.monotonic()-phase_start
        record['nodes']=len(tree.entries)
        phase='solve_and_certify';phase_start=time.monotonic()
        tree.solve();solve_time=time.monotonic()-phase_start
        phase='native_audit';phase_start=time.monotonic()
        audit=tree.audit_native();assert audit['cutoff_leaves']==0
        record['timings']['native_audit_seconds']=time.monotonic()-phase_start
        save_reference(out/f'reference_{budget}_{index}.npz',tree)
        record.update(status='certified',certificate=tree.certificate,native_audit=audit)
        record.pop('oracle_label',None)
    except Exception as exc:
        elapsed=time.monotonic()-phase_start
        if phase=='construction':record['timings']['construction_seconds']=elapsed
        elif phase=='solve_and_certify':solve_time=elapsed
        else:record['timings'][phase+'_seconds']=elapsed
        record.update(status=classify(str(exc)),reason=str(exc),failed_phase=phase)
        traceback.print_exc()
    finally:
        equilibrium.certify_policy=original_certify;equilibrium.solve_equilibrium=original_solve
        record['timings'].update(search_excluding_certification_seconds=max(0.,stats['equilibrium_seconds']-stats['certification_seconds']),
            candidate_certification_seconds=stats['certification_seconds'],certification_calls=stats['certification_calls'],
            final_wrapper_checks_seconds=max(0.,solve_time-stats['equilibrium_seconds']),solve_and_certify_seconds=solve_time,
            total_seconds=time.monotonic()-start)
        write_json(path,record)
    print(index,budget,record['status'],record['timings'],flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_native_entry_search_v2'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int);p.add_argument('--budget',type=int)
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(a.source,out,a.worker,a.budget);return
    original=json.loads((a.source/'summary.json').read_text());indices=[r['index'] for r in original['results'] if r['status']=='solver_time_budget']
    assert len(indices)==15
    excluded=[dict(index=r['index'],status=r['status']) for r in original['results'] if r['status'] not in ('verified','solver_time_budget')]
    sources=source_identity();start=time.monotonic()
    summary=dict(source_summary_sha256=file_hash(a.source/'summary.json'),original_budget_seconds=6,
        indices=indices,excluded_original_failures=excluded,stages={},source_identity=sources,
        timing_note='Construction includes native tree/information partitions. Search excludes calls to certify_policy; candidate certification includes all successful/failed candidate checks. Final wrapper checks include privacy identity and final root deviations. Native audit is outside the solver deadline.',
        caveat='Same cases/settings except wall budget; solver phase allocations depend on available time, so this is not continuation of an identical search trajectory. No C/S remeasurement or population timing claim.')
    write_json(out/'summary.json',summary)
    def launch(index,budget):
        with (out/f'worker_{budget}_{index}.log').open('w') as log:
            try:
                r=subprocess.run([sys.executable,__file__,'--source',str(a.source),'--output',str(out),'--worker',str(index),'--budget',str(budget)],
                    stdout=log,stderr=subprocess.STDOUT,timeout=budget+30,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
                if r.returncode:raise RuntimeError(f'Worker exited {r.returncode}')
                result=json.loads((out/f'result_{budget}_{index}.json').read_text())
            except (subprocess.TimeoutExpired,RuntimeError) as exc:
                result=dict(index=index,budget_seconds=budget,status='hard_timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'worker_error',reason=str(exc),oracle_label=None)
                write_json(out/f'result_{budget}_{index}.json',result)
        print('completed',budget,index,result['status'],flush=True)
        return result
    remaining=indices
    for budget in (30,120):
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda i:launch(i,budget),remaining))
        summary['stages'][str(budget)]=dict(attempted=len(results),statuses=dict(Counter(r['status'] for r in results)),results=results)
        summary['elapsed_seconds']=time.monotonic()-start;write_json(out/'summary.json',summary)
        remaining=[r['index'] for r in results if r['status']!='certified']
        if not remaining:break
    summary.update(elapsed_seconds=time.monotonic()-start,unresolved_indices=remaining,source_unchanged=sources==source_identity())
    write_json(out/'summary.json',summary)
    print({b:stage['statuses'] for b,stage in summary['stages'].items()},flush=True)

if __name__=='__main__':main()
