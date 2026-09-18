"""Read-only audit of four low-signal cells in the released v3 curriculum.

Reconstruct from visible input; never patch labels based on model failures.
"""
from collections import Counter,defaultdict
from copy import copy,deepcopy
from functools import lru_cache
from itertools import combinations
import hashlib,json
from pathlib import Path
import numpy as np
from jsonschema import validate
from training.social_mixed.core import ROOT
from training.social_mixed.prepare_distribution_curriculum import stable
from training.social_mixed.distribution_sampling import select
from training.b_sft.debug.audit_readable_pretraining import reconstruct,independent_backward
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.preference_contract import belief
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft import social_named_probe as named
from training.b_sft.social_bp_training import native_completion,reward
from training.social_mixed.structure_coverage import geometry_id
SOURCE=ROOT/'examples/social_mixed/data_binary_linear_v3'
OUT=ROOT/'new/zero_signal_data_audit_v1'
VALUES={'want':1,'neutral':0,'avoid':-1}

def read(p):return [json.loads(l) for l in p.read_text().splitlines()]
def cell(t):
    if t['task']=='B' and len(t['teacher']['gold']['possible_preferences'])<3 and (t['kernel'],t['completion_mode']) in [('B2','linear'),('B2','binary'),('B1','linear')]:return t['kernel']+'/'+t['completion_mode']+'/reduced_support'
    if t['kernel']=='P4' and t['completion_mode']=='binary' and t.get('p4_case')=='ordinary_alternative':return 'P4/binary/ordinary_only/ordinary_alternative'
    return None

@lru_cache(maxsize=8)
def solve(key,initialization='uniform',order=None):
    raw,setup=json.loads(key)
    e=PrivateEpisode(raw,setup,seconds=60,max_nodes=80000,max_sweeps=128,initialization=initialization,audit_update_order=order)
    return e,audit_native(e.tree),independent_backward(e.tree)

def marginal(weights,worlds,p,g):return {name:float(sum(w for w,world in zip(weights,worlds) if world[p][g]==value)) for name,value in VALUES.items()}

def completion(name,args):return dict(finish_reason='stop',raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))

def interface_check(t,request_builder=None):
    checks=0;gold_calls=[]
    for variant in (0,1):
        req=(request_builder or named.request)(t,'action_tools',variant);v=named.present(t,variant)
        if t['task']=='P':
            expected={stable(a) for a in t['teacher']['acceptable_actions']}
            for native,action in zip(t['input']['legal_actions'],v['legal_actions']):
                name,args=named.action_call(action);schema=next(tool['function']['parameters'] for tool in req['tools'] if tool['function']['name']==name)
                validate(args,schema)
                score=named.score(t,completion(name,args),'action_tools',variant)
                assert score['status']=='ok' and bool(score['correct'])==(stable(native) in expected)
                if score['correct']:gold_calls.append(dict(variant=variant,name=name,arguments=args))
                checks+=1
        else:
            gold=t['teacher']['gold']
            for size in (1,2,3):
                for possible in combinations(VALUES,size):
                    for favored in (*VALUES,'undetermined'):
                        obj=dict(judgments=[dict(**v['belief_question'],possible_preferences=list(possible),favored=favored)])
                        validate(obj,req['tools'][0]['function']['parameters'])
                        score=named.score(t,completion('SUBMIT_BELIEFS',obj),'action_tools',variant)
                        correct=set(possible)==set(gold['possible_preferences']) and favored==gold['favored']
                        assert bool(score['correct'])==correct
                        checks+=1
            obj=dict(judgments=[dict(**v['belief_question'],**gold)])
            assert named.score(t,completion('SUBMIT_BELIEFS',obj),'action_tools',variant)['correct']
            gold_calls.append(dict(variant=variant,name='SUBMIT_BELIEFS',arguments=obj))
    assert reward(t,native_completion(t))['reward']==1
    cut=native_completion(t);cut['finish_reason']='length';assert reward(t,cut)['reward']==0
    return dict(roundtrips=checks,gold_calls=gold_calls,all_passed=True)

def audit_task(t):
    inp=t['input'];raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior'];key=stable([raw,inp['imposed_setup']])
    root,native,independent=solve(key);e=copy(root);e.weights=root.weights.copy()
    facts=[(f['player'],f['goal'],VALUES[f['preference']]) for f in inp['private_results']]
    trace=[]
    for event in inp['voluntary_history']:
        entry=e.tree.entries[e.index];ai=[a.to_dict() for a in entry.actions].index(event)
        weights=e._weights(inp['observer'],own,[])
        row=dict(actor=entry.actor,event=event,worlds=e.tree.worlds,prior=weights.tolist(),
            observed_action_likelihood_by_world=e.tree.policy[e.index][ai].tolist(),
            alternatives=[a.to_dict() for a in entry.actions],
            actor_continuation_values_by_world=[[float(w[entry.actor]) for w in e.tree.values[c]] for c in entry.children])
        if t['task']=='B':
            q=inp['queries'][0];row['prior_marginal']=marginal(weights,e.tree.worlds,q['player'],q['goal'])
            manual=weights*e.tree.policy[e.index][ai];manual/=manual.sum();row['posterior_marginal']=marginal(manual,e.tree.worlds,q['player'],q['goal'])
        trace.append(row);e.observe(event)
    node=e.tree.entries[e.index].node
    assert node.state.public_state()==inp['current_state']
    assert (None if node.pending is None else node.pending.to_dict())==inp['pending_offer']
    result=dict(id=t['id'],cell=cell(t),origin=t['origin_id'],profile=t['background_profile'],structure=geometry_id(inp['game']),
        selected_policy_match=e.tree.certificate['policy_sha256']==t['teacher']['policy_sha256'],native=native,
        independent_information_compatible_backward=independent,trace=trace,interface=interface_check(t),status='ok',
        remaining_proposal_opportunities=len(inp['game']['round_robin'])-root.tree.entries[0].node.state.turn_index)
    if t['task']=='B':
        q=inp['queries'][0];b=e.belief(q['player'],q['goal'],observer=inp['observer'],own=own,private_results=facts)
        assert belief(b['preference_weights'])==t['teacher']['gold']
        np.testing.assert_allclose(list(b['preference_weights'].values()),list(t['teacher']['preference_weights'].values()),atol=1e-9,rtol=0)
        result.update(gold=t['teacher']['gold'],posterior=b['preference_weights'],excluded=[v for v in VALUES if b['preference_weights'][v]==0])
    else:
        choices=e.choices(own,facts);assert choices['actions']==inp['legal_actions']
        supplied=inp['supplied_belief'];assert 'joint_distribution' not in supplied
        mask=np.array([all(world[f['player']][f['goal']]==VALUES[f['preference']] for f in supplied['known_preferences']) for world in e.tree.worlds])
        supplied_weights=e.tree.world_weights*mask;supplied_weights/=supplied_weights.sum()
        np.testing.assert_allclose(supplied_weights,e._weights(inp['player'],own,facts),atol=1e-9)
        np.testing.assert_allclose(choices['values'],t['teacher']['action_values'],atol=1e-9,rtol=0)
        indices=acceptable(choices['values'],inp['player'],actions=choices['actions'])
        assert [choices['actions'][j] for j in indices]==t['teacher']['acceptable_actions']
        best=max(v[inp['player']] for v in choices['values'])
        result['action_values']=[dict(action=a,own=v[inp['player']],regret=best-v[inp['player']],accepted=i in indices) for i,(a,v) in enumerate(zip(choices['actions'],choices['values']))]
    return result,key

def pair_key(t):
    i=t['input'];game=deepcopy(i['game'])
    for g in game['goals']:g.pop('binary',None)
    return stable([t['kernel'],t.get('b12_case'),t.get('p4_case'),game,i['public_preferences'],i['own_preferences'],i['imposed_setup'],i['voluntary_history'],i.get('queries'),i['private_results'],t['background_profile']])

def main():
    OUT.mkdir(exist_ok=True);tasks=read(SOURCE/'bp_train.jsonl');targets=[t for t in tasks if cell(t)];rows=[];keys={};errors=[]
    frozen={r['id']:r['request'] for r in read(SOURCE/'requests_train.jsonl')}
    exposure=Counter(t['id'] for step in range(194) for t in select(tasks,step,42))
    with (OUT/'progress.jsonl').open('w') as log:
        for t in targets:
            try:
                assert frozen[t['id']]==named.request(t,'action_tools',t.get('name_variant',0))
                r,key=audit_task(t);r['scheduled_groups_194']=exposure[t['id']];rows.append(r);keys[t['id']]=key
                event=dict(id=t['id'],cell=cell(t),status='ok',independent=r['independent_information_compatible_backward'])
            except Exception as exc:event=dict(id=t['id'],cell=cell(t),status='error',error=repr(exc));errors.append(event)
            log.write(json.dumps(event)+'\n');log.flush();print(json.dumps(event),flush=True)
    # Bounded policy-selection check on every balanced target. No altered labels are installed.
    sensitivity=[]
    for t in targets:
        if t['background_profile']!='balanced' or t['id'] not in keys:continue
        for init,order in [('first',None),('last',None),('uniform',tuple(reversed(range(t['input']['game']['n_players']))))]:
            event=dict(id=t['id'],initialization=init,update_order=order)
            try:
                root,_,_=solve(keys[t['id']],init,order);e=copy(root);e.weights=root.weights.copy()
                for a in t['input']['voluntary_history']:e.observe(a)
                inp=t['input'];own=tuple(VALUES[inp['own_preferences'][f'goal_{g}']] for g in range(len(inp['game']['goals'])))
                if t['task']=='B':
                    q=inp['queries'][0];gold=belief(e.belief(q['player'],q['goal'],observer=inp['observer'],own=own)['preference_weights']);reference=t['teacher']['gold']
                else:
                    c=e.choices(own);ids=acceptable(c['values'],inp['player'],actions=c['actions']);gold=[c['actions'][j] for j in ids];reference=t['teacher']['acceptable_actions']
                event.update(status='same' if gold==reference else 'different',gold=gold)
            except Exception as exc:event.update(status='unavailable',error=repr(exc))
            sensitivity.append(event);print(json.dumps(event),flush=True)
    indexed=defaultdict(list)
    for t in tasks:indexed[pair_key(t)].append(t)
    pairs=[dict(id=t['id'],mode=t['completion_mode'],gold=t['teacher'].get('gold',t['teacher'].get('acceptable_actions')),
        counterparts=[dict(id=x['id'],mode=x['completion_mode'],gold=x['teacher'].get('gold',x['teacher'].get('acceptable_actions'))) for x in indexed[pair_key(t)] if x['completion_mode']!=t['completion_mode']]) for t in targets]
    summary=dict(targets=len(targets),passed=len(rows),errors=errors,cells=dict(Counter(cell(t) for t in targets)),
        scoring_roundtrips=sum(r['interface']['roundtrips'] for r in rows),independent_backward=sum(bool(r['independent_information_compatible_backward']) for r in rows),
        policy_sensitivity=dict(Counter(r['status'] for r in sensitivity)),unique_origins=len({t['origin_id'] for t in targets}),
        scheduled_groups={k:sum(exposure[t['id']] for t in targets if cell(t)==k) for k in {cell(t) for t in targets}},
        source_manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),
        scope='Released local v3 data; actual step 0–193 training samples were not found locally. Scheduled exposure is not observed exposure. No model calls; no labels modified.')
    for name,value in [('summary',summary),('tasks',rows),('policy_sensitivity',sensitivity),('mode_pairs',pairs)]:
        (OUT/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (OUT/'requests.jsonl').write_text(''.join(json.dumps(dict(id=t['id'],cell=cell(t),request=frozen[t['id']]),ensure_ascii=False)+'\n' for t in targets))
    print(json.dumps(summary),flush=True)
    if errors:raise RuntimeError('Audit failures recorded; do not declare data valid')

if __name__=='__main__':main()
