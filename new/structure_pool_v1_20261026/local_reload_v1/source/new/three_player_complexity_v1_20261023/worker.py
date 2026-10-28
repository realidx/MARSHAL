"""One isolated native-terminal solve/measure job; parent enforces hard limits."""
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'

import argparse
import gzip
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from .common import ROOT,sha,stable,write
from .metrics import measure
from new.strategic_game_v1_20261021.rules import StrategicRules
from new.sparse_solver_v1_20261023.engine import ReducedEngine
from new.sparse_solver_v1_20261023.joint import solve as joint
from new.sparse_solver_v1_20261023.run import repair_offpath
from new.node_qs_audit_v1_20261023.run import examples
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.equilibrium import certify_policy
from training.strategic_slices.common import save_reference


def tree_for(job,config):
    rules=StrategicRules(job['raw']);root=rules.initial()
    for action in job.get('setup',[]):
        matches=[a for a in rules.actions(root) if stable(a.to_dict())==stable(action)]
        assert len(matches)==1,action
        root=rules._apply(root,matches[0])
    return BoundedPrivateWindow(rules,root,rules.worlds,lookahead_rr=3,
        max_nodes=config['max_nodes'],seconds=config['construct_seconds'],
        world_weights=world_weights(rules.worlds,job['raw']['background_prior']))


def load(tree,path):
    with np.load(path) as data:flat=data['probabilities']
    off=0
    for p in tree.policy:
        if p is not None:p[:]=flat[off:off+p.size].reshape(p.shape);off+=p.size
    assert off==len(flat)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',type=Path,required=True);args=parser.parse_args()
    request=json.loads((args.task/'request.json').read_text());job=request['job'];cfg=request['config'];start=time.monotonic()
    result=dict(index=job['index'],id=job['id'],original_index=job.get('original_index'),arm=job.get('arm'),
        kind=job.get('kind','expanded_parent'),status='started',labels='NOT_MEASURED',
        setup=job.get('setup',[]),phase='construct',memory_limit_applied=False)
    def phase(name):result['phase']=name;write(args.task/'progress.json',dict(phase=name,elapsed=time.monotonic()-start))
    try:
        if cfg['memory_gb']>0 and platform.system()=='Linux':
            import resource
            limit=int(cfg['memory_gb']*1024**3);resource.setrlimit(resource.RLIMIT_AS,(limit,limit));result['memory_limit_applied']=True
        tree=tree_for(job,cfg);result.update(nodes=len(tree.entries),worlds=tree.w,cutoff_leaves=len(tree.cutoff_leaves))
        assert not tree.cutoff_leaves,'Native terminal only, no shortened fallback'
        if cfg.get('operation')=='audit':
            phase('independent_reload');source=Path(request['reference']);assert sha(source)==request['reference_sha256'];load(tree,source)
            tree.deadline=time.monotonic()+cfg['audit_seconds'];checked=certify_policy(tree,epsilon=cfg['epsilon'])
            assert checked is not None,tree.equilibrium_audit
            result.update(status='independently_reloaded',certificate=checked['certificate'],native_audit=tree.audit_native())
        else:
            if job.get('reuse'):
                reuse=job['reuse'];raw_path=ROOT/reuse['raw_path'];ref_path=ROOT/reuse['reference_path']
                assert sha(raw_path)==reuse['raw_sha256'] and sha(ref_path)==reuse['reference_sha256']
                assert stable(json.loads(raw_path.read_text()))==stable(job['raw'])
                assert not job.get('setup'),'Root reference cannot silently apply to a different prefix'
                load(tree,ref_path);found=True;result['solver']=dict(status='explicit_raw_matched_reference_reuse',identity=reuse)
            else:
                phase('reduction');tree.deadline=time.monotonic()+cfg['construct_seconds'];engine=ReducedEngine(tree)
                phase('search');tree.deadline=time.monotonic()+cfg['solve_seconds']
                if cfg['backend']=='inertia':found,info,_=engine.iterate(seconds=cfg['solve_seconds'],max_sweeps=cfg['max_sweeps'])
                elif cfg['backend']=='inertia_then_joint':
                    front_seconds=cfg['solve_seconds']*.75
                    found,front,_=engine.iterate(seconds=front_seconds,max_sweeps=cfg['max_sweeps'])
                    info=dict(front=front,front_budget_seconds=front_seconds)
                    if not found:
                        found,refinement=joint(engine,seconds=cfg['solve_seconds']*.25,max_evaluations=cfg['joint_evaluations'])
                        info['joint']=refinement
                else:found,info=joint(engine,seconds=cfg['solve_seconds'],max_evaluations=cfg['joint_evaluations'])
                result['solver']=info
            if not found:
                result['status']='candidate_unavailable'
            else:
                phase('full_native_certification')
                tree.deadline=time.monotonic()+cfg['audit_seconds']
                checked=certify_policy(tree,epsilon=cfg['epsilon'])
                if checked is None and cfg['repair_passes']:
                    checked,events=repair_offpath(tree,cfg['repair_passes']);result['repair_events']=events
                if checked is None:result.update(status='candidate_rejected',equilibrium_audit=tree.equilibrium_audit)
                else:
                    result.update(status='certified_native_terminal_subgame' if job.get('setup') else 'certified_native_terminal_parent',
                        certificate=checked['certificate'],native_audit=tree.audit_native())
                    save_reference(args.task/'reference.npz',tree);result['reference_sha256']=sha(args.task/'reference.npz')
                    write(args.task/'certified.json',result)
                    if cfg['labels']:
                        phase('Q_S');tree.deadline=time.monotonic()+cfg['metric_seconds'];rows,summary,ops=measure(tree)
                        with gzip.open(args.task/'labels.jsonl.gz','wt',encoding='utf-8') as stream:
                            for r in rows:stream.write(stable(r)+'\n')
                        write(args.task/'examples.json',examples(tree,rows,limit=2))
                        result.update(labels='MEASURED',summary=summary,metrics=ops,
                            root_contexts=[r for r in rows if r['node']==0],labels_sha256=sha(args.task/'labels.jsonl.gz'),
                            examples_sha256=sha(args.task/'examples.json'))
    except Exception as exc:
        import traceback
        result.update(status='error',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    result.update(elapsed_seconds=time.monotonic()-start,worker_python=sys.version,
        environment_threads={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')})
    write(args.task/'result.json',result)


if __name__=='__main__':main()
