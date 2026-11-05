"""Same current-node omission contract, skip undefined zero-CF diagnostic rows."""
from collections import defaultdict
import numpy as np

from new.node_qs_audit_v1_20261023.metrics import (
    Observations,contingent_values,full_context,forest_response,EPS,
)
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.equilibrium import _reach
from new.node_qs_audit_v1_20261023.run import summarize


def measure(tree):
    baseline=tree.evaluate();joint=[None]*len(tree.entries);joint[0]=tree.world_weights.copy()
    for i,e in enumerate(tree.entries):
        for ai,ch in enumerate(e.children):joint[ch]=joint[i]*tree.policy[i][ai]
    rows=[];zero=0;total=0;forests=0;forest_nodes=0
    for focal in range(tree.n):
        tree._check();reach=_reach(tree,focal);values=contingent_values(tree,focal,reach)
        observations=Observations(tree,focal);tasks=defaultdict(lambda:defaultdict(list));local=[]
        for i,e in enumerate(tree.entries):
            if i%256==0:tree._check()
            if e.actor!=focal:continue
            for cell,ids in enumerate(tree.information_groups[i]):
                total+=1
                if reach[i][ids].sum()==0:zero+=1;continue
                r=full_context(tree,i,ids,reach[i],joint[i],values,baseline);r['cell']=cell;local.append(r)
                masks=[('private',p,g) for p,g in observed_slots(e.node,focal)]
                masks += [('history',ev.turn_index) for ev in e.node.state.transcript]
                for mask in masks:tasks[mask][observations.key(i,int(ids[0]),mask)].append(r)
        for mask,groups in sorted(tasks.items()):
            for members in groups.values():
                tree._check()
                if len(members)==1:
                    members[0]['S_items'].append(dict(omitted=list(mask),S=0.,full_contexts=1));continue
                roots={}
                for r in members:roots.setdefault(r['node'],np.zeros(tree.w))[r['world_ids']]=reach[r['node']][r['world_ids']]
                result=forest_response(tree,focal,roots,omitted=mask,observations=observations)
                forests+=1;forest_nodes+=result['nodes']
                for r in members:
                    i=r['node'];ids=r['world_ids'];posterior=np.array(r['posterior'])
                    v=posterior@result['values'][i][ids];full=max(r['Q']);loss=full-float(v[focal])
                    assert loss>=-EPS,(i,mask,loss)
                    probs=result['root_policy'][i][:,ids[int(np.flatnonzero(posterior>0)[0])]]
                    item=dict(omitted=list(mask),S=max(0.,loss),V_full=full,V_omitted=float(v[focal]),
                        omitted_action_probabilities=probs.tolist(),full_contexts=len(members),
                        entry_action_regret=max(0.,full-float(probs@r['Q'])),
                        response_secondary_loss=(max(0.,max(r['Q_others'][a] for a in r['own_optimal'])-float(v.sum()-v[focal]))
                            if r['phase']=='response' and loss<=EPS else None),replay_verified=True)
                    r['S_items'].append(item)
                    channel='S_private' if mask[0]=='private' else 'S_history';r[channel]=max(r[channel],max(0.,loss))
        rows.extend(local)
    rows.sort(key=lambda r:(r['node'],r['cell']))
    summary=summarize(rows);summary.update(all_cells=total,zero_CF_cells=zero,S_zero_CF='UNAVAILABLE_NOT_ZERO')
    for scope in ('counterfactual','on_reference'):
        for field in ('proposal_spans','positive_distinct_gaps'):
            data=summary[scope].pop(field)
            summary[scope][field+'_quantiles']=(np.quantile(data,[0,.25,.5,.75,1]).tolist() if data else None)
        selected=[r for r in rows if scope=='counterfactual' or r['reference_mass']>0]
        for channel in ('private','history'):
            summary[scope][channel+'_entry_action_positive']=sum(any(x['omitted'][0]==channel
                and x.get('entry_action_regret',0)>EPS for x in r['S_items']) for r in selected)
    return rows,summary,dict(nontrivial_forests=forests,forest_nodes=forest_nodes,
        omitted_policy_remaining_ties='uniform',information='current-node omission, not pre-answer acquisition value')
