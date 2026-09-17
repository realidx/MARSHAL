"""Startup timing and concurrent CPU-side role preparation for two-GPU B/P."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import resource
import threading
import faulthandler


_trace_lock = threading.Lock()
_active_phases = {}
_trace_file = None


def process_snapshot():
    """No CUDA calls: diagnostics must not create contexts or synchronize GPUs."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = dict(cpu_user=usage.ru_utime, cpu_system=usage.ru_stime,
                  major_faults=usage.ru_majflt, minor_faults=usage.ru_minflt,
                  voluntary_switches=usage.ru_nvcsw, involuntary_switches=usage.ru_nivcsw)
    for name in ('io', 'schedstat', 'wchan'):
        try: result[name] = Path('/proc/self', name).read_text().strip()
        except OSError: pass
    if hasattr(os, 'sched_getaffinity'):
        result['allowed_cpus'] = sorted(os.sched_getaffinity(0))
    return result


def _event(root, record):
    with (root / f'startup_events-{os.getpid()}.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(unix=time.time(), pid=os.getpid(),
            worker=os.environ.get('WORKER_NAME', 'driver'), **record)) + '\n')


def _begin_trace(root, token, phase):
    global _trace_file
    if os.environ.get('BP_STARTUP_DIAGNOSTICS') != '1': return
    with _trace_lock:
        if not _active_phases:
            _trace_file = (root / f'startup-stacks-{os.getpid()}.log').open('a')
            # A C watchdog can dump stacks even when the Python GIL is blocked.
            faulthandler.dump_traceback_later(60, repeat=True, file=_trace_file)
        _active_phases[token] = phase
        _trace_file.write(f'\nBEGIN {phase} unix={time.time()} active={list(_active_phases.values())}\n')
        _trace_file.flush()


def _end_trace(token):
    global _trace_file
    with _trace_lock:
        _active_phases.pop(token, None)
        if not _active_phases and _trace_file is not None:
            faulthandler.cancel_dump_traceback_later()
            _trace_file.close()
            _trace_file = None


def enabled(config):
    return getattr(config,'social_bp_curriculum',False) and config.num_gpus_per_node==2


def environment_config():
    from types import SimpleNamespace
    folder=os.environ.get('BP_DIAGNOSTICS_DIR')
    return SimpleNamespace(social_bp_curriculum=bool(folder),num_gpus_per_node=2,output_dir=folder)


@contextmanager
def startup_phase(config,phase):
    if not enabled(config):
        yield
        return
    root=Path(config.output_dir);root.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();status='ok';token=object();before=process_snapshot()
    _event(root, dict(event='begin', phase=phase, resources=before))
    print(f"BP_STARTUP BEGIN {os.environ.get('WORKER_NAME','driver')} {phase} pid={os.getpid()}", flush=True)
    _begin_trace(root, token, phase)
    try:
        yield
    except BaseException:
        status='failed'
        raise
    finally:
        _end_trace(token)
        after=process_snapshot()
        row=dict(phase=phase,seconds=time.perf_counter()-start,status=status,pid=os.getpid(),
                 worker=os.environ.get('WORKER_NAME','driver'),rank=os.environ.get('RANK','0'),
                 finished_unix=time.time())
        row['cpu_seconds']=(after['cpu_user']+after['cpu_system']-before['cpu_user']-before['cpu_system'])
        row['major_faults']=after['major_faults']-before['major_faults']
        row['resources_before']=before;row['resources_after']=after
        # One file per process; no cross-process append contention on shared storage.
        root=Path(config.output_dir);root.mkdir(parents=True,exist_ok=True)
        with (root/f'startup-{os.getpid()}.jsonl').open('a') as output:
            output.write(json.dumps(row)+'\n')
        _event(root, dict(event='end', phase=phase, seconds=row['seconds'], status=status))
        print(f"BP_STARTUP {row['worker']} {phase}: {row['seconds']:.2f}s ({status})",flush=True)


def prepare_roles(config,resource_manager,cluster_factory):
    """Only create actors/import modules/query devices concurrently, not model init."""
    specs=[('actor_train',config.actor_train.name,config.actor_train),
           ('actor_infer',config.actor_infer.name,config.actor_infer),
           ('reference',config.reference.name,config.reference)]
    specs.extend((f'reward:{name}',f'reward-{name}',value) for name,value in config.rewards.items())
    if config.adv_estimator!='grpo':raise ValueError('Concurrent B/P role preparation requires GRPO')
    def create(spec):
        key,name,value=spec
        with startup_phase(config,'create_'+key):
            return cluster_factory(name=name,worker_cls=value.worker_cls,
                                   resource_manager=resource_manager,worker_config=value)
    with startup_phase(config,'create_all_roles'):
        with ThreadPoolExecutor(max_workers=len(specs)) as pool:
            pending=[(spec[0],pool.submit(create,spec)) for spec in specs]
            results={};errors=[]
            for name,future in pending:
                try:results[name]=future.result()
                except BaseException as exc:errors.append((name,exc))
            if errors:raise RuntimeError('Failed preparing roles: '+', '.join(name for name,_ in errors)) from errors[0][1]
    return results
