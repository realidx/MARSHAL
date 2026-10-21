"""Portable, resumable CPU terminal solving for the frozen 100 parents.

This is a separate research protocol. It never edits the input pool or uses
Q/S/D to select a policy. Every accepted reference is independently audited.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
VERSION='strategic-parents-remote-terminal-solver-repair-v3'
POOL=Path('new/strategic_game_v1_20261021/parents_100_v1')
PROFILES={
    'base':dict(solve_seconds=300,audit_seconds=180,max_sweeps=256,max_candidates=8,
        max_joint_cells=65536,max_joint_evaluations=640,large_tree_ordered_sweeps=4,
        starts=['uniform']),
    'extended':dict(solve_seconds=900,audit_seconds=300,max_sweeps=512,max_candidates=12,
        max_joint_cells=131072,max_joint_evaluations=2048,large_tree_ordered_sweeps=8,
        starts=['uniform','dirichlet:0','dirichlet:1','dirichlet:2']),
}


def now():return datetime.now(timezone.utc).isoformat()


def digest(path):
    h=sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))


def atomic(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('x') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def read(path):return json.loads(Path(path).read_text())


def verify_bundle():
    manifest=read(ROOT/'BUNDLE_MANIFEST.json')
    for rel,h in manifest['files'].items():
        if digest(ROOT/rel)!=h:raise ValueError('Bundle file changed or corrupted: '+rel)
    return manifest


def environment():
    import numpy as np
    import scipy
    return dict(python=sys.version,python_version=platform.python_version(),
        executable=sys.executable,numpy=np.__version__,scipy=scipy.__version__,
        platform=platform.platform(),machine=platform.machine(),hostname=socket.gethostname(),
        cpu_count=os.cpu_count(),slurm={k:os.environ.get(k) for k in
        ('SLURM_JOB_ID','SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE','SLURM_JOB_PARTITION')},
        threads={k:os.environ.get(k,'NOT_RECORDED') for k in
        ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')},
        numpy_build_config=getattr(np.__config__,'CONFIG','NOT_RECORDED'))


def numerical_environment(env):
    return {k:env[k] for k in ('python_version','numpy','scipy','machine')}


def parents():
    rows=[json.loads(s) for s in (ROOT/POOL/'parents.jsonl').read_text().splitlines()]
    if len(rows)!=100 or len({r['id'] for r in rows})!=100:
        raise ValueError('Expected exactly the frozen 100 distinct parents')
    if digest(ROOT/POOL/'parents.jsonl')!=read(ROOT/POOL/'manifest.json')['raw_sha256']:
        raise ValueError('Parent manifest mismatch')
    return rows


def tree_for(parent,config,seconds):
    from new.strategic_game_v1_20261021.rules import StrategicRules
    from new.game_design_feasibility_20261021.design import count_public_tree
    from training.b_sft.preference_contract import world_weights
    from training.strategic_slices.bounded import BoundedPrivateWindow
    rules=StrategicRules(parent['raw'])
    if count_public_tree(rules)!=parent['preflight']:raise ValueError('Preflight/parent identity changed')
    tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
        world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),
        lookahead_rr=3,seconds=seconds,**config)
    if tree.cutoff_leaves or len(tree.entries)!=parent['preflight']['public_histories']:
        raise ValueError('Full-terminal tree assertion failed')
    if any(not e.node.state.is_terminal for e in tree.entries if e.actor is None):
        raise ValueError('Nonterminal leaf forbidden')
    return tree


def constructor_config(plan):
    names=('max_sweeps','max_candidates','max_joint_cells','max_joint_evaluations','large_tree_ordered_sweeps')
    return dict(max_nodes=100000,epsilon=1e-8,**{k:plan[k] for k in names})


def worker(task_path):
    import numpy as np
    from training.b_sft.shared_teacher import SearchLimit
    from training.strategic_slices.equilibrium import certify_policy
    from training.strategic_slices.common import save_reference
    verify_bundle()
    task=read(task_path);folder=Path(task_path).parent;plan=task['plan']
    p=next(p for p in parents() if p['id']==task['parent_id'])
    result=dict(parent_id=p['id'],index=p['index'],status='started',started_at=now(),
        plan=plan,constructor=constructor_config(plan),environment=environment(),
        source_bundle_sha256=digest(ROOT/'BUNDLE_MANIFEST.json'),
        parents_sha256=digest(ROOT/POOL/'parents.jsonl'))
    start=time.monotonic();phase='construct';tree=None
    try:
        tree=tree_for(p,result['constructor'],plan['construct_seconds'])
        tree.diagnostic_dir = folder/'search_diagnostics'
        result['construction_seconds']=time.monotonic()-start
        if plan['start'].startswith('dirichlet:'):
            seed=int(plan['start'].split(':')[1]);rng=np.random.default_rng(seed)
            for i,e in enumerate(tree.entries):
                if e.actor is None:continue
                prob=np.zeros_like(tree.policy[i])
                for ids in tree.information_groups[i]:
                    prob[:,ids]=rng.dirichlet(np.ones(len(e.actions)))[:,None]
                tree.policy[i]=prob
            tree.initialization=f'public-infoset-dirichlet-seed-{seed}'
        result['initialization']=tree.initialization
        phase='solve';t=time.monotonic();tree.deadline=t+plan['solve_seconds']
        tree.solve();result['solve_seconds']=time.monotonic()-t
        phase='independent_audit';t=time.monotonic();tree.deadline=t+plan['audit_seconds']
        checked=certify_policy(tree,epsilon=1e-8)
        if checked is None:raise SearchLimit('Independent full-terminal certification did not pass')
        audit=tree.audit_native()
        result['audit_seconds']=time.monotonic()-t
        phase='save_reference'
        save_reference(folder/'reference.npz',tree)
        result.update(status='certified',certificate=tree.certificate,
            independent_certificate=checked['certificate'],native_audit=audit,
            reference_sha256=digest(folder/'reference.npz'),full_native_terminal=True)
    except (SearchLimit,MemoryError) as e:
        result.update(status='unavailable',failed_phase=phase,reason=f'{type(e).__name__}: {e}',oracle_label=None)
        if tree is not None:result['last_equilibrium_audit']=getattr(tree,'equilibrium_audit',None)
    except Exception as e:
        result.update(status='infrastructure_error',failed_phase=phase,reason=f'{type(e).__name__}: {e}',oracle_label=None)
    result.update(finished_at=now(),elapsed_seconds=time.monotonic()-start)
    atomic(folder/'result.json',result)
    return 3 if result['status']=='infrastructure_error' else 0


def checked_result(folder):
    result=read(Path(folder)/'result.json')
    if result['status']=='certified':
        if digest(Path(folder)/'reference.npz')!=result['reference_sha256']:
            raise ValueError('Saved reference corrupted: '+str(folder))
        if not result.get('full_native_terminal') or not result.get('independent_certificate'):
            raise ValueError('Reference lacks full-terminal certification')
    return result


def choose(scope,out,plans):
    rows=[];pending=[]
    for p in scope:
        pid=p['id'];imported=out/'imported'/pid
        if (imported/'result.json').exists():
            r=checked_result(imported)
            if r['status']!='certified':raise ValueError('Only certified imports allowed')
            rows.append(dict(parent_id=pid,index=p['index'],status='certified',origin='imported',
                execution=str(imported.relative_to(out)),reference_sha256=r['reference_sha256']))
            continue
        chosen=None;failures=[];next_plan=None
        for pi,plan in enumerate(plans):
            attempts=out/'attempts'/pid/f'plan-{pi:02d}'
            executions=sorted(attempts.glob('execution-*')) if attempts.exists() else []
            completed=[e for e in executions if (e/'result.json').exists()]
            if completed:
                # More than one execution may be needed after interruption,
                # but only the completed outcome controls this declared plan.
                r=checked_result(completed[0])
                if r['status']=='infrastructure_error':
                    raise RuntimeError('Infrastructure error needs inspection: '+str(completed[0]))
                if r['status']=='certified':chosen=completed[0];break
                failures.append(str(completed[0].relative_to(out)))
                continue
            next_plan=(pi,plan,len(executions));break
        if chosen:
            r=checked_result(chosen)
            rows.append(dict(parent_id=pid,index=p['index'],status='certified',origin='solved',
                execution=str(chosen.relative_to(out)),reference_sha256=r['reference_sha256']))
        elif next_plan is not None:
            pending.append((p,*next_plan))
        else:
            rows.append(dict(parent_id=pid,index=p['index'],status='unavailable',failed_executions=failures,oracle_label=None))
    return rows,pending


def workers(requested):
    available=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else (os.cpu_count() or 1)
    if os.environ.get('SLURM_CPUS_PER_TASK'):available=min(available,int(os.environ['SLURM_CPUS_PER_TASK']))
    if requested<0:raise ValueError('workers must be zero (auto) or positive')
    return max(1,min(4,available)) if requested==0 else min(requested,available)


def terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()


def run(args):
    import shutil
    manifest=verify_bundle();all_parents=parents();out=args.output.resolve()
    indices=set(args.indices) if args.indices is not None else set(range(100))
    if not indices or not indices.issubset(set(range(100))):raise ValueError('Invalid indices')
    scope=[p for p in all_parents if p['index'] in indices]
    profile=PROFILES[args.profile].copy()
    for key in ('solve_seconds','audit_seconds','max_joint_cells'):
        value=getattr(args,key)
        if value is not None:
            if value<=0:raise ValueError(key+' must be positive')
            profile[key]=value
    plans=[dict(**{k:v for k,v in profile.items() if k!='starts'},start=start,
        construct_seconds=args.construct_seconds) for start in profile['starts']]
    if args.construct_seconds<=0:raise ValueError('construct-seconds must be positive')
    env=environment();effective_workers=workers(args.workers)
    contract=dict(version=VERSION,bundle_manifest_sha256=digest(ROOT/'BUNDLE_MANIFEST.json'),
        parents_sha256=digest(ROOT/POOL/'parents.jsonl'),profile=args.profile,plans=plans,
        scope_indices=sorted(indices),numerical_environment=numerical_environment(env),
        imported_from=str(args.from_run.resolve()) if args.from_run else None)
    if out.exists() and not args.resume:raise ValueError('Output exists; use --resume or a new output path')
    out.mkdir(parents=True,exist_ok=True)
    lock=out/'.run.lock'
    if lock.exists() and args.recover_lock:
        old=read(lock)
        if old.get('hostname')==socket.gethostname():
            try:os.kill(old['pid'],0)
            except ProcessLookupError:pass
            else:raise RuntimeError('Recorded owner process still exists; do not recover this lock')
        atomic(out/'sessions'/('recovered-lock-'+uuid.uuid4().hex+'.json'),old)
        lock.unlink()
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(dict(pid=os.getpid(),hostname=socket.gethostname(),time=now()),f)
    session=uuid.uuid4().hex;session_path=out/'sessions'/(session+'.json');active={}
    session_record=dict(id=session,started_at=now(),actual_argv=sys.argv,workers=effective_workers,
        environment=env,status='running')
    interrupted=False
    def request_interrupt(*_):
        # Do not raise between Popen() and adding the process to active;
        # otherwise a just-created worker could be orphaned on cancellation.
        nonlocal interrupted
        interrupted=True
    old_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    for sig in old_handlers:signal.signal(sig,request_interrupt)
    try:
        snapshot_path=out/'pipeline_snapshot.json'
        if snapshot_path.exists():
            if read(snapshot_path)['contract']!=contract:raise ValueError('Resume contract changed; create a new output')
        else:
            import inspect
            from training.strategic_slices.bounded import BoundedPrivateWindow
            from training.strategic_slices.equilibrium import solve_equilibrium
            defaults={label:{k:v.default for k,v in inspect.signature(fn).parameters.items()
                if v.default is not inspect.Parameter.empty} for label,fn in
                [('tree',BoundedPrivateWindow.__init__),('solver',solve_equilibrium)]}
            atomic(snapshot_path,dict(version=VERSION,created_at=now(),contract=contract,
                actual_argv=sys.argv,resolved_workers=effective_workers,environment=env,
                source_and_data_files=manifest['files'],unmodified_constructor_and_solver_defaults=defaults,
                acceptance='Native terminal; own-information epsilon-Nash and local support/response-only social tie audit; epsilon 1e-8, tie tolerance 1e-9',
                initialization_selection='First certified in predeclared plan order; no information/model metric considered',
                model_prompt_Q_S_D_training='NOT_USED_OR_MEASURED',parent_membership='Fixed 100; no replacements'))
        if args.from_run:
                origin=args.from_run.resolve();verify_output(origin)
                old=read(origin/'pipeline_snapshot.json')
                if any(old['contract'][k]!=contract[k] for k in ('bundle_manifest_sha256','parents_sha256','numerical_environment')):
                    raise ValueError('Imported source/data/numerical environment identity differs')
                if not (out/'import_provenance.json').exists():
                    atomic(out/'import_provenance.json',dict(path=str(origin),
                        snapshot_sha256=digest(origin/'pipeline_snapshot.json'),
                        summary_sha256=digest(origin/'summary.json')))
                for r in read(origin/'summary.json')['results']:
                    if r['parent_id'] not in {p['id'] for p in scope} or r['status']!='certified':continue
                    src=origin/r['execution'];checked_result(src)
                    dst=out/'imported'/r['parent_id']
                    if dst.exists():
                        checked_result(dst)
                        continue
                    temporary=out/'import-staging'/(r['parent_id']+'-'+uuid.uuid4().hex)
                    temporary.mkdir(parents=True,exist_ok=False)
                    shutil.copyfile(src/'reference.npz',temporary/'reference.npz')
                    shutil.copyfile(src/'result.json',temporary/'result.json')
                    atomic(temporary/'origin.json',dict(run=str(origin),execution=r['execution'],
                        snapshot_sha256=digest(origin/'pipeline_snapshot.json')))
                    checked_result(temporary);dst.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(temporary,dst)
        if (out/'COMPLETE.json').exists():
            verify_output(out);print(json.dumps(read(out/'summary.json')['counts']),flush=True);return 0
        atomic(session_path,session_record)
        while True:
            if interrupted:raise KeyboardInterrupt()
            rows,pending=choose(scope,out,plans)
            running_ids={item['parent_id'] for item in active.values()}
            pending=[task for task in pending if task[0]['id'] not in running_ids]
            for p,pi,plan,ei in pending[:max(0,effective_workers-len(active))]:
                folder=out/'attempts'/p['id']/f'plan-{pi:02d}'/f'execution-{ei:03d}'
                folder.mkdir(parents=True,exist_ok=False)
                task=dict(parent_id=p['id'],index=p['index'],plan=plan,
                    session_id=session,
                    source_bundle_sha256=contract['bundle_manifest_sha256'],parents_sha256=contract['parents_sha256'])
                atomic(folder/'task.json',task)
                log=(folder/'worker.log').open('x')
                proc=subprocess.Popen([sys.executable,'-m','new.strategic_game_v1_20261021.remote_solver',
                    '_worker','--task',str(folder/'task.json')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                active[proc]=dict(parent_id=p['id'],folder=folder,log=log,start=time.monotonic(),
                    hard_seconds=plan['construct_seconds']+plan['solve_seconds']+plan['audit_seconds']+60)
            if interrupted:raise KeyboardInterrupt()
            for proc,item in list(active.items()):
                if interrupted:raise KeyboardInterrupt()
                hard_timeout=proc.poll() is None and time.monotonic()-item['start']>item['hard_seconds']
                if hard_timeout:terminate(proc)
                if proc.poll() is None:continue
                item['log'].close();folder=item['folder']
                if not (folder/'result.json').exists():
                    if not hard_timeout and proc.returncode not in (-9,137):
                        if interrupted:raise KeyboardInterrupt()
                        raise RuntimeError('Worker exited without result; inspect '+str(folder/'worker.log'))
                    atomic(folder/'result.json',dict(parent_id=item['parent_id'],status='unavailable',
                        failed_phase='worker_supervision',reason='hard wall limit or SIGKILL/OOM',
                        exit_code=proc.returncode,oracle_label=None))
                result=checked_result(folder)
                print(json.dumps(dict(parent_id=item['parent_id'],status=result['status'],
                    elapsed_seconds=round(time.monotonic()-item['start'],2),reason=result.get('reason')),ensure_ascii=False),flush=True)
                del active[proc]
                if result['status']=='infrastructure_error':raise RuntimeError('Infrastructure error: '+str(folder/'result.json'))
            atomic(out/'progress.json',dict(updated_at=now(),resolved=len(rows),expected=len(scope),
                counts=dict(Counter(r['status'] for r in rows)),active=len(active)))
            if not active and not choose(scope,out,plans)[1]:break
            time.sleep(.2)
        rows,pending=choose(scope,out,plans)
        if pending or len(rows)!=len(scope):raise RuntimeError('Incomplete execution accounting')
        rows.sort(key=lambda r:r['index'])
        summary=dict(version=VERSION,finished_at=now(),expected=len(scope),pool_size=100,
            counts=dict(Counter(r['status'] for r in rows)),results=rows,
            all_100_certified=len(rows)==100 and all(r['status']=='certified' for r in rows),
            no_Q_S_D_measured=True)
        atomic(out/'summary.json',summary)
        # Seal all actual evidence except mutable progress/locks and session
        # completion metadata; session events are retained separately.
        files={str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()
            and p.name not in ('.run.lock','progress.json','COMPLETE.json','ARTIFACTS.json')
            and 'sessions' not in p.relative_to(out).parts}
        atomic(out/'ARTIFACTS.json',files)
        atomic(out/'COMPLETE.json',dict(execution_complete=True,all_100_certified=summary['all_100_certified'],
            certified=summary['counts'].get('certified',0),unavailable=summary['counts'].get('unavailable',0),
            expected=len(scope),summary_sha256=digest(out/'summary.json'),
            artifacts_sha256=digest(out/'ARTIFACTS.json')))
        print(json.dumps(dict(output=str(out),**summary['counts'],all_100_certified=summary['all_100_certified'])),flush=True)
        return 0
    except KeyboardInterrupt:
        session_record['status']='interrupted';return 130
    except Exception:
        session_record['status']='infrastructure_error';raise
    finally:
        for proc,item in active.items():terminate(proc);item['log'].close()
        if session_record['status']=='running':session_record['status']='finished'
        session_record['finished_at']=now();atomic(session_path,session_record)
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
        lock.unlink(missing_ok=True)


def verify_output(out):
    done=read(out/'COMPLETE.json')
    if digest(out/'ARTIFACTS.json')!=done['artifacts_sha256']:raise ValueError('Artifact manifest changed')
    for rel,h in read(out/'ARTIFACTS.json').items():
        if digest(out/rel)!=h:raise ValueError('Result artifact changed: '+rel)
    if digest(out/'summary.json')!=done['summary_sha256']:raise ValueError('Summary changed')
    return read(out/'summary.json')


def audit(args):
    import numpy as np
    from training.strategic_slices.equilibrium import certify_policy
    verify_bundle();out=args.output.resolve();summary=verify_output(out)
    contract=read(out/'pipeline_snapshot.json')['contract']
    if contract['bundle_manifest_sha256']!=digest(ROOT/'BUNDLE_MANIFEST.json'):
        raise ValueError('Audit source bundle differs')
    byid={p['id']:p for p in parents()};checks=[]
    for r in summary['results']:
        if r['status']!='certified':continue
        folder=out/r['execution'];record=checked_result(folder)
        if not args.hash_only:
            tree=tree_for(byid[r['parent_id']],record['constructor'],args.seconds)
            with np.load(folder/'reference.npz',allow_pickle=False) as archive:
                flat=archive['probabilities']
            offset=0
            for i,p in enumerate(tree.policy):
                if p is None:continue
                count=p.size;tree.policy[i]=flat[offset:offset+count].reshape(p.shape).copy();offset+=count
            if offset!=flat.size:raise ValueError('Reference probability length differs')
            tree.initialization=record['initialization']
            tree.deadline=time.monotonic()+args.seconds
            result=certify_policy(tree,epsilon=1e-8)
            if result is None:raise ValueError('Saved reference failed independent re-certification')
            if tree.reference_identity()[0]!=record['certificate']['policy_sha256']:
                raise ValueError('Saved policy identity differs')
            tree.values=result['values'];tree.audit_native()
        checks.append(r['parent_id'])
        print(json.dumps(dict(audited=r['parent_id'],kind='hash' if args.hash_only else 'full-terminal-recertification')),flush=True)
    report=dict(time=now(),kind='hash-only' if args.hash_only else 'full-terminal-recertification',
        checked=len(checks),parents=checks,unavailable=summary['counts'].get('unavailable',0),
        expected=summary['expected'],pool_size=100,all_100_certified=summary['all_100_certified'],
        environment=environment(),source_bundle_sha256=digest(ROOT/'BUNDLE_MANIFEST.json'))
    atomic(out/'audits'/(uuid.uuid4().hex+'.json'),report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 2 if args.require_all and not summary['all_100_certified'] else 0


def main():
    # Set before importing any numerical modules, also inherited by workers.
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[key]='1'
    sys.path.insert(0,str(ROOT/'third_party/negotiation_benchmark/src'))
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('run');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--profile',choices=PROFILES,default='base');p.add_argument('--workers',type=int,default=0)
    p.add_argument('--resume',action='store_true');p.add_argument('--recover-lock',action='store_true')
    p.add_argument('--from-run',type=Path);p.add_argument('--indices',nargs='+',type=int)
    p.add_argument('--construct-seconds',type=float,default=120)
    p.add_argument('--solve-seconds',type=float);p.add_argument('--audit-seconds',type=float)
    p.add_argument('--max-joint-cells',type=int)
    p=sub.add_parser('audit');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hash-only',action='store_true');p.add_argument('--require-all',action='store_true')
    p.add_argument('--seconds',type=float,default=300)
    sub.add_parser('doctor')
    p=sub.add_parser('_worker');p.add_argument('--task',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='run':return run(args)
    if args.command=='audit':return audit(args)
    if args.command=='_worker':return worker(args.task)
    manifest=verify_bundle()
    from new.strategic_game_v1_20261021.rules import StrategicRules
    rows=parents();rules=StrategicRules(rows[0]['raw'])
    print(json.dumps(dict(bundle=manifest['version'],environment=environment(),parents=len(rows),
        input_sha256=digest(ROOT/POOL/'parents.jsonl'),first_game=rules.public_game()),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e}',file=sys.stderr);sys.exit(1)
