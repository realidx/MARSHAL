"""Validate and freeze v4 candidate; leaves active training release unchanged."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
import hashlib
import shutil
import numpy as np
from training.social_mixed.prepare_reasoning_v4 import SOURCE,OUT,read,digest
from training.social_mixed.core import ROOT,Episode,seed_for,sp_prompt
from training.social_mixed.structure_coverage import geometry_id,audit
from training.social_mixed.reasoning_requests import request
from training.social_mixed.frozen.benac_p.generator import GeneratorConfig,generate_game
from training.social_mixed.frozen.outcome_rules import generation_rule
from training.b_sft.social_bp_training import native_completion,reward
from training.b_sft.preference_contract import profile,VERSION

def main():
    packs={n:read(OUT/(n+'.jsonl')) for n in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation')}
    for name in ('selfplay_train','selfplay_validation'):
        packs[name]=[r for r in packs[name] if not r['id'].startswith('reasoning-v4-sp-')]
    occupied={geometry_id(t.get('input',t.get('raw'))['game']) for ts in packs.values() for t in ts}
    final=ROOT/'examples/final_evaluation/benac_a_v1/resets.jsonl'
    protected={geometry_id(t['raw']['game']) for t in read(final)}
    attempts=[]
    for split,count in [('train',12),('validation',4)]:
        for index in range(count):
            players=3;mode='binary' if index%2==0 else 'linear';rounds=3+index%2
            cfg=GeneratorConfig(n_players=players,actions_per_player=3 if players==2 else 2,n_goals=4 if players==2 else 3,n_rounds=rounds,
                preference_probs=(1/3,1/3,1/3),linear_goal_fraction=0. if mode=='binary' else 1.)
            for attempt in range(500):
                seed=seed_for('reasoning-v4-sp',split,index,attempt);spec=generate_game(seed,cfg);g=spec.to_dict();world=spec.private_preferences.tolist()
                for key in ('private_preferences','metadata','seed'):g.pop(key,None)
                family=geometry_id(g)
                if family in occupied or family in protected:continue
                occupied.add(family)
                row=dict(id=f'reasoning-v4-sp-{split}-{index}',split=split,players=players,rounds=rounds,
                    background_profile='balanced',completion_mode=mode,structure_family=family,realized_world=world,
                    raw=dict(game=g,history=[],preference_generation=dict(version=VERSION,values=[-1,0,1],background_prior=profile('balanced'))),
                    generation=dict(seed=seed,config=asdict(cfg),attempt=attempt,source='native random geometry/world; only structural exclusion; no outcome selection'))
                # Full random native replay, including queries, to validate termination and utility.
                e=Episode(row,row['id'],0,42);rng=np.random.default_rng(seed)
                while e.status=='running':
                    legal=sp_prompt.visible(e.observation())['legal_actions'];action=legal[int(rng.integers(len(legal)))];name,args=sp_prompt.action_call(action)
                    e.accept(dict(completion=dict(finish_reason='stop',raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))))
                assert e.status=='terminal'
                packs['selfplay_'+split].append(row);attempts.append(dict(id=row['id'],seed=seed,attempt=attempt,geometry=family));break
            else:raise ValueError(f'Unique geometry allocation exhausted: {split} {index} {players}')
    for rows in packs.values():
        for t in rows:
            if 'p4_case' in t and t['p4_case'] is None:t.pop('p4_case')
    # Bound redundant history controls; spend new supervision on changed decisions.
    train=packs['bp_train'];seen_controls=Counter();excluded=[];retained=[]
    for t in sorted(train,key=lambda t:t['id']):
        if t.get('oracle_pair_of'):continue
        if t.get('reasoning_source_id') and t['task']=='P' and t['skill']=='history_planning' and not t['teacher'].get('history_changes_acceptable'):
            key=(t['completion_mode'],t['input']['game']['n_players']);seen_controls[key]+=1
            if seen_controls[key]>2:excluded.append(t['id']);continue
        retained.append(t)
    packs['bp_train']=retained
    if (OUT/'excluded_history_controls.json').exists():excluded=sorted(set(excluded)|set(json.loads((OUT/'excluded_history_controls.json').read_text())['ids']))
    (OUT/'excluded_history_controls.json').write_text(json.dumps(dict(ids=excluded,reason='At most two new history-insensitive controls per mode/player-count; no model outcome filtering'),indent=2))
    # Same-history oracle condition is an exact joint posterior, never a lossy B label.
    for split in ('train','validation'):
        rows=packs['bp_'+split]
        rows[:]=[t for t in rows if not t.get('oracle_pair_of')]
        additions=[]
        for t in rows:
            if not t.get('reasoning_source_id'):continue
            if t['task']=='P':
                group='v4:'+digest([t['reasoning_source_id'],t['input']['voluntary_history']])
                t['contrast_group']=group;t['p123_case']=('0_history_sensitive' if t['teacher'].get('history_changes_acceptable') else '1_history_control_'+t['completion_mode']+'_'+str(t['input']['game']['n_players'])) if t['kernel']=='P2' else group
                if t['kernel']=='P4':t['p4_case']=group
                t['direct_answer']=False
                oracle=deepcopy(t);oracle['id']=digest(['oracle-pair',t['id']]);oracle['native_task_id']=oracle['id'];oracle['oracle_pair_of']=t['id']
                oracle['input']['belief_source']='supplied'
                names={1:'want',0:'neutral',-1:'avoid'}
                oracle['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],
                    support='This is YOUR supplied exact joint distribution. This joint posterior follows from the same visible history under the stated partner policy; it does not disclose the realized hidden world.',
                    joint_distribution=[dict(probability=str(float(weight)),preferences=[dict(player=p,goal=g,preference=names[v]) for p,row in enumerate(world) for g,v in enumerate(row)])
                        for world,weight in zip(t['teacher']['worlds'],t['teacher']['posterior']) if weight>0])
                # Keep own/public facts in their original visible fields; all joint rows sum to one.
                assert abs(sum(float(r['probability']) for r in oracle['input']['supplied_belief']['joint_distribution'])-1)<1e-9
                oracle['semantic_id']=digest(oracle['input']);additions.append(oracle)
        rows.extend(additions)
    checks=[]
    for split in ('train','validation'):
        for t in packs['bp_'+split]:
            assert reward(t,native_completion(t))['correct']
            req=request(t,'action_tools',t.get('name_variant',0))
            if t['input'].get('belief_source')=='history':
                assert 'YOUR CURRENT BELIEF' not in req['messages'][1]['content']
                assert 'Use this supplied belief' not in req['messages'][1]['content']
                checks.append(t['id'])
        (OUT/('requests_'+split+'.jsonl')).write_text(''.join(json.dumps(dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))))+'\n' for t in packs['bp_'+split]))
    from training.social_mixed.validation import select_bp,cells
    dev=packs['bp_validation'];required={k for t in dev if t['kernel']!='A0' for k in cells(t)}
    for size in range(32,65):
        panel=select_bp(dev,size)
        if required<={k for t in panel for k in cells(t)}:break
    else:raise ValueError('Compact validation cannot cover required diagnostics')
    panel_ids={t['id'] for t in panel}
    for t in dev:t['periodic_validation']=t['id'] in panel_ids
    for name in ('diagnostics.jsonl','p4_links.json','requests_test.jsonl'):
        shutil.copyfile(SOURCE/name,OUT/name)
    for n,ts in packs.items():(OUT/(n+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in ts))
    report=audit(OUT);assert not report['cross_split_families']
    (OUT/'structure_audit.json').write_text(json.dumps(report,indent=2))
    (OUT/'sp_generation.json').write_text(json.dumps(attempts,indent=2))
    parent=json.loads((SOURCE/'manifest.json').read_text())
    manifest=dict(prompt_sources={**parent['prompt_sources'], 'training/social_mixed/reasoning_requests.py':hashlib.sha256((ROOT/'training/social_mixed/reasoning_requests.py').read_bytes()).hexdigest()},
        allowed_completion_modes=['binary','linear'],mode_counts={n:dict(Counter(t.get('completion_mode','binary' if all(g['binary'] for g in t['raw']['game']['goals']) else 'linear') if 'raw' in t else t['completion_mode'] for t in ts)) for n,ts in packs.items()},
        construction_sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['training/social_mixed/prepare_reasoning_v4.py','training/social_mixed/expand_reasoning_geometry.py','training/social_mixed/expand_feedback_v4.py','training/social_mixed/search_history_decisions_v4.py','training/social_mixed/finalize_reasoning_v4.py','training/social_mixed/validation.py']},periodic_validation_ids=sorted(panel_ids),periodic_validation_tasks=len(panel_ids),dataset_version='reasoning-v4-candidate',active=False,model_calls=0,
        parent_manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),
        history_request_module='training.social_mixed.reasoning_requests',history_request_checked=len(checks),
        files={p.name:dict(count=len(p.read_text().splitlines()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in OUT.glob('*.jsonl')},
        coverage={n:dict(Counter(t.get('kernel','selfplay') for t in ts)) for n,ts in packs.items()},
        limitations=['Active training remains v3; this candidate requires the history-aware request adapter.',
          'SP starts from native zero state; longer horizon affords feedback, but interactive OFFER information value is not certified.',
          'Eight independent three-player BP geometries were added; other new trajectories reuse existing split-specific geometry.',
          'Only balanced-prior new lessons in this candidate.'])
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(dict(coverage=manifest['coverage'],periodic_validation_tasks=len(panel_ids))))

if __name__=='__main__':main()
