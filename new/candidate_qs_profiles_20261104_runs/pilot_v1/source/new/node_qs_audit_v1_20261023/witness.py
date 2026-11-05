"""Independent sequence LP and conservative tie-robust bounds on actual S.

Bounds range over ALL own-payoff-optimal omitted policies, relaxing secondary
response constraints. Thus a positive lower S bound cannot be explained by
our uniform choice among omitted-policy ties. This does not change main labels.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, vstack, csr_matrix

from .metrics import Observations, stage, forest_response
from .run import inputs, snapshot
from new.sparse_solver_v1_20261023.common import parents, write, sha
from new.sparse_solver_v1_20261023.probe import build
from training.strategic_slices.equilibrium import _reach


def sequence_lp(tree, focal, roots, *, omitted, observations, target=None):
    total=sum(float(m.sum()) for m in roots.values())
    reach={i:m/total for i,m in roots.items()}
    last={i:np.zeros(tree.w,dtype=int) for i in roots}
    origin={i:i for i in roots};nodes=[];seen=set();todo=list(roots)
    while todo:
        i=todo.pop()
        if i in seen:raise ValueError('Roots overlap')
        seen.add(i);nodes.append(i);todo.extend(tree.entries[i].children)
    rr=[0];cc=[0];vv=[1.];rhs=[1.];cells={};nvars=1
    objective=defaultdict(float);target_objective=defaultdict(float)
    target_mass=1. if target is None else float(roots[target[0]][list(target[1])].sum()/total)
    assert target_mass>0
    for i in sorted(nodes,key=lambda j:stage(tree.entries[j])):
        entry=tree.entries[i]
        if entry.actor is None:
            for wi in np.flatnonzero(reach[i]>0):
                seq=int(last[i][wi]);value=float(reach[i][wi]*entry.payoff[wi,focal])
                objective[seq]+=value
                if target and origin[i]==target[0] and wi in target[1]:
                    target_objective[seq]+=value/target_mass
            continue
        for ch in entry.children:last[ch]=last[i].copy();origin[ch]=origin[i]
        if entry.actor==focal:
            for wi in np.flatnonzero(reach[i]>0):
                parent=int(last[i][wi]);key=(parent,observations.key(i,int(wi),omitted))
                if key not in cells:
                    seqs=tuple(range(nvars,nvars+len(entry.actions)));nvars+=len(entry.actions)
                    r=len(rhs);rhs.append(0.)
                    rr.extend([r]*(1+len(seqs)));cc.extend([parent,*seqs]);vv.extend([-1.,*([1.]*len(seqs))])
                    cells[key]=seqs
                seqs=cells[key]
                for ai,ch in enumerate(entry.children):last[ch][wi]=seqs[ai]
        for ai,ch in enumerate(entry.children):
            reach[ch]=reach[i].copy() if entry.actor==focal else reach[i]*tree.policy[i][ai]
    A=coo_matrix((vv,(rr,cc)),shape=(len(rhs),nvars)).tocsr();b=np.array(rhs)
    c=np.zeros(nvars);ct=np.zeros(nvars)
    for seq,value in objective.items():c[seq]=value
    for seq,value in target_objective.items():ct[seq]=value
    options=dict(primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9,time_limit=60.)
    def solve(obj,a=A,bb=b):
        result=linprog(obj,A_eq=a,b_eq=bb,bounds=(0,None),method='highs',options=options)
        if not result.success:raise RuntimeError(result.message)
        assert np.max(np.abs(a@result.x-bb))<1e-7
        return result
    optimum=solve(-c);v=float(c@optimum.x)
    result=dict(V_omitted_LP=v,variables=nvars,flow_residual=float(np.max(np.abs(A@optimum.x-b))),
                objective='own-payoff only; superset of response-social-admissible policies')
    if target:
        constrained=vstack([A,csr_matrix(c[None])],format='csr');bb=np.r_[b,v]
        high=solve(-ct,constrained,bb);low=solve(ct,constrained,bb)
        result.update(target_own_value_max=float(ct@high.x),target_own_value_min=float(ct@low.x))
    return result


def check_game(index,parent,identity,run,output):
    start=time.monotonic();tree=build(parent,seconds=60)
    assert sha(identity['path'])==identity['sha256']
    with np.load(identity['path']) as data:flat=data['probabilities']
    off=0
    for p in tree.policy:
        if p is not None:p[:]=flat[off:off+p.size].reshape(p.shape);off+=p.size
    assert off==len(flat);tree.deadline=float('inf')
    with gzip.open(run/'cases'/str(index)/'labels.jsonl.gz','rt') as stream:
        rows=[json.loads(line) for line in stream]
    checks=[]
    for channel in ('private','history'):
        # Prespecified one highest-S true context per channel per positive parent.
        candidates=[(item['S'],r,item) for r in rows for item in r['S_items']
                    if item['omitted'][0]==channel and item['S']>1e-8]
        if not candidates:continue
        _,chosen,item=max(candidates,key=lambda x:(x[0],x[1]['reference_mass'],-x[1]['node']))
        focal=chosen['actor'];mask=tuple(item['omitted']);obs=Observations(tree,focal)
        key=obs.key(chosen['node'],chosen['world_ids'][int(np.flatnonzero(np.array(chosen['posterior'])>0)[0])],mask)
        members=[r for r in rows if r['actor']==focal and r['counterfactual_mass']>0
            and any(tuple(x['omitted'])==mask for x in r['S_items'])
            and obs.key(r['node'],r['world_ids'][0],mask)==key]
        reach=_reach(tree,focal);roots={}
        for r in members:roots.setdefault(r['node'],np.zeros(tree.w))[r['world_ids']]=reach[r['node']][r['world_ids']]
        result=forest_response(tree,focal,roots,omitted=mask,observations=obs)
        total=sum(m.sum() for m in roots.values())
        dp=sum(float(m@result['values'][i][:,focal]) for i,m in roots.items())/total
        lp=sequence_lp(tree,focal,roots,omitted=mask,observations=obs,
            target=(chosen['node'],set(chosen['world_ids'])))
        assert abs(lp['V_omitted_LP']-dp)<1e-7,(lp,dp)
        full_lp=sequence_lp(tree,focal,roots,omitted=None,observations=obs)
        full=sum(r['counterfactual_mass']*max(r['Q']) for r in members)/total
        assert abs(full-full_lp['V_omitted_LP'])<1e-7
        full_actual=max(chosen['Q'])
        lower=max(0.,full_actual-lp['target_own_value_max']);upper=max(0.,full_actual-lp['target_own_value_min'])
        assert lower-1e-7<=item['S']<=upper+1e-7
        posteriors=[]
        for r in members:
            posterior=np.zeros(tree.w);posterior[r['world_ids']]=r['posterior'];posteriors.append(posterior)
        posterior_spread=max(float(np.abs(a-b).sum()) for a in posteriors for b in posteriors)
        check=dict(channel=channel,index=index,node=chosen['node'],cell=chosen['cell'],omitted=list(mask),
            focal=focal,reference_mass=chosen['reference_mass'],S_uniform=item['S'],
            S_lower_over_all_own_optimal_omitted_policies=lower,
            S_upper_over_all_own_optimal_omitted_policies=upper,
            independent_LP_matches_DP=True,full_information_LP_matches_Q=True,
            dp_value=dp,full_group_value=full,forest_roots=len(roots),full_contexts=len(members),
            full_preference_posterior_L1_spread=posterior_spread,**lp)
        checks.append(check)
    write(output/'cases'/str(index)/'checks.json',checks)
    print(dict(index=index,checks=len(checks),elapsed=round(time.monotonic()-start,2)),flush=True)
    return dict(index=index,checks=checks,elapsed=time.monotonic()-start)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();rows=json.loads((args.run/'results.json').read_text())
    indices=[r['index'] for r in rows if r['status']=='measured' and
        (r['summary']['counterfactual']['private_S_positive'] or r['summary']['counterfactual']['history_S_positive'])]
    identities=inputs('terminal')
    snapshot(args.output,dict(operation='Independent sequence LP and S tie-robust bounds on real positive witnesses',
        input_run=str(args.run),input_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        input_results_sha256=sha(args.run/'results.json'),indices=indices,workers=args.workers,
        witness_rule='One largest S per omission channel per positive parent, tie prefer reference reach',
        LP=dict(time_limit=60,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9),
        S_bounds='All own-optimal omitted policies; relaxing secondary social constraint gives conservative interval',
        model='NOT_USED',training='NOT_RUN'),{i:identities[i] for i in indices})
    from concurrent.futures import ProcessPoolExecutor,as_completed
    pool=parents();results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        fs=[executor.submit(check_game,i,pool[i],identities[i],args.run,args.output) for i in indices]
        for future in as_completed(fs):
            results.append(future.result());results.sort(key=lambda r:r['index']);write(args.output/'results.json',results)
    checks=[c for r in results for c in r['checks']]
    write(args.output/'COMPLETE.json',dict(parents=len(results),witnesses=len(checks),
        all_DP_LP_checks_passed=True,
        robust_positive_witnesses=sum(c['S_lower_over_all_own_optimal_omitted_policies']>1e-8 for c in checks),
        results_sha256=sha(args.output/'results.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
