"""Instrument unsuccessful search candidates; retain diagnostics, never oracle labels."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import scipy.optimize as optimize
import training.strategic_slices.equilibrium as eq
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import write_json, file_hash, save_reference
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from examples.strategic_slices.retry_terminal_budgets import classify


def worker(source, out, index, budget):
    raw_path=source/f'raw_{index}.json'; raw=json.loads(raw_path.read_text())
    rules=PrivateInvestigationRules(raw); started=time.monotonic()
    result=dict(index=index,budget=budget,raw_sha256=file_hash(raw_path),oracle_label=None,
                certifications=[],optimizers=[],joint_problems=[])
    original_cert=eq.certify_policy; original_residual=eq._JointResidual
    original_root=optimize.root; original_ls=optimize.least_squares
    def certify(tree,*args,**kwargs):
        value=original_cert(tree,*args,**kwargs)
        audit=deepcopy(tree.equilibrium_audit)
        local=audit.get('local_policy_audit',{})
        result['certifications'].append(dict(passed=value is not None,
            max_own_deviation_gain=audit['max_own_deviation_gain'],
            local_checked=bool(local), max_local_supported_action_gain=local.get('max_local_supported_action_gain'),
            own_support_failures=len(local.get('own_failures',[])),response_tie_failures=len(local.get('failures',[]))))
        return value
    class Residual(original_residual):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            result['joint_problems'].append(dict(cells=len(self.offsets),variables=len(self.x0)))
    def optimizer(original):
        def run(*args,**kwargs):
            solution=original(*args,**kwargs)
            result['optimizers'].append(dict(method=kwargs.get('method','least_squares'),
                success=bool(solution.success), message=str(solution.message),
                evaluations=int(solution.nfev) if hasattr(solution,'nfev') else None, residual_max=float(np.max(np.abs(solution.fun)))))
            return solution
        return run
    eq.certify_policy=certify;eq._JointResidual=Residual
    optimize.root=optimizer(original_root);optimize.least_squares=optimizer(original_ls)
    tree=None
    try:
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),
            lookahead_rr=3,max_nodes=30000,seconds=budget)
        result.update(nodes=len(tree.entries),worlds=tree.w,construction_seconds=time.monotonic()-started)
        tree.solve()
        result.update(status='certified_on_diagnostic_rerun',certificate=tree.certificate,native_audit=tree.audit_native())
        save_reference(out/f'reference_{index}.npz',tree)
        # No metrics: this diagnostic run must not silently substitute a reference.
    except Exception as exc:
        result.update(status=classify(str(exc)),reason=str(exc))
        if tree is not None:
            result['last_audit']=deepcopy(getattr(tree,'equilibrium_audit',None))
    finally:
        eq.certify_policy=original_cert;eq._JointResidual=original_residual
        optimize.root=original_root;optimize.least_squares=original_ls
    result['seconds']=time.monotonic()-started
    write_json(out/f'result_{index}.json',result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_native_entry_search_v2'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int)
    p.add_argument('--budget',type=int,default=120)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(a.source,a.output,a.worker,a.budget);return
    indices=[8,13,19,20,21,26,27,30];start=time.monotonic()
    def launch(index):
        budget=30 if index==20 else a.budget
        with (a.output/f'worker_{index}.log').open('w') as log:
            try:
                subprocess.run([sys.executable,'-m','examples.strategic_slices.diagnose_terminal_failures',
                    '--source',str(a.source),'--output',str(a.output),'--worker',str(index),'--budget',str(budget)],
                    stdout=log,stderr=subprocess.STDOUT,check=True,timeout=budget+30,
                    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                r=json.loads((a.output/f'result_{index}.json').read_text())
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
                r=dict(index=index,status='diagnostic_worker_failure',reason=str(exc),oracle_label=None)
                write_json(a.output/f'result_{index}.json',r)
        print(index,r['status'],len(r.get('certifications',[])),flush=True);return r
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,indices))
    write_json(a.output/'summary.json',dict(results=results,seconds=time.monotonic()-start,
        statuses=dict(Counter(r['status'] for r in results)),
        caveat='Instrumented fresh reruns; deadlines affect search trajectories. Candidate failure does not establish equilibrium nonexistence. No acceptance thresholds or core solver code changed.'))

if __name__=='__main__':main()
