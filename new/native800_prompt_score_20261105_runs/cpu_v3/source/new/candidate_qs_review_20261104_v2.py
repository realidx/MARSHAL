"""Additional diagnostic: unavoidable current loss after hiding a private answer.

This is a relaxation lower bound, not a replacement for S or an admission
threshold. After the forced current action, full information is restored.
"""
from collections import Counter,defaultdict
import numpy as np
from new import candidate_qs_review_20261104 as base

original_case=base.summarize_case
original_aggregate=base.aggregate
original_snapshot=base.m.snapshot


def summarize_case(key,arm,rows,result,job):
    case,examples=original_case(key,arm,rows,result,job)
    groups=defaultdict(list)
    for row in rows:
        if row['counterfactual_mass']<=0:continue
        for item in row['S_items']:
            mask=item['omitted']
            if mask[0]!='private' or item['full_contexts']<=1:continue
            other=tuple(tuple(x)for x in row['private_answers']if x[:2]!=mask[1:])
            group=(row['actor'],row['node'],tuple(row['own_type']),other,tuple(mask))
            groups[group].append((row,item))
    counts=Counter();witness=None
    for group,members in groups.items():
        assert all(item['full_contexts']==len(members)for row,item in members)
        weights=np.array([row['counterfactual_mass']for row,item in members]);weights/=weights.sum()
        values=np.array([row['Q']for row,item in members]);full=float(weights@values.max(axis=1))
        coarse=float((weights@values).max());bound=max(0.,full-coarse)
        total_loss=float(weights@np.array([item['S']for row,item in members]))
        current=float(weights@np.array([item['own_current_loss']for row,item in members]))
        assert bound<=current+base.m.EPS and current<=total_loss+base.m.EPS
        common=set.intersection(*(set(row['own_optimal'])for row,item in members))
        counts['ambiguous_groups']+=1
        positive=bound>base.m.EPS;counts['positive_bound_groups']+=positive
        counts['disjoint_full_own_optima_groups']+=not common
        counts['positive_bound_'+members[0][0]['phase']+'_groups']+=positive
        counts['relative_Q_changed_zero_bound_groups']+=bound<=base.m.EPS and any(item['relative_Q_change_Linf']>base.m.EPS for row,item in members)
        if positive and witness is None:
            witness=dict(node=group[1],focal=group[0],omitted=list(group[-1]),
                cells=[row['cell']for row,item in members],weights=weights.tolist(),full_Q=values.tolist(),
                common_own_optimal=sorted(common),current_loss_lower_bound=bound,
                actual_canonical_current_loss=current,actual_total_S_average=total_loss,
                definition='Full information restored after current action; fixed-reference counterfactual weights')
    case['private_group_bound']=dict(counts= dict(counts),first_positive_witness=witness)
    return case,examples


def aggregate(cases):
    out=original_aggregate(cases);counts=Counter()
    for case in cases:counts.update(case['private_group_bound']['counts'])
    ranked=sorted(cases,key=lambda x:(-x['private_group_bound']['counts'].get('positive_bound_groups',0),x['key']))
    total=counts['positive_bound_groups']
    out['private_current_loss_lower_bound']=dict(counts=dict(counts),
        positive_parents=sum(x['private_group_bound']['counts'].get('positive_bound_groups',0)>0 for x in cases),
        top2=[dict(key=x['key'],groups=x['private_group_bound']['counts'].get('positive_bound_groups',0))for x in ranked[:2]],
        top2_group_share=sum(x['private_group_bound']['counts'].get('positive_bound_groups',0)for x in ranked[:2])/total if total else None,
        scope='Per private-answer omission group; not context count, not new S or modelD')
    return out


def snapshot(out,config,identities):
    base.m.VERSION='candidate-qs-parent-review-v2'
    base.m.REG=base.m.ROOT/'examples/strategic_slices/versions/candidate_qs_parent_review_v2_20261104/SNAPSHOT.json'
    config=dict(config,private_group_diagnostic=dict(
        formula='sum_g w_g max_a Q_g(a) - max_a sum_g w_g Q_g(a)',
        interpretation='Lower bound on weighted omission loss: full information restored after the current decision',
        weights='Same frozen-reference CF masses, exclude own past choice likelihood',
        remaining_tie_independent='Bound independent of chosen canonical omitted optimal mixture; reference still fixed',
        scope='Private answers only; no history grouping shortcut',
        selection='NOT_USED_AS_ADMISSION_THRESHOLD'))
    return original_snapshot(out,config,identities)


base.summarize_case=summarize_case
base.aggregate=aggregate
base.m.snapshot=snapshot

if __name__=='__main__':base.main()
