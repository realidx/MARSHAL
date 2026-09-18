"""Small audited P1 bridge candidates for P4's empty-self OFFER pattern.

Export only; do not modify a released or active dataset. Fully known, one-step
versions precede the existing uncertain multi-turn ordinary_alternative task.
"""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
from training.social_mixed.prepare_distribution_curriculum import annotate
from training.social_mixed.audit_zero_signal import ROOT,SOURCE,OUT,read,interface_check
from training.social_mixed.structure_coverage import geometry_id
from training.social_mixed.prepare_reasoning_v4 import task_at,stable
from training.social_mixed.prepare_distribution_curriculum import root_episode
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.preference_contract import profile
from training.b_sft.social_named_probe import request,present
from training.b_sft.social_bp_training import native_completion,reward


def main():
    owners={}
    for split in ('train','validation','test'):
        for prefix in ('bp','selfplay'):
            path=SOURCE/(prefix+'_'+split+'.jsonl')
            if path.exists():
                for t in read(path):owners.setdefault(geometry_id(t.get('input',t.get('raw'))['game']),set()).add(split)
    protected={geometry_id(r['raw']['game']) for r in read(ROOT/'examples/final_evaluation/benac_a_v1/resets.jsonl')}
    base=deepcopy(next(t for t in read(SOURCE/'bp_train.jsonl') if t['kernel']=='P1' and t['background_profile']=='balanced'))
    rows=[];checks=[]
    for stage in ('only_missing_partner','avoid_extra_self'):
        for binary in (True,False):
            goals=1 if stage=='only_missing_partner' else 3
            actions=1 if goals==1 else 2
            own=[1] if goals==1 else [1,1,-1]
            raw=dict(id='empty-self-'+stage,ego=0,own_preferences=own,history=[],type_catalogues={'0':[own],'1':[[1]*goals]},
                game=dict(n_players=2,n_actions_per_player=[actions,1],max_changes=1,menu_enabled=False,round_robin=[1,0],
                    goals=[dict(goal_id=g,binary=binary,required_actions=[dict(player_id=0,action_id=0 if g<2 else 1),dict(player_id=1,action_id=0)]) for g in range(goals)]))
            setup=[dict(action='OFFER',partner_id=0,proposer_action=[0],partner_action=[1]+[0]*(actions-1)),dict(response='ACCEPT')]
            raw,public,_=expand_support(raw);raw['background_prior']=profile('balanced');family=geometry_id(raw['game'])
            if owners.get(family,set())-{'train'} or family in protected:raise ValueError('Bridge would reuse held-out geometry')
            source=deepcopy(base);source.update(id='bridge-'+stage+'-'+str(binary),completion_mode='binary' if binary else 'linear',family=family)
            source['input']=dict(public_preferences=public,background_prior=profile('balanced'))
            root,_=root_episode(stable([raw,setup]));t=task_at(source,root,setup,[],[],'P')
            if t is None:raise ValueError('Bridge has no discriminating target')
            t.update(kernel='P1',skill='complete',pool='complete',bridge_stage=stage,bridge_target='ordinary_alternative_empty_self',
                p123_case='0_empty_self_'+stage,contrast_group='0_empty_self_'+stage,training_ready=False,review_status='cpu_checked_candidate_not_installed')
            t['input']['belief_source']='supplied';t['input']['supplied_belief']=dict(known_preferences=public,unresolved_preferences=[],support='These known facts completely specify YOUR current belief.')
            # Gold unchanged: the joint posterior is the sole public world.
            assert len(root.tree.worlds)==1 and reward(t,native_completion(t))['reward']==1
            v=present(t,t.get('name_variant',0));accepted=[v['legal_actions'][t['input']['legal_actions'].index(a)] for a in t['teacher']['acceptable_actions']]
            assert accepted and all(a.get('action')=='OFFER' and a['self_commitments']==[] and a['partner_commitments'] for a in accepted),(stage,binary,accepted,t['teacher']['action_values'])
            checks.append(dict(id=t['id'],stage=stage,mode=t['completion_mode'],geometry=family,interface=interface_check(t),gold=accepted))
            rows.append(t);root_episode.cache_clear()
    # Forward decision exercises for the exact inverse-inference bottlenecks.
    # Preferences are genuinely public in these simpler tasks, not leaked in B.
    for kind in ('known_preference_response','known_preference_proposal'):
        modes=(False,) if kind.endswith('response') else (True,False)
        for binary in modes:
            for value in (1,0,-1):
                for sign in ((1,-1) if kind.endswith('response') else (1,)):
                    own=[value,1];other=[sign,1]
                    raw=dict(id=kind,ego=0,own_preferences=own,history=[],type_catalogues={'0':[own],'1':[other]},
                        game=dict(n_players=2,n_actions_per_player=[2,1],max_changes=1,menu_enabled=False,
                            round_robin=[0,1] if kind.endswith('response') else [1,0],goals=[
                                dict(goal_id=g,binary=binary,required_actions=[dict(player_id=0,action_id=g),dict(player_id=1,action_id=0)]) for g in range(2)]))
                    setup=[dict(action='PASS')]
                    if kind.endswith('response'):
                        setup.append(dict(action='OFFER',partner_id=0,proposer_action=[0],partner_action=[1,0]))
                    raw,public,_=expand_support(raw);raw['background_prior']=profile('balanced');family=geometry_id(raw['game'])
                    if owners.get(family,set())-{'train'} or family in protected:raise ValueError('Forward bridge overlaps held-out geometry')
                    source=deepcopy(base);source.update(id=f'bridge-{kind}-{binary}-{value}-{sign}',completion_mode='binary' if binary else 'linear',family=family)
                    source['input']=dict(public_preferences=public,background_prior=profile('balanced'))
                    root,_=root_episode(stable([raw,setup]));t=task_at(source,root,setup,[],[],'P')
                    assert t is not None and len(root.tree.worlds)==1
                    t.update(kernel='P1',skill='complete',pool='complete',bridge_stage=kind,
                        bridge_target='B1_linear_response_inverse' if kind.endswith('response') else 'B2_proposal_counterfactual',
                        p123_case='0_'+kind,contrast_group='0_'+kind,training_ready=False,review_status='cpu_checked_candidate_not_installed')
                    t['input']['belief_source']='supplied';t['input']['supplied_belief']=dict(known_preferences=public,unresolved_preferences=[],support='These known facts completely specify YOUR current belief.')
                    assert reward(t,native_completion(t))['reward']==1
                    checks.append(dict(id=t['id'],stage=kind,mode=t['completion_mode'],candidate_preference=value,other_goal_preference=sign,
                        geometry=family,interface=interface_check(t),gold=t['teacher']['acceptable_actions']))
                    rows.append(t);root_episode.cache_clear()
    rows=[annotate(t) for t in rows]
    (OUT/'bridge_candidates.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in rows))
    (OUT/'bridge_requests.jsonl').write_text(''.join(json.dumps(dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))))+'\n' for t in rows))
    (OUT/'bridge_checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    (OUT/'bridge_manifest.json').write_text(json.dumps(dict(active=False,model_calls=0,training_ready=False,source_manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),files={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ('bridge_candidates.jsonl','bridge_requests.jsonl','bridge_checks.json')},script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
    print(json.dumps(dict(candidates=len(rows),stages=4,modes=['binary','linear'],active=False)))

if __name__=='__main__':main()
