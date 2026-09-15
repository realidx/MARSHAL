"""Re-solve teaching cases without revealing or imposing a hidden type list.

Unknown slots have the full support of the declared uniform teaching generator.
Only public fixed preferences, own information and observations reach the LM.
This does not change the outcome self-play generator.
"""
import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import numpy as np

from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, GAME_VERSION, VERSION as TEACHER_VERSION
from training.b_sft.social_bp_curriculum import acceptable, digest
from training.b_sft.social_bp_curriculum_eval import request, score
from training.b_sft.debug.audit_private_teaching import POLICY
from training.b_sft.social_b_oracle import NAMES

VERSION='bp-no-catalogue-probe-v1'
GENERATOR=('The explicitly public preferences below are fixed. '
    'Every other preference is initially drawn independently with equal chances of want, neutral and avoid. '
    'Redraw invalid configurations: each player must want at least one goal, and each goal must have '
    'at least one player who is not neutral. These rules are common knowledge. Each player knows its '
    'own preferences. No extra restrictions on the unknown preferences apply. '
    'The imposed setup actions do not provide behavioral evidence; voluntary actions do.')


def expand_support(raw):
    """Old constant slots become explicit public facts; variable slots expand.

    Reconstruct the generator support before using any history or private answer.
    Reject unsupported cross-player correlation rather than silently dropping it.
    """
    raw=deepcopy(raw)
    n=raw['game']['n_players']; goals=len(raw['game']['goals'])
    public=[]; unknown=[]
    template=[[None]*goals for _ in range(n)]
    for p in range(n):
        rows=raw['type_catalogues'][str(p)]
        for g in range(goals):
            values={r[g] for r in rows}
            if len(values)==1:
                value=next(iter(values));template[p][g]=value
                public.append(dict(player=p,goal=g,preference=NAMES[value]))
            else:unknown.append((p,g))
    worlds=[]
    for values in product((1,0,-1),repeat=len(unknown)):
        world=deepcopy(template)
        for (p,g),value in zip(unknown,values):world[p][g]=value
        if any(1 not in row for row in world):continue
        if any(all(world[p][g]==0 for p in range(n)) for g in range(goals)):continue
        worlds.append(tuple(tuple(r) for r in world))
    if not worlds:raise ValueError('Public facts make the declared generator impossible')
    rows={str(p):list(dict.fromkeys(w[p] for w in worlds)) for p in range(n)}
    if set(product(*(rows[str(p)] for p in range(n))))!=set(worlds):
        raise ValueError('Private teacher needs general correlated joint support for this case')
    old_count=np.prod([len(v) for v in raw['type_catalogues'].values()]).item()
    raw['type_catalogues']={p:[list(r) for r in rs] for p,rs in rows.items()}
    return raw,public,dict(old_worlds=old_count,new_worlds=len(worlds),unknown_slots=unknown)


def named(own):
    return {f'goal_{g}':NAMES[v] for g,v in enumerate(own)}


def view(e, public, observer, own, facts, setup, events):
    node=e.tree.entries[e.index].node
    return dict(game=e.rules.public_game(),player=observer,observer=observer,
        preference_generation=GENERATOR,public_preferences=public,own_preferences=named(own),
        private_results=[dict(player=p,goal=g,preference=NAMES[v]) for p,g,v in facts],
        current_state=node.state.public_state(),
        goal_descriptions=[dict(goal=f'goal_{g.goal_id}',requires=[f'player_{a.player_id}.action_{a.action_id}' for a in g.required_actions])
                           for g in e.rules.spec.goals],
        pending_offer=None if node.pending is None else node.pending.to_dict(),
        imposed_setup=setup,voluntary_history=events,partner_policy=POLICY,
        knowledge_rule='Each player sees this public history and its own preferences/results. A public query target does not reveal the answer to other players.')


def tasks_from_case(case):
    raw,public,expansion=expand_support(case['raw'])
    setup=case['setup'];events=case.get('events',[]);facts=case.get('private_results',[])
    observer=case.get('observer',0);own=raw['type_catalogues'][str(observer)][0]
    e=PrivateEpisode(raw,setup)
    before=[]
    for action in events:
        before.append(e.belief(1,0,observer=observer,own=own,private_results=facts))
        e.observe(action)
    inp=view(e,public,observer,own,facts,setup,events)
    teacher=dict(policy_sha256=e.tree.certificate['policy_sha256'],expansion=expansion,
                 native=audit_native(e.tree))
    if case['kind']=='B':
        belief=e.belief(1,0,observer=observer,own=own,private_results=facts)
        skill=case.get('skill','formation')
        inp.update(task=skill,queries=[dict(player=1,goal=0)],
            favored_rule='Keep every preference with positive support. Favored is the uniquely most supported preference, even if alternatives remain possible; otherwise use undetermined.',
            instruction='Infer the queried hidden preference from your available information. Explain briefly which evidence distinguishes preferences and what remains uncertain; do not output numerical confidence.')
        if skill in ('update','maintain'):
            if before:
                previous=before[-1]
                inp.update(old_history=events[:-1],new_history=events[-1:])
            else:
                # Explicit assisted pre-answer exercise. Setup is imposed and
                # has no voluntary evidence; private result is newly delivered.
                weights=e.weights*np.array([w[observer]==tuple(own) for w in e.tree.worlds])
                weights/=weights.sum()
                marginal={NAMES[v]:sum(float(p) for p,w in zip(weights,e.tree.worlds) if w[1][0]==v) for v in (1,0,-1)}
                possible=[k for k,v in marginal.items() if v>0]
                leaders=[k for k in possible if abs(marginal[k]-max(marginal.values()))<1e-9]
                previous=dict(possible_preferences=possible,favored=leaders[0] if len(leaders)==1 else 'undetermined')
                inp['new_evidence']='Your listed private result, if any; other displayed setup actions were imposed independently of preferences.'
            inp['previous_belief']={k:previous[k] for k in ('possible_preferences','favored')}
        gold={k:belief[k] for k in ('possible_preferences','favored')}
        if skill in ('update','maintain'):
            skill='maintain' if inp['previous_belief']==gold else 'update'
            inp['task']=skill
        teacher.update(gold=gold,preference_weights=belief['preference_weights'])
    else:
        skill=case['name'];row=e.choices(own,facts)
        weights=e._weights(observer,own,facts)
        known=[];uncertain=[]
        for p in range(raw['game']['n_players']):
            for g in range(len(raw['game']['goals'])):
                vals={w[p][g] for w,weight in zip(e.tree.worlds,weights) if weight>0}
                if len(vals)==1:known.append(dict(player=p,goal=g,preference=NAMES[next(iter(vals))]))
                else:uncertain.append(dict(player=p,goal=g))
        inp.update(legal_actions=row['actions'],supplied_belief=dict(
            known_preferences=known,unresolved_preferences=uncertain,
            support='Your CURRENT belief is the stated preference-generation distribution conditioned on these known preferences. There are no additional behavioral likelihood updates in this P exercise. Retain the generator constraints between goals. This describes YOUR belief, not private facts revealed to everyone.'),
            instruction='Use the supplied current belief directly. Prefer your final utility, then help others on own ties. Explain briefly why the selected action fits the partner information and preferences. Submit one exact legal action object; PASS has no extra fields.')
        if events:raise ValueError('P belief renderer currently supports setup-only exercises')
        accepted=acceptable(row['values'],observer)
        teacher.update(acceptable_actions=[row['actions'][i] for i in accepted],action_values=row['values'],
                       all_legal_accepted=len(accepted)==len(row['actions']))
    task=dict(task=case['kind'],skill=skill,stage=0,input=inp,teacher=teacher,source=case['name'],
              split='development_probe',training_ready=False,mechanism=VERSION)
    task['id']=digest((VERSION,task['source'],task['task'],inp))
    return task


def extra_favored_cases():
    # A completed wanted goal keeps all three hidden values legal. G0/G1
    # provide equally useful trades to P0; P1 is neutral about G1.
    raw=dict(id='no-catalogue-favored',ego=0,own_preferences=[1,1,1],history=[],
        type_catalogues={'0':[[1,1,1]],'1':[[v,0,1] for v in (1,0,-1)]},
        game=dict(n_players=2,n_actions_per_player=[3,2],max_changes=1,menu_enabled=False,round_robin=[0,1],
            goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=0,action_id=a),dict(player_id=1,action_id=b)])
                   for g,(a,b) in enumerate(((0,0),(1,0),(2,1)))]))
    setup=[dict(action='OFFER',partner_id=1,proposer_action=[0,0,1],partner_action=[0,1]),dict(response='ACCEPT')]
    for goal in (0,1):
        action=dict(action='OFFER',partner_id=0,proposer_action=[1,1],partner_action=[int(goal==0),int(goal==1),1])
        yield dict(name=f'favored_three_types_goal_{goal}',kind='B',raw=raw,setup=setup,events=[action],skill='formation')
        yield dict(name=f'maintain_favored_goal_{goal}',kind='B',raw=raw,setup=setup,events=[action,dict(response='ACCEPT')],skill='maintain')


def joint_unknown_cases():
    from training.b_sft.debug.audit_minimal_teaching import fixture, offer
    # Both slots vary. expand_support must restore all five valid rows, not
    # preserve the two-row template's artificial anticorrelation.
    raw=fixture(types=((1,-1),(-1,1)),schedule=(0,1))
    yield dict(name='joint_unknown_offer_a',kind='B',raw=raw,setup=[dict(action='PASS')],
               events=[offer(0,actor=1)],skill='formation')
    yield dict(name='joint_unknown_favored_disappears',kind='B',raw=raw,setup=[dict(action='PASS')],
               events=[offer(1,actor=1)],skill='update')
    yield dict(name='joint_unknown_maintain',kind='B',raw=raw,setup=[dict(action='PASS')],
               events=[offer(1,actor=1),dict(response='ACCEPT')],skill='maintain')


def build(out):
    cases=[json.loads(line) for line in Path('new/local_data/social_runs/minimal_teaching_v1/cases.jsonl').read_text().splitlines()]
    for case in cases:
        if case['name'].startswith('irrelevant') or case['name'].startswith('later_response'):case['skill']='maintain'
        elif 'favored_only' in case['name']:case['skill']='update'
    old_three=[json.loads(line) for line in Path('new/local_data/social_runs/private_teaching_v1/tasks.jsonl').read_text().splitlines()]
    from training.b_sft.social_bp_curriculum import result_use_fixture
    raw,_=result_use_fixture('want')
    for i,old in enumerate(old_three):
        inp=old['input']
        facts=[(x['player'],x['goal'],next(v for v,n in NAMES.items() if n==x['preference'])) for x in inp['private_results']]
        cases.append(dict(name=f'three_player_{i}_{old["skill"]}',kind=old['task'],raw=raw,setup=inp['setup'],
            events=[inp['new_public_action']] if 'new_public_action' in inp else [],
            observer=inp['observer'],private_results=facts,skill=old['skill']))
    cases.extend(extra_favored_cases())
    cases.extend(joint_unknown_cases())
    tasks=[tasks_from_case(c) for c in cases]
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    bundle=out/'bundle';bundle.mkdir()
    requests=[]
    for task in tasks:
        payload=request(task)
        payload['messages'][0]['content']+=' Give a short decision-relevant explanation (at most 120 words) before your tool call; do not merely repeat the problem.'
        visible=json.dumps(payload)
        for forbidden in ('public_type_catalogues','joint_alternatives','action_values','preference_weights','policy_sha256'):
            assert forbidden not in visible,forbidden
        args=dict(judgments=[dict(player=1,goal=0,**task['teacher']['gold'])]) if task['task']=='B' else task['teacher']['acceptable_actions'][0]
        result=score(task,dict(raw_message=dict(tool_calls=[dict(function=dict(name=payload['tools'][0]['function']['name'],arguments=json.dumps(args)))])))
        assert result['reward']==1
        requests.append(dict(task_id=task['id'],task=task['task'],request=payload))
    (out/'tasks.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in tasks))
    (bundle/'requests.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in requests))
    shutil.copyfile('training/b_sft/remote_bp_probe.py',bundle/'remote_bp_probe.py')
    for name in ('start_probe_gpu2.sh','run_no_catalogue_probe.sh'):
        shutil.copyfile(Path('training/b_sft')/name,bundle/name)
    summary=dict(version=VERSION,teacher_version=TEACHER_VERSION,game_version=GAME_VERSION,
        actual_LM=False,parameters_updated=False,tasks=len(tasks),counts=dict(Counter(t['task'] for t in tasks)),
        group_size=8,planned_requests=len(tasks)*8,preflight_requests=2,
        directory_visibility='No type rows or joint-world list exposed; full support reconstructed from public facts and the declared generator',
        generator_scope='Uniform conditional teaching distribution, not a change to outcome self-play',
        expanded_tasks=sum(t['teacher']['expansion']['new_worlds']>t['teacher']['expansion']['old_worlds'] for t in tasks),
        max_nodes=max(t['teacher']['native']['edges']+1 for t in tasks),
        reward_roundtrips=len(tasks),limitations=['Development diagnostic; no blind split or training export',
            'Does not yet test a general likely-language multi-turn P interface',
            'Public generation rules and explicit known preferences remain visible; only the extra type directory is removed'],
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),Path('training/b_sft/social_private_teacher.py'),Path('training/b_sft/social_bp_curriculum_eval.py'))})
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    manifest=dict(version=VERSION,tasks=len(tasks),group_size=8,
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir() if p.is_file()})
    (bundle/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with tarfile.open(out/'visible_probe.tar.gz','w:gz') as archive:
        archive.add(bundle,arcname='bundle')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    print(json.dumps(build(parser.parse_args().out),ensure_ascii=False,indent=2))
