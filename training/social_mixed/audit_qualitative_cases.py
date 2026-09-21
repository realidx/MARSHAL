"""Per-case LP audit of qualitative P under frozen per-world continuation values.

The broad envelope avoids inventing a numerical meaning for 'clearly favored'.
The contract audit additionally uses the existing B labeler's margin internally.
Neither certifies that a changed distribution is reachable from an old history.
"""
import itertools
import json
from collections import Counter
import numpy as np
from scipy.optimize import linprog
from training.social_mixed.reasoning_bank import load, PATH, sha
from training.b_sft.preference_contract import belief, B_MARGIN
from training.b_sft.social_bp_curriculum import acceptable, TOL
from training.b_sft.decision_policy import is_offer_response

NAMES={'want':1,'neutral':0,'avoid':-1}


def cells(case, task, mode):
    lab=case['labels'];worlds=np.asarray(lab['worlds']);inp=task['input']
    keep=np.ones(len(worlds),dtype=bool)
    for key,value in inp['own_preferences'].items():
        keep &= worlds[:,inp['player'],int(key.split('_')[1])]==NAMES[value]
    for q in lab['query_candidates']:
        keep &= np.isin(worlds[:,q['player'],q['goal']],[NAMES[n] for n in q['gold']['possible_preferences']])
    indices=np.flatnonzero(keep);ws=worlds[indices];base=[];options=[]
    for q in lab['query_candidates']:
        gold=q['gold'];support=gold['possible_preferences'];fav=gold['favored']
        masks={n:(ws[:,q['player'],q['goal']]==NAMES[n]).astype(float) for n in support}
        if len(support)<2:continue
        if fav!='undetermined':
            margin=B_MARGIN if mode=='b_contract' else 0.
            base.extend((masks[n]-masks[fav],-margin) for n in support if n!=fav)
        elif mode=='b_contract':
            branches=[]
            for top,runner in itertools.permutations(support,2):
                branch=[(masks[n]-masks[top],0.) for n in support if n!=top]
                branch.append((masks[top]-masks[runner],B_MARGIN+1e-9))
                branches.append(branch)
            options.append(branches)
    result=[]
    for combo in itertools.product(*options):
        rows=base+[r for branch in combo for r in branch]
        A=np.array([r[0] for r in rows]) if rows else None
        b=np.array([r[1] for r in rows]) if rows else None
        test=solve(np.zeros(len(indices)),A,b)
        if test is not None:result.append((A,b))
    if not result:raise ValueError('Empty qualitative region: '+case['canonical_id'])
    return indices,result


def solve(objective,A,b,extra=()):
    n=len(objective)
    if extra:
        more=np.array([r[0] for r in extra]);bounds=np.array([r[1] for r in extra])
        A=more if A is None else np.vstack([A,more]);b=bounds if b is None else np.r_[b,bounds]
    r=linprog(objective,A_ub=A,b_ub=b,A_eq=np.ones((1,n)),b_eq=[1.],bounds=(0,None),method='highs',
              options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    if r.status==2:return None
    if not r.success:raise RuntimeError(r.message)
    return r.x


def matches(weights,case,mode):
    worlds=np.asarray(case['labels']['worlds'])
    for q in case['labels']['query_candidates']:
        mass={n:float(weights[worlds[:,q['player'],q['goal']]==v].sum()) for n,v in NAMES.items()}
        target=q['gold']
        if mode=='b_contract':
            if belief(mass)!=target:return False
        else:
            if {n for n,v in mass.items() if v>0}!=set(target['possible_preferences']):return False
            f=target['favored']
            if f!='undetermined' and any(mass[f]<=mass[n] for n in target['possible_preferences'] if n!=f):return False
    return True


def audit_case(case,task,mode):
    lab=case['labels'];inp=task['input'];actor=inp['player'];actions=inp['legal_actions']
    indices,regions=cells(case,task,mode);pay=np.asarray(lab['per_world_payoffs'])[:,indices,:]
    own=pay[:,:,actor];social=pay.sum(axis=2)-own;response=is_offer_response(actions)
    original=np.asarray(lab['posterior']);original_set=set(acceptable(lab['action_values'],actor,actions=actions))
    if 'teacher' in task:
        if {json.dumps(actions[a],sort_keys=True) for a in original_set} != {json.dumps(a,sort_keys=True) for a in task['teacher']['acceptable_actions']}:
            raise ValueError('Source reward does not match audited convention')
    if response and len(actions)!=2:raise ValueError('Response feasibility proof expects two responses')
    candidates=[];max_regret=np.zeros(len(actions));max_tie_social=np.zeros(len(actions))
    for a in range(len(actions)):
        for j in range(len(actions)):
            if a==j:continue
            diff=own[j]-own[a]
            for A,b in regions:
                x=solve(-diff,A,b);value=float(diff@x)
                max_regret[a]=max(max_regret[a],value)
                if value>.1+TOL:candidates.append(x)
                if response:
                    gap=social[j]-social[a]
                    x=solve(-gap,A,b,[(diff,TOL),(-diff,TOL)])
                    if x is not None:
                        value=float(gap@x);max_tie_social[a]=max(max_tie_social[a],value)
                        if value>.1+TOL:candidates.append(x)
        # Feasibility of own-tolerance acceptance; conservative for response ties.
        extra=[(own[j]-own[a],.1+TOL) for j in range(len(actions)) if j!=a]
        for A,b in regions:
            objective=(social[1-a]-social[a]) if response else sum((own[j]-own[a] for j in range(len(actions))), np.zeros(len(indices)))
            x=solve(objective,A,b,extra)
            if x is not None:candidates.append(x)
    robust=[a for a in range(len(actions)) if max_regret[a]<=.1+TOL and max_tie_social[a]<=.1+TOL]
    witnesses=[];seen=set();observed_accepted=set(original_set);observed_rejected=set(range(len(actions)))-original_set
    for x in candidates:
        full=np.zeros(len(original));full[indices]=x
        # Move off LP closure boundaries to positive support/strict favored.
        # Only independently revalidated points are reported as witnesses.
        for mix in (1e-5,.001,.01):
            w=(1-mix)*full+mix*original
            if not matches(w,case,mode):continue
            vals=np.einsum('awp,w->ap',np.asarray(lab['per_world_payoffs']),w)
            accepted=set(acceptable(vals,actor,actions=actions))
            observed_accepted.update(accepted);observed_rejected.update(set(range(len(actions)))-accepted)
            key=tuple(sorted(accepted))
            if accepted!=original_set and key not in seen:
                seen.add(key);witnesses.append(dict(weights=w.tolist(),values=vals.tolist(),acceptable_indices=list(key),
                    disjoint_from_original=accepted.isdisjoint(original_set),same_numeric_B_contract=matches(w,case,'b_contract')))
    always_rejected=[]
    for a in range(len(actions)):
        if a in observed_accepted:continue
        feasible=False
        extra=[(own[j]-own[a],.1+TOL) for j in range(len(actions)) if j!=a]
        for A,b in regions:
            x=solve(np.zeros(len(indices)),A,b,extra)
            if x is None:continue
            if not response:feasible=True;break
            j=1-a;diff=own[j]-own[a];gap=social[j]-social[a]
            # Exact two-response acceptance is a union: no own-value tie,
            # or the other's social advantage is within tolerance.
            hi=solve(-diff,A,b,extra);lo=solve(diff,A,b,extra)
            social_ok=solve(np.zeros(len(indices)),A,b,extra+[(gap,.1+TOL)])
            if float(diff@hi)>TOL or float(diff@lo)<-TOL or social_ok is not None:
                feasible=True;break
        if not feasible:always_rejected.append(a)
    exact_invariant=original_set==set(robust) and len(robust)+len(always_rejected)==len(actions)
    status=('reward_label_changes_witnessed' if witnesses else 'reward_labels_invariant_in_envelope' if exact_invariant
            else 'original_positive_labels_robust_negative_labels_unresolved' if original_set<=set(robust)
            else 'unresolved_boundary_or_response_tie')
    return dict(mode=mode,status=status,worlds_considered=len(indices),convex_regions=len(regions),
                original_acceptable_indices=sorted(original_set),universally_acceptable_indices=robust,
                original_positive_labels_all_robust=original_set<=set(robust),
                worst_own_regret_by_action=max_regret.tolist(),worst_response_tie_social_gap=max_tie_social.tolist(),
                always_rejected_indices=always_rejected,
                disjoint_action_witness=any(w['disjoint_from_original'] for w in witnesses),witnesses=witnesses)


def audit():
    tasks={t['canonical_id']:t for s in ('train','validation') for t in load(s) if t['paired_view']=='Pplus'}
    rows=[]
    for split in ('train','validation'):
        for case in load(split,'cases.jsonl'):
            task=tasks[case['canonical_id']]
            row=dict(canonical_id=case['canonical_id'],split=split,family=case['family'],
                     source_task_id=case['source_task_id'],
                     qualitative_beliefs=task['input']['supplied_belief']['semantic_beliefs'],
                     legal_actions=task['input']['legal_actions'],
                     all_immediate_actions_terminal=all(x['terminal'] for x in case['labels']['immediate_transitions']))
            for mode in ('text_envelope','b_contract'):row[mode]=audit_case(case,task,mode)
            rows.append(row)
            if len(rows)%25==0:print('audited',len(rows),flush=True)
    payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode()
    (PATH/'qualitative_case_audit.jsonl').write_bytes(payload)
    report=dict(cases=len(rows),audit_sha256=sha(payload),
        auditor_sha256=sha(__import__('pathlib').Path(__file__).read_bytes()),
        bank_manifest_sha256_at_audit=sha((PATH/'manifest.json').read_bytes()),
        numerical_method='SciPy HiGHS LP, primal/dual feasibility tolerance 1e-9; finite-precision certificates, not exact rational proofs',
        scope='LP extrema over available teacher world universe, with explicit own preferences and all qualitative supports; per-world continuation values held fixed. Certificates are scoped to this model, not a proof of reachable alternative histories or re-equilibrated future policy.',
        text_envelope='Favored strictly leads; undetermined has no numerical constraint. Closure used for conservative robustness bounds. This deliberately overapproximates unspecified natural-language strength.',
        b_contract='Existing B_MARGIN is used only internally. Undetermined is a union of top/runner-up regions. No numbers added to model beliefs.',
        summaries={mode:dict(statuses=dict(Counter(r[mode]['status'] for r in rows)),
            original_positive_labels_robust=sum(r[mode]['original_positive_labels_all_robust'] for r in rows),
            has_universally_acceptable_action=sum(bool(r[mode]['universally_acceptable_indices']) for r in rows),
            disjoint_witness_cases=sum(r[mode]['disjoint_action_witness'] for r in rows),
            witness_cases_by_split=dict(Counter(r['split'] for r in rows if r[mode]['witnesses'])))
            for mode in ('text_envelope','b_contract')})
    (PATH/'qualitative_case_audit_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return rows,report

if __name__=='__main__':audit()
