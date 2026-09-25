"""Freeze 32 teacher-selected development diagnostics; no model outputs used."""
import csv
import hashlib
import json
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode, request
from new.diagnostic_v6.semantic_sufficiency import certify
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_private_teacher import audit_native

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def key(value):return json.dumps(value,sort_keys=True,separators=(',',':'))

def qualify(c):
    from training.social_mixed.structure_coverage import geometry_id
    c=deepcopy(c);task=c['task'];i=task['input'];t=task['teacher'];q=i['queries'][0]
    c['structure_family']=geometry_id(i['game'])
    c['mode']='binary' if all(g['binary'] for g in i['game']['goals']) else 'linear'
    ws=t['worlds'];actor=i['observer']
    unknown=[(p,g) for p in range(i['game']['n_players']) for g in range(len(i['game']['goals'])) if len({w[p][g] for w in ws})>1]
    if unknown!=[(q['player'],q['goal'])] or len(ws)!=3:
        raise ValueError('B query does not cover exactly all hidden preferences')
    st=i['current_state']
    # Normalize world axis explicitly: never assume catalogue ordering.
    indices=[next(j for j,w in enumerate(ws) if w[q['player']][q['goal']]==v) for v in (1,0,-1)]
    pay=np.array(t['per_world_payoffs'])[:,indices,:]
    cert=certify(t['gold'],pay.tolist(),actor)
    if not cert['decision_sufficient']:raise ValueError('Qualitative B is decision ambiguous')
    clean_initial=dict(commitments=st['commitments'],turn_index=st['turn_index'],
        investigation_remaining=st['investigation_remaining_by_player'],pending_offer=i['pending_offer'])
    fresh=InitialEpisode(c['raw'],clean_initial,seconds=10,max_nodes=30000,max_sweeps=128)
    entry=fresh.tree.entries[0]
    acts=[a.to_dict() for a in entry.actions]
    if acts!=i['legal_actions']:raise ValueError('Clean-state legal actions changed')
    fws=fresh.tree.worlds
    order=[next(j for j,w in enumerate(fws) if w[q['player']][q['goal']]==v) for v in (1,0,-1)]
    fresh_pay=np.array([fresh.tree.values[x] for x in entry.children])[:,order,:]
    if not np.allclose(pay,fresh_pay,rtol=0,atol=1e-9):raise ValueError('Continuation relies on removed history')
    audit_native(fresh.tree)
    # Also certify actual tolerance-based scoring, including response tie rules.
    reward_sets=set()
    for comp in cert['components']:
        for vertex in comp['vertices']:
            p=np.array([float(Fraction(v)) for v in vertex['posterior']])
            values=np.einsum('awp,w->ap',pay,p)
            reward_sets.add(tuple(acceptable(values,actor,actions=acts)))
    if len(reward_sets)!=1:raise ValueError('Reward tolerance is not invariant over qualitative region')
    actual=tuple(acts.index(a) for a in t['acceptable_actions'])
    if set(actual)!=set(next(iter(reward_sets))):raise ValueError('Reward set does not match source posterior')
    world_sets=[set(acceptable(pay[:,w,:],actor,actions=acts)) for w in range(3)]
    gold_set=set(actual)
    opposite=[v for v,choices in zip(('want','neutral','avoid'),world_sets) if choices.isdisjoint(gold_set)]
    c['intervention_qualification']=dict(
        world_reward_sets={v:sorted(a) for v,a in zip(('want','neutral','avoid'),world_sets)},
        reward_changes=len({tuple(sorted(a)) for a in world_sets})>1,
        common_acceptable_actions=sorted(set.intersection(*world_sets)),
        gold_disjoint_alternatives=opposite,
        role='repair_sensitive' if opposite else 'action_control')
    c['certificate']=dict(semantic=cert,acceptable_action_indices=list(actual),
        clean_state_payoffs_match=True,all_unknowns_covered=True,remaining_proposals=len(st['round_robin'])-st['turn_index'])
    clean=deepcopy(task);clean.update(task='P',condition='P_infer',skill='history_planning')
    clean['input'].update(private_results=[],voluntary_history=[],imposed_setup=[],
        initial_commitments=st['commitments'],initial_turn_index=st['turn_index'])
    req=request(clean,clean_initial)
    text=req['messages'][1]['content']
    before,rest=text.split('\nINITIAL STATE AT GAME START',1)
    _,after=rest.split('\nCURRENT BINDING STATE',1)
    text=before+'\nCURRENT BINDING STATE'+after
    text=text.replace('Infer the relevant preferences from the visible information and choose your next action.',
        'Choose your next action using the supplied partner judgment and current state.')
    text=text.replace('Your own preferences, known facts and observed choices can change your current belief.',
        'Use the supplied partner judgment for the hidden preference.')
    text=text.replace('at the stated initial state','at the current decision state')
    req['messages'][1]['content']=text
    c['requests']['P_clean']=req
    c['gold_judgment']=t['gold'];c['teacher_posterior']=t['posterior']
    c['task'].update(task='P',skill='history_planning',condition='P_infer')
    facts=i['private_results']
    if any(f['player']==q['player'] and f['goal']==q['goal'] for f in facts):c['stratum']='direct_feedback'
    elif facts:c['stratum']='feedback_integration'
    elif c['history_events']:c['stratum']='behavior_inference'
    else:c['stratum']='initial_information_control'
    c['structural_difficulty']=dict(goals=len(i['game']['goals']),events=c['history_events'],
        legal_actions=len(acts),note='Structural counts, not measured model difficulty')
    return c

def training_audit(cases):
    # Conservative parent-ID audit across all local training task banks; geometry
    # reuse is reported separately and never presented as structure-held-out.
    parents={c['source_parent']:[] for c in cases}
    paths=sorted(set((ROOT/'examples/social_mixed').rglob('*tasks.jsonl'))|
                 set((ROOT/'examples/social_mixed').rglob('bp_train.jsonl'))|
                 set((ROOT/'examples/social_bp').rglob('*train_tasks.jsonl')))
    sources=[]
    for path in paths:
        sources.append(dict(path=str(path.relative_to(ROOT)),sha256=sha(path)))
        for line in path.read_text().splitlines():
            row=json.loads(line);t=row.get('task') if isinstance(row.get('task'),dict) else row
            if t.get('split') not in (None,'train'):continue
            ids={str(t.get(k,'')) for k in ('canonical_id','package_id','origin_id','id')}
            for parent in ids & parents.keys():parents[parent].append(str(path.relative_to(ROOT)))
    return dict(scope='Local canonical-parent identifier overlap; NOT geometry-disjoint or unseen evaluation',
        sources=sources,matches={k:sorted(set(v)) for k,v in parents.items() if v})

def main():
    rows=json.loads((HERE/'candidates.json').read_text())+json.loads((HERE/'feedback_candidates.json').read_text())+json.loads((HERE/'interaction_candidates.json').read_text());qualified=[];rejected=[]
    for row in rows:
        try:qualified.append(qualify(row))
        except (ValueError,AssertionError,RuntimeError) as e:rejected.append(dict(id=row['id'],reason=str(e)))
    # Hard quotas: never silently fill an intervention panel with controls.
    pools={s:[c for c in qualified if c['intervention_qualification']['role']==s] for s in ('repair_sensitive','action_control')}
    selected=[];used=set();labels=Counter();geometries=Counter();modes=Counter();targets={'repair_sensitive':16,'action_control':16}
    for s,n in targets.items():
        for _ in range(n):
            pool=[c for c in pools[s] if c['source_parent'] not in used]
            if not pool:raise RuntimeError(f'Insufficient {s} parents; refusing control fallback')
            c=min(pool,key=lambda c:(labels[key(c['gold_judgment'])],geometries[c['structure_family']],modes[c['mode']],len(c['task']['input']['game']['goals']),sha_id(c['id'])))
            selected.append(c);used.add(c['source_parent']);labels[key(c['gold_judgment'])]+=1;geometries[c['structure_family']]+=1;modes[c['mode']]+=1
    if len(selected)!=32:raise RuntimeError('Expected exactly 32 cases')
    audit=training_audit(selected)
    if audit['matches']:raise RuntimeError('Selected parent overlaps training: '+key(audit['matches']))
    selected.sort(key=lambda c:(c['stratum'],c['id']))
    for n,c in enumerate(selected):c['case_number']=n+1
    (HERE/'cases.json').write_text(json.dumps(selected,indent=2)+'\n')
    (HERE/'selection_audit.json').write_text(json.dumps(dict(qualified=len(qualified),available={s:len(v) for s,v in pools.items()},
        intended_targets=targets,selected=dict(Counter(c['stratum'] for c in selected)),labels=dict(labels),
        exclusions=rejected,training_overlap=audit),indent=2)+'\n')
    with (HERE/'case_inventory.csv').open('w') as f:
        fields=['case_number','id','source_parent','stratum','support','favored','goals','events','legal_actions','intervention_role','gold_disjoint_alternatives']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in selected:
            w.writerow(dict(case_number=c['case_number'],id=c['id'],source_parent=c['source_parent'],stratum=c['stratum'],
                support='|'.join(c['gold_judgment']['possible_preferences']),favored=c['gold_judgment']['favored'],
                intervention_role=c['intervention_qualification']['role'],gold_disjoint_alternatives='|'.join(c['intervention_qualification']['gold_disjoint_alternatives']),
                **{k:c['structural_difficulty'][k] for k in ('goals','events','legal_actions')}))
    manifest=dict(version='initial-state-diagnostic-v7-intervention-balanced',cases=32,status='frozen_development_diagnostic',
        scope='Reused validation structures plus teacher-generated natural histories; not an untouched or geometry-held-out benchmark',
        unique_geometries=len(geometries),modes=dict(modes),
        conditions=['B','O','P_gold','P_model'],calls_per_repeat_max=128,
        intervention_roles=dict(Counter(c['intervention_qualification']['role'] for c in selected)),
        selected=dict(Counter(c['stratum'] for c in selected)),
        files={name:sha(HERE/name) for name in ('cases.json','selection_audit.json','case_inventory.csv')})
    deps=[HERE/'build.py',HERE/'initial_state.py',HERE/'experiment.py',HERE/'interaction_candidates.py',
          HERE/'feedback_candidates.py',ROOT/'new/diagnostic_v6/semantic_sufficiency.py',
          ROOT/'new/diagnostic_v5/experiment.py']
    deps += [ROOT/'training/b_sft'/name for name in ('social_private_teacher.py','social_terminal_teacher.py',
        'shared_teacher.py','social_named_probe.py','social_bp_curriculum.py','social_bp_training.py',
        'preference_contract.py','review_prompt.py','decision_policy.py')]
    manifest['dependencies']={str(path.relative_to(ROOT)):sha(path) for path in deps}
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},indent=2))

def sha_id(x):return hashlib.sha256(x.encode()).hexdigest()
if __name__=='__main__':main()
