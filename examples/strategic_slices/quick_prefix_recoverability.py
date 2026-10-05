"""Exact sequence-form compatibility of bounded-optimal prefixes and terminal value.

Fixed terminal-reference opponents for terminal assessment. The bounded prefix
objective retains its original bounded-reference opponents/continuation.
A sparse realization-plan LP searches ALL information-respecting focal policies,
including all bounded-optimal ties, then optimizes the remaining own decisions.
This diagnoses achievable value under specified opponents, not physical impossibility
under every possible opponent. No perfect-information access is given to the focal.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json,os,subprocess,sys,time
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix,vstack
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import replay_node,write_json,file_hash
from training.strategic_slices.values import extreme_value
from training.strategic_slices.diagnose_bounded import root_entrances
from training.strategic_slices.freeze import source_identity
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights


def worker(out,index):
    case=json.loads((out/'cases.json').read_text())[index]
    rules=PrivateInvestigationRules(case['raw']);node=replay_node(rules,case['history'])
    prior=world_weights(rules.worlds,case['raw']['background_prior'])
    short=BoundedPrivateWindow(rules,node,rules.worlds,world_weights=prior,lookahead_rr=1,max_nodes=20000,seconds=12).solve()
    full=BoundedPrivateWindow(rules,node,rules.worlds,world_weights=prior,lookahead_rr=len(rules.spec.round_robin),max_nodes=20000,seconds=12).solve()
    short.audit_native();full.audit_native()
    assert all(e.node.state.is_terminal for e in full.entries if e.actor is None)
    entrance=root_entrances(short)[0];ego=entrance['ego'];weights=np.array(entrance['entry_world_weights'])
    active=np.flatnonzero(weights>0)
    # Map identical public action histories, retaining every separate history.
    mapping={};stack=[(0,0)]
    while stack:
        bi,ti=stack.pop();mapping[bi]=ti;b,t=short.entries[bi],full.entries[ti]
        if b.actor is not None:
            assert [a.to_dict() for a in b.actions]==[a.to_dict() for a in t.actions]
            stack.extend(zip(b.children,t.children))
    # Realization sequence at each history/world. Perfect recall implies that
    # all worlds in one own information cell have the same preceding sequence.
    last={0:np.zeros(full.w,dtype=int)};exogenous={0:weights.copy()}
    rowids=[0];cols=[0];coeffs=[1.];rhs=[1.];nvars=1;cells={};terminal={}
    for ti,t in enumerate(full.entries):
        if t.actor is None:
            for wi in active:
                seq=int(last[ti][wi]);terminal[seq]=terminal.get(seq,0.)+exogenous[ti][wi]*t.payoff[wi,ego]
            continue
        for child in t.children:last[child]=last[ti].copy()
        if t.actor==ego:
            groups=[]
            for group in full.information_groups[ti]:
                ids=np.intersect1d(group,active)
                if not len(ids):continue
                parent=int(last[ti][ids[0]]);assert np.all(last[ti][ids]==parent)
                variables=np.arange(nvars,nvars+len(t.actions));nvars+=len(t.actions)
                row=len(rhs);rhs.append(0.)
                rowids.extend([row]*(len(variables)+1));cols.extend([parent,*variables]);coeffs.extend([-1.,*([1.]*len(variables))])
                for ai,child in enumerate(t.children):last[child][ids]=variables[ai]
                groups.append((ids,parent,variables))
            cells[ti]=groups
        for ai,child in enumerate(t.children):
            exogenous[child]=exogenous[ti] if t.actor==ego else exogenous[ti]*full.policy[ti][ai]
    A=coo_matrix((coeffs,(rowids,cols)),shape=(len(rhs),nvars)).tocsr();rhs=np.array(rhs)
    terminal_c=np.zeros(nvars)
    for seq,v in terminal.items():terminal_c[seq]=v
    def solve(objective,primary=None,target=None,extra=None):
        eq,erhs=(A,rhs) if extra is None else (vstack([A,extra]),np.r_[rhs,np.zeros(extra.shape[0])])
        result=linprog(-objective,A_eq=eq,b_eq=erhs,
            A_ub=None if primary is None else coo_matrix(-primary.reshape(1,-1)).tocsr(),
            b_ub=None if primary is None else [-target+1e-9],bounds=(0,None),method='highs',
            options=dict(time_limit=8,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
        if not result.success:raise RuntimeError(result.message)
        assert np.max(np.abs(eq@result.x-erhs))<1e-7
        if primary is not None:assert primary@result.x>=target-1e-7
        return result.x,float(objective@result.x)
    def recover(x):
        policy={}
        for ti,groups in cells.items():
            p=full.policy[ti].copy()
            for ids,parent,variables in groups:
                q=np.maximum(x[variables],0.)
                q=q/q.sum() if q.sum()>1e-12 else np.eye(1,len(variables),0)[0]
                p[:,ids]=q[:,None]
            policy[ti]=p
        return policy
    def evaluate(tree,policy,k=None):
        counts={0:0}
        for i,e in enumerate(tree.entries):
            for child in e.children:counts[child]=counts[i]+int(e.actor==ego)
        values={}
        for i in reversed(range(len(tree.entries))):
            e=tree.entries[i]
            if e.actor is None:values[i]=e.payoff[:,ego];continue
            controlled=e.actor==ego and (k is None or counts[i]<k)
            p=policy[mapping[i] if tree is short else i] if controlled else tree.policy[i]
            values[i]=np.einsum('aw,aw->w',p,np.stack([values[c] for c in e.children]))
        return float(weights@values[0])
    _,benchmark=solve(terminal_c)
    direct=extreme_value(full,ego,0,weights,100)['value']
    assert abs(benchmark-direct)<1e-7
    report=dict(case=case,entrance=entrance,players=rules.spec.n_players,
        terminal_best=benchmark,cutoffs=dict(bounded=short.cutoff,terminal=full.cutoff),
        sequence_variables=nvars,information_constraints=len(rhs)-1,rows=[],
        bounded_certificate=short.certificate,terminal_certificate=full.certificate)
    for k in (1,2,3):
        primary=np.zeros(nvars);reach={0:weights.copy()};counts={0:0}
        for bi,b in enumerate(short.entries):
            if bi not in reach:continue
            if counts[bi]>=k or b.actor is None:
                for wi in active:primary[last[mapping[bi]][wi]]+=reach[bi][wi]*short.values[bi][wi,ego]
                continue
            for ai,child in enumerate(b.children):
                counts[child]=counts[bi]+int(b.actor==ego)
                reach[child]=reach[bi] if b.actor==ego else reach[bi]*short.policy[bi][ai]
        original=extreme_value(short,ego,0,weights,k)
        _,bounded_best=solve(primary);assert abs(bounded_best-original['value'])<1e-7
        x,compatible=solve(terminal_c,primary,bounded_best)
        policy=recover(x)
        assert abs(evaluate(full,policy)-compatible)<1e-6
        assert abs(evaluate(short,policy,k)-bounded_best)<1e-6
        # A concrete canonical optimum (the existing DP's tie convention), with
        # an optimal terminal continuation. No claim that it is the worst tie.
        ri=[];ci=[];vs=[];rn=0
        for bi,p in original['policy'].items():
            ti=mapping[bi]
            for ids,parent,variables in cells[ti]:
                probs=p[:,ids[0]]
                assert np.allclose(p[:,ids],probs[:,None])
                for var,prob in zip(variables,probs):
                    ri.extend([rn,rn]);ci.extend([int(var),parent]);vs.extend([1.,-float(prob)]);rn+=1
        extra=coo_matrix((vs,(ri,ci)),shape=(rn,nvars)).tocsr()
        cx,canonical=solve(terminal_c,extra=extra)
        cp=recover(cx)
        assert abs(evaluate(full,cp)-canonical)<1e-6
        assert abs(evaluate(short,cp,k)-bounded_best)<1e-6
        root_policy=policy[0][:,active]@weights[active]
        canonical_root=cp[0][:,active]@weights[active]
        report['rows'].append(dict(k=k,bounded_best=bounded_best,
            best_terminal_with_bounded_optimal_prefix=compatible,
            unavoidable_loss=max(0.,benchmark-compatible),
            canonical_prefix_best_terminal=canonical,canonical_loss=max(0.,benchmark-canonical),
            compatible_root_probabilities=root_policy.tolist(),canonical_root_probabilities=canonical_root.tolist(),
            independent_policy_replay_verified=True))
    report.update(status='verified',root_actions=[a.to_dict() for a in full.entries[0].actions])
    write_json(out/f'result_{index}.json',report)


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--output',type=Path,required=True);cli.add_argument('--worker',type=int)
    args=cli.parse_args();out=args.output.resolve()
    if args.worker is not None:worker(out,args.worker);return
    start=time.monotonic();sources=source_identity();cases=json.loads((out/'cases.json').read_text())
    def run(index):
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        with (out/f'worker_{index}.log').open('w') as log:
            try:
                p=subprocess.run([sys.executable,__file__,'--output',str(out),'--worker',str(index)],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=45)
                status='failed' if p.returncode else 'verified'
            except subprocess.TimeoutExpired:status='timeout'
        return json.loads((out/f'result_{index}.json').read_text()) if status=='verified' else dict(case=cases[index],status=status)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(len(cases))))
    write_json(out/'summary.json',dict(seconds=time.monotonic()-start,source_sha256=sources,
        source_unchanged=sources==source_identity(),script_sha256=file_hash(__file__),cases_sha256=file_hash(out/'cases.json'),
        protocol=__doc__,per_case_seconds=45,results=results))
    print([(r['case']['name'],r['status']) for r in results])


if __name__=='__main__':main()
