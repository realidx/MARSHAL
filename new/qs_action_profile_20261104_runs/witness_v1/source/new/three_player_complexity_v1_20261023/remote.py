"""CPU subprocess scheduler, strict resume, full references and omission labels."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .common import ROOT,REG,VERSION,identity,sha,snapshot,stable,write

DEFAULTS=dict(max_nodes=600000,construct_seconds=180.,solve_seconds=600.,audit_seconds=300.,
    metric_seconds=1200.,case_seconds=3600.,memory_gb=8.,epsilon=1e-8,tie_tolerance=1e-9,
    max_sweeps=512,joint_evaluations=400,repair_passes=8,labels=True,
    backend='inertia_then_joint',repair_internal_audit_seconds=60,
    joint_front_internal_max_sweeps=256,operation='solve')


def verify_source():
    meta=json.loads(REG.read_text());assert meta['version']==VERSION
    for p,h in meta['source_hashes'].items():assert sha(ROOT/p)==h,f'Source mismatch: {p}'
    return meta


def doctor(args):
    meta=verify_source();bundle=ROOT/'BUNDLE_MANIFEST.json';verified=None
    if bundle.exists():
        files=json.loads(bundle.read_text())['files']
        for p,h in files.items():assert sha(ROOT/p)==h,f'Bundle mismatch: {p}'
        verified=len(files)
    import numpy,scipy
    print(stable(dict(version=VERSION,source_files=len(meta['source_hashes']),bundle_files_verified=verified,
        python=sys.version,executable=sys.executable,numpy=numpy.__version__,scipy=scipy.__version__,
        numpy_scipy_match_pinned=numpy.__version__=='1.26.4' and scipy.__version__=='1.12.0',
        GPU_model='NOT_REQUIRED')))


def stop(proc):
    if proc.poll() is not None:return
    os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=3)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()


def aggregate(out,jobs):
    results=[]
    for job in jobs:
        folder=out/'cases'/str(job['index']);executions=sorted(folder.glob('execution-*/result.json'))
        if not executions:continue
        path=executions[-1];r=json.loads(path.read_text());r['result_path']=str(path.relative_to(out))
        certified=path.parent/'certified.json'
        if certified.exists():
            c=json.loads(certified.read_text());r['reference_accepted']=True
            r['reference_sha256']=c['reference_sha256'];r['reference_path']=str((path.parent/'reference.npz').relative_to(out))
        else:r['reference_accepted']=r['status']=='independently_reloaded'
        results.append(r)
    write(out/'results.json',results)
    by_arm={}
    for arm in sorted({j.get('arm','diagnostic') for j in jobs}):
        group=[r for r in results if (r.get('arm') or 'diagnostic')==arm]
        by_arm[arm]=dict(resolved=len(group),certified=sum(r['reference_accepted'] for r in group),
            measured=sum(r.get('labels')=='MEASURED' for r in group),
            private_S_positive_parents=sum(r.get('summary',{}).get('counterfactual',{}).get('private_S_positive',0)>0 for r in group),
            history_S_positive_parents=sum(r.get('summary',{}).get('counterfactual',{}).get('history_S_positive',0)>0 for r in group),
            private_entry_action_positive_parents=sum(r.get('summary',{}).get('counterfactual',{}).get('private_entry_action_positive',0)>0 for r in group),
            history_entry_action_positive_parents=sum(r.get('summary',{}).get('counterfactual',{}).get('history_entry_action_positive',0)>0 for r in group))
    summary=dict(requested=len(jobs),resolved=len(results),certified=sum(r['reference_accepted'] for r in results),
        measured=sum(r.get('labels')=='MEASURED' for r in results),arms=by_arm,
        unresolved=[j['index'] for j in jobs if j['index'] not in {r['index'] for r in results}],
        unavailable=[r['index'] for r in results if not r['reference_accepted']],
        unmeasured=[r['index'] for r in results if r.get('labels')!='MEASURED'])
    write(out/'progress.json',summary);return summary


def schedule(out,jobs,cfg,workers):
    pending=[j for j in jobs if not sorted((out/'cases'/str(j['index'])).glob('execution-*/result.json'))]
    live=[]
    try:
        while pending or live:
            while pending and len(live)<workers:
                job=pending.pop(0);root=out/'cases'/str(job['index']);root.mkdir(parents=True,exist_ok=True)
                attempt=len(list(root.glob('execution-*')));folder=root/f'execution-{attempt:04d}';folder.mkdir()
                request=dict(job=job,config=cfg)
                if cfg['operation']=='audit':request.update(reference=job['audit_reference'],reference_sha256=job['audit_reference_sha256'])
                write(folder/'request.json',request)
                log=(folder/'worker.log').open('w')
                env=os.environ.copy()
                for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
                env['PYTHONPATH']=str(ROOT)+os.pathsep+str(ROOT/'third_party/negotiation_benchmark/src')
                proc=subprocess.Popen([sys.executable,'-u','-m','new.three_player_complexity_v1_20261023.worker','--task',str(folder.resolve())],
                    cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                live.append((job,folder,proc,log,time.monotonic()))
            for item in list(live):
                job,folder,proc,log,start=item;timed_out=time.monotonic()-start>cfg['case_seconds']
                if timed_out:stop(proc)
                if proc.poll() is None:continue
                log.close();path=folder/'result.json'
                if not path.exists():
                    progress=json.loads((folder/'progress.json').read_text()) if (folder/'progress.json').exists() else {}
                    write(path,dict(index=job['index'],id=job['id'],original_index=job.get('original_index'),arm=job.get('arm'),
                        status='hard_wall_timeout' if timed_out else 'worker_exit',returncode=proc.returncode,
                        last_phase=progress.get('phase'),labels='NOT_MEASURED',elapsed_seconds=time.monotonic()-start))
                r=json.loads(path.read_text());print(dict(index=job['index'],arm=job.get('arm'),status=r['status'],
                    labels=r.get('labels'),elapsed=round(r.get('elapsed_seconds',0),2)),flush=True)
                live.remove(item);aggregate(out,jobs)
            if live:time.sleep(.15)
    finally:
        for job,folder,proc,log,start in live:stop(proc);log.close()


def run(args):
    verify_source();cfg={k:getattr(args,k,default) for k,default in DEFAULTS.items()}
    cfg['labels']=not args.no_labels
    assert args.workers>0 and cfg['max_nodes']>0 and cfg['memory_gb']>=0
    assert all(cfg[k]>0 for k in ('construct_seconds','solve_seconds','audit_seconds','metric_seconds','case_seconds'))
    jobs=list(map(json.loads,args.jobs.read_text().splitlines()))
    if args.indices!='all':
        chosen=list(map(int,args.indices.split(',')));assert len(chosen)==len(set(chosen))
        jobs=[j for j in jobs if j['index'] in chosen];assert len(jobs)==len(chosen)
    assert len({j['index'] for j in jobs})==len(jobs)
    selection=dict(jobs_sha256=sha(args.jobs),indices=[j['index'] for j in jobs])
    if not args.resume:
        snapshot(args.output,dict(**cfg,workers=args.workers,selection=selection,
            hard_wall='subprocess group terminated at case_seconds',
            memory='Linux RLIMIT_AS; no application on macOS; actual flag in each result',
            profile_selection='first fully certified candidate; no Q/S/model-based reference selection'),{'jobs':identity(args.jobs)})
        write(args.output/'jobs.json',jobs)
    else:
        saved=json.loads((args.output/'pipeline_snapshot.json').read_text())
        for p,h in saved['source_hashes'].items():assert sha(ROOT/p)==h,'Resume source mismatch'
        assert saved['resolved_config']['selection']==selection,'Resume input/selection mismatch'
        for k,v in cfg.items():assert saved['resolved_config'][k]==v,f'Resume config mismatch: {k}'
        import numpy,scipy
        assert saved['environment']['python']==sys.version
        assert saved['environment']['numpy']==numpy.__version__ and saved['environment']['scipy']==scipy.__version__
        assert json.loads((args.output/'jobs.json').read_text())==jobs
    lock=(args.output/'.run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another process holds this output lock')
    with lock:
        sessions=args.output/'sessions';sessions.mkdir(exist_ok=True)
        write(sessions/f'{time.time_ns()}.json',dict(argv=sys.argv,workers=args.workers,pid=os.getpid(),resume=args.resume))
        def interrupted(signum,frame):raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM,interrupted)
        schedule(args.output,jobs,cfg,args.workers)
        summary=aggregate(args.output,jobs);write(args.output/'COMPLETE.json',dict(**summary,
            execution_complete=summary['resolved']==len(jobs),all_certified=summary['certified']==len(jobs),
            all_measured=summary['measured']==len(jobs),results_sha256=sha(args.output/'results.json'),
            pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))


def audit(args):
    original=json.loads((args.run/'pipeline_snapshot.json').read_text())
    for p,h in original['source_hashes'].items():assert sha(ROOT/p)==h,'Independent audit source mismatch'
    original_jobs=json.loads((args.run/'jobs.json').read_text());results=json.loads((args.run/'results.json').read_text())
    good={r['index']:r for r in results if r.get('reference_accepted') and r.get('reference_path')}
    jobs=[]
    for job in original_jobs:
        if job['index'] not in good:continue
        r=good[job['index']];ref=args.run/r['reference_path'];assert sha(ref)==r['reference_sha256']
        jobs.append(dict(**job,audit_reference=str(ref.resolve()),audit_reference_sha256=r['reference_sha256']))
    cfg=dict(DEFAULTS,operation='audit',labels=False,construct_seconds=args.seconds,audit_seconds=args.seconds,
        case_seconds=args.case_seconds,memory_gb=args.memory_gb,max_nodes=original['resolved_config']['max_nodes'])
    snapshot(args.output,dict(**cfg,workers=args.workers,input_run=str(args.run),input_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        successful_indices=[j['index'] for j in jobs],missing_certificates=[j['index'] for j in original_jobs if j['index'] not in good]),
        {'run_snapshot':identity(args.run/'pipeline_snapshot.json'),'results':identity(args.run/'results.json')})
    write(args.output/'jobs.json',jobs);schedule(args.output,jobs,cfg,args.workers);summary=aggregate(args.output,jobs)
    write(args.output/'COMPLETE.json',dict(**summary,original_requested=len(original_jobs),original_certified=len(jobs),
        independently_passed=sum(r['status']=='independently_reloaded' for r in json.loads((args.output/'results.json').read_text())),
        missing_original_indices=[j['index'] for j in original_jobs if j['index'] not in good],
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),results_sha256=sha(args.output/'results.json')))


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    p=sub.add_parser('run');p.add_argument('--jobs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--indices',default='all');p.add_argument('--workers',type=int,default=1);p.add_argument('--resume',action='store_true')
    p.add_argument('--no-labels',action='store_true')
    for key,default in DEFAULTS.items():
        if key in ('labels','operation','epsilon','tie_tolerance','repair_internal_audit_seconds','joint_front_internal_max_sweeps'):continue
        p.add_argument('--'+key.replace('_','-'),type=type(default),default=default,
            choices=('inertia','joint','inertia_then_joint') if key=='backend' else None)
    p=sub.add_parser('audit');p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=1);p.add_argument('--seconds',type=float,default=300.)
    p.add_argument('--case-seconds',type=float,default=900.);p.add_argument('--memory-gb',type=float,default=8.)
    args=parser.parse_args();{'doctor':doctor,'run':run,'audit':audit}[args.command](args)


if __name__=='__main__':main()
