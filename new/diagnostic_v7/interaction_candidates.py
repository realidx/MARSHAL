"""Restore an actual decision after an informative offer, using existing geometries.
Teacher-only search; fixed starting bindings, no imposed behavioral history.
"""
from copy import deepcopy
from collections import Counter
import hashlib,json,random
from pathlib import Path
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode,request
from new.diagnostic_v7.build import qualify
from new.diagnostic_v4.build import focal_positions
from training.b_sft.prepare_no_catalogue_probe import view,expand_support
from training.b_sft.social_private_teacher import audit_native
from training.b_sft.preference_contract import belief,profile
from training.b_sft.social_bp_curriculum import acceptable

HERE=Path(__file__).resolve().parent

def build():
    sources=json.loads((HERE/'candidates.json').read_text());out=[];errors=[];seen=set()
    # Small natural two-decision games. No model outputs or forced history.
    for seed in range(760000,760600):
        rng=random.Random(seed);ng=rng.choice((3,4));own=[rng.choice((-1,0,1)) for _ in range(ng)]
        own[0]=1;partner=[rng.choice((-1,0,1)) for _ in range(ng)];partner[1]=1
        goals=[dict(goal_id=g,binary=bool(seed%2),required_actions=[dict(player_id=p,action_id=rng.randrange(2)) for p in (0,1)]) for g in range(ng)]
        rows=[]
        for value in (1,0,-1):
            row=partner.copy();row[0]=value;rows.append(row)
        raw=dict(id=f'v7-natural-{seed}',history=[],ego=0,own_preferences=own,
                 type_catalogues={'0':[own],'1':rows},background_prior=profile('balanced'),
                 game=dict(n_players=2,n_actions_per_player=[2,2],round_robin=[1,0],max_changes=1,menu_enabled=False,goals=goals))
        try:raw,public,expansion=expand_support(raw)
        except ValueError:continue
        if len(raw['type_catalogues']['1'])!=3:continue
        sources.append(dict(id=raw['id'],source_parent=raw['id'],source_b_id=None,raw=raw,
            initial_state=dict(commitments=[[0,0],[0,0]],turn_index=0),
            task=dict(input=dict(game=raw['game'],queries=[dict(player=1,goal=0)],public_preferences=public),teacher=dict(worlds=[0,1,2]))))
    for src in sources:
        i=src['task']['input'];raw=deepcopy(src['raw']);q=i['queries'][0]
        if i['game']['n_players']!=2 or len(i['game']['goals'])>4:continue
        if len(src['task']['teacher']['worlds'])!=3:continue
        # Same physical starting bindings, partner offers before final focal proposal.
        raw['game']['round_robin']=[0,1,1,0]
        initial=dict(commitments=src['initial_state']['commitments'],turn_index=2)
        sig=json.dumps([raw,initial,q],sort_keys=True)
        if sig in seen:continue
        seen.add(sig)
        try:
            ep=InitialEpisode(raw,initial,seconds=2,max_nodes=10000,max_sweeps=128)
            own=raw['own_preferences']
            for pos,events,prob in focal_positions(ep,own):
                if prob<.02:continue
                node=pos.tree.entries[pos.index];actions=[a.to_dict() for a in node.actions]
                weights=pos._weights(0,own,())
                marginal=pos.belief(q['player'],q['goal'],observer=0,own=own)['preference_weights']
                pay=np.array([pos.tree.values[x] for x in node.children]);values=np.einsum('awp,w->ap',pay,weights)
                inp=view(pos,i['public_preferences'],0,own,[],[],events)
                inp.update(initial_commitments=initial['commitments'],initial_turn_index=2,queries=[q],
                    background_prior=raw['background_prior'],favored_margin=.1,legal_actions=actions,
                    supplied_belief=dict(known_preferences=i['public_preferences'],unresolved_preferences=[q],support='Infer from visible evidence.'))
                teacher=dict(gold=belief(marginal),preference_weights=marginal,worlds=pos.tree.worlds,posterior=weights.tolist(),
                    per_world_payoffs=pay.tolist(),action_values=values.tolist(),policy_sha256=pos.tree.certificate['policy_sha256'],
                    acceptable_actions=[actions[j] for j in acceptable(values,0,actions=actions)])
                cid='interaction-'+hashlib.sha256(json.dumps([sig,events],sort_keys=True).encode()).hexdigest()[:18]
                task=dict(id=cid,input=inp,teacher=teacher,task='B',condition='B',skill='formation')
                ot=deepcopy(task);ot.update(task='P',condition='P_infer',skill='history_planning')
                c=dict(id=cid,source_parent=src['source_parent'],source_b_id=src['source_b_id'],raw=raw,initial_state=initial,task=task,
                    requests=dict(B=request(task,initial),O=request(ot,initial)),history_events=len(events),
                    native_audit=audit_native(pos.tree),path_probability=prob,
                    derivation='Same source geometry/preferences; independent starting state; native partner offer and response before focal proposal')
                try:
                    checked=qualify(c)
                    sets=[set(acceptable(pay[:,w,:],0,actions=actions)) for w in range(3)]
                    if checked['intervention_qualification']['role']=='repair_sensitive':
                        out.append(c)
                except (ValueError,RuntimeError,AssertionError):pass
        except (ValueError,RuntimeError,AssertionError) as e:errors.append(dict(source=src['id'],error=str(e)))
        if len({c['source_parent'] for c in out})>=24:break
    (HERE/'interaction_candidates.json').write_text(json.dumps(out,indent=2)+'\n')
    report=dict(qualified_action_relevant=len(out),parents=len({c['source_parent'] for c in out}),labels=dict(Counter(str(c['task']['teacher']['gold']) for c in out)),errors=errors)
    (HERE/'interaction_search.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='errors'},indent=2))
if __name__=='__main__':build()
