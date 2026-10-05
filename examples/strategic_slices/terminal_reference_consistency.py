"""Compare initial-game and re-solved terminal references at identical reached beliefs."""
import argparse,json,os,subprocess,sys,time
from copy import copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from training.strategic_slices.build import sample_parent
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.diagnose_bounded import count_bounded_nodes,root_entrances
from training.strategic_slices.common import write_json,save_reference
from training.strategic_slices.values import window_values,masked_answer_value
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights


def metrics(tree,root,ego,weights,k):
    result=window_values(tree,ego,root,weights,k);infos=[]
    for a in tree.entries[root].actions:
        a=a.to_dict()
        if a.get('action')!='INVESTIGATE':continue
        slot=(a['player'],a['goal'])
        if len({w[slot[0]][slot[1]] for w,m in zip(tree.worlds,weights) if m>0})<=1:s=0.
        else:s=masked_answer_value(tree,ego=ego,root_index=root,root_weights=weights,query_slot=slot,k=k)['S']
        infos.append(dict(slot=slot,S=s))
    return dict(result,information_values=infos,S_max=max((x['S'] for x in infos),default=0.))


def worker(out,i):
    case=json.loads((out/'cases.json').read_text())[i];raw=case['raw'];start=time.monotonic()
    rules=PrivateInvestigationRules(raw);prior=world_weights(rules.worlds,raw['background_prior'])
    depth=len(rules.spec.round_robin);budget=dict(lookahead_rr=depth,max_nodes=30000,seconds=8)
    count=count_bounded_nodes(rules,rules.initial(),depth)['unfolded_public_history_nodes']
    if count>30000:
        write_json(out/f'result_{i}.json',dict(case=case,status='node_budget',nodes=count));return
    full=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,world_weights=prior,**budget).solve()
    full_audit=full.audit_native();assert full_audit['cutoff_leaves']==0
    save_reference(out/f'full_{i}.npz',full)
    reach={0:prior.copy()};histories={0:[]};eligible=[]
    for j,e in enumerate(full.entries):
        if e.actor is None:continue
        if j and e.node.pending is None and 1<=depth-e.node.state.turn_index<=3 and reach[j].sum()>1e-8:
            eligible.append(j)
        for ai,child in enumerate(e.children):
            reach[child]=reach[j]*full.policy[j][ai];histories[child]=histories[j]+[ai]
    # Earliest reached proposal boundary first, then largest reach; no C/S-based selection.
    selected=sorted(eligible,key=lambda j:(full.entries[j].node.state.turn_index,-reach[j].sum(),histories[j]))[:2]
    pairs=[]
    for ei,j in enumerate(selected):
        mass=reach[j];active=np.flatnonzero(mass>0);belief=mass[active]/mass.sum()
        worlds=[full.worlds[int(w)] for w in active]
        fresh=BoundedPrivateWindow(rules,full.entries[j].node,worlds,world_weights=belief,**budget).solve()
        audit=fresh.audit_native();assert audit['cutoff_leaves']==0
        save_reference(out/f'fresh_{i}_{ei}.npz',fresh)
        # Independent indexing/belief check: transplant the original subtree
        # policy onto the freshly constructed tree, without re-solving it.
        inherited=copy(fresh);inherited.policy={};stack=[(j,0)]
        while stack:
            oldidx,newidx=stack.pop();oldentry,newentry=full.entries[oldidx],fresh.entries[newidx]
            assert [a.to_dict() for a in oldentry.actions]==[a.to_dict() for a in newentry.actions]
            if oldentry.actor is None:
                np.testing.assert_allclose(oldentry.payoff[active],newentry.payoff,atol=1e-10)
            else:
                inherited.policy[newidx]=full.policy[oldidx][:,active].copy()
                stack.extend(zip(oldentry.children,newentry.children))
        # Compare both references with exactly the same root information-cell weights.
        rows=[]
        for cell in root_entrances(fresh):
            weights=np.array(cell['entry_world_weights']);padded=np.zeros(full.w);padded[active]=weights
            oldprev=newprev=old_s=new_s=0.
            for k in (1,2,3):
                old=metrics(full,j,cell['ego'],padded,k);new=metrics(fresh,0,cell['ego'],weights,k)
                replay=metrics(inherited,0,cell['ego'],weights,k)
                for key in ('V_star','V_min','C_span','S_max','root_Q'):
                    np.testing.assert_allclose(old[key],replay[key],atol=1e-8,rtol=0)
                old['selected']=old['C_span']>.1 and (k==1 or old['C_span']-oldprev>.05 or old['S_max']-old_s>.05)
                new['selected']=new['C_span']>.1 and (k==1 or new['C_span']-newprev>.05 or new['S_max']-new_s>.05)
                oldprev,newprev=old['C_span'],new['C_span']
                if old['C_span']>.1:old_s=old['S_max']
                if new['C_span']>.1:new_s=new['S_max']
                rows.append(dict(k=k,own=cell['own'],private_results=cell['private_results'],
                    full_world_weights=padded.tolist(),fresh_world_weights=weights.tolist(),full=old,fresh=new))
        pairs.append(dict(history=histories[j],public_reach=float(mass.sum()),active_world_indices=active.tolist(),
            posterior=belief.tolist(),inherited_policy_replay_verified=True,certificate=fresh.certificate,audit=audit,rows=rows))
    write_json(out/f'result_{i}.json',dict(case=case,status='verified',nodes=count,seconds=time.monotonic()-start,
        full_certificate=full.certificate,full_audit=full_audit,pairs=pairs))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',type=int)
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
    if a.worker is not None:worker(out,a.worker);return
    cases=[dict(name=f'random_{i}',raw=sample_parent(2026100500+i,2 if i<3 else 3,rounds=1)) for i in range(6)]
    # Original two-round fixture is attempted honestly under the same node budget.
    cases.append(dict(name='original-investigation',raw=json.loads(Path('examples/strategic_slices/fixtures/information_acquisition.json').read_text())['raw']))
    write_json(out/'cases.json',cases);start=time.monotonic()
    def launch(i):
        with (out/f'worker_{i}.log').open('w') as log:
            try:
                r=subprocess.run([sys.executable,__file__,'--output',str(out),'--worker',str(i)],stdout=log,stderr=subprocess.STDOUT,timeout=35,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                status='failed' if r.returncode else 'done'
            except subprocess.TimeoutExpired:status='hard_timeout'
        if status=='done':return json.loads((out/f'result_{i}.json').read_text())
        log=(out/f'worker_{i}.log').read_text()
        if 'SearchLimit: Shared teacher wall budget exceeded' in log:status='solver_time_budget'
        return dict(case=cases[i],status=status,oracle_label=None,log=f'worker_{i}.log')
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,range(len(cases))))
    rows=[r for c in results if c['status']=='verified' for p in c['pairs'] for r in p['rows']]
    stats=dict(comparisons=len(rows),C_changed=sum(abs(r['full']['C_span']-r['fresh']['C_span'])>1e-6 for r in rows),
        S_changed=sum(abs(r['full']['S_max']-r['fresh']['S_max'])>1e-6 for r in rows),
        selection_changed=sum(r['full']['selected']!=r['fresh']['selected'] for r in rows),
        positive_S_full=sum(r['full']['S_max']>.05 for r in rows),positive_S_fresh=sum(r['fresh']['S_max']>.05 for r in rows))
    write_json(out/'summary.json',dict(scope='Small one-round random games plus original investigation fixture. Reached histories only; exact Bayesian posterior from full reference action likelihoods, shared by both arms. Not a guarantee of a unique/sequential equilibrium or general equivalence.',seconds=time.monotonic()-start,stats=stats,results=results))
    print([(r['case']['name'],r['status']) for r in results]);print(stats)

if __name__=='__main__':main()
