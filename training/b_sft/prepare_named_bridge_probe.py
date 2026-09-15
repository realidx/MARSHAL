"""Versioned named B/P diagnostic, output controls and short teaching examples.

Exports only visible requests to the server. Labels, qualitative interval
certificates and native mapping are local. Does not train or contact a server.
"""
import argparse
from collections import Counter
from copy import deepcopy, copy
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import numpy as np

from training.b_sft.prepare_no_catalogue_probe import tasks_from_case, expand_support, view
from training.b_sft.debug.audit_minimal_teaching import fixture
from training.b_sft.social_bp_curriculum import digest, acceptable
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.b_sft.social_b_oracle import NAMES
from training.b_sft.social_p_qualitative import robust_actions, WIDE_ENVELOPES, WORDS
from training.b_sft import social_named_probe as named
from training.b_sft import social_prompt

VERSION = 'bp-readable-action-tools-v4'


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def confidence_fixture():
    # Risky bundle achieves two wanted goals; safe bundle achieves one.
    # Only one preference is unknown, with all THREE generator-compatible values.
    raw = dict(id='named-qualitative-risk', ego=0, own_preferences=[1,1,1], history=[],
        type_catalogues={'0': [[1,1,1]], '1': [[v,0,1] for v in (1,0,-1)]},
        game=dict(n_players=2, n_actions_per_player=[2,1], max_changes=1, menu_enabled=False,
            round_robin=[1,0], goals=[dict(goal_id=g, binary=True, required_actions=[
                dict(player_id=0, action_id=int(g==2)), dict(player_id=1, action_id=0)]) for g in range(3)]))
    return raw


def qualitative_tasks():
    raw = confidence_fixture()
    task = tasks_from_case(dict(name='qualitative-base', kind='P', raw=raw, setup=[dict(action='PASS')]))
    expanded, _, _ = expand_support(raw)
    episode = PrivateEpisode(expanded, [dict(action='PASS')])
    entry = episode.tree.entries[0]
    payoffs = np.array([episode.tree.values[c] for c in entry.children])
    # Only responder-private type varies. Verify the final response payoff per
    # world against separately solved complete-information native games.
    for wi, world in enumerate(episode.tree.worlds):
        full = deepcopy(expanded)
        full['type_catalogues'] = {str(p): [list(row)] for p,row in enumerate(world)}
        check = PrivateEpisode(full, [dict(action='PASS')])
        assert check.choices(world[0])['actions'] == task['input']['legal_actions']
        np.testing.assert_allclose(check.choices(world[0])['values'], payoffs[:,wi,:], atol=1e-9, rtol=0)
    for value, level in [(1,'very_likely'), (1,'almost_certain'), (-1,'likely'),
                         (-1,'unlikely'), (-1,'impossible'), (-1,'certain'), (1,'possible')]:
        claims = [dict(event=[dict(player=1, goal=0, value=value)], level=level)]
        cert = robust_actions(payoffs, 0, episode.tree.worlds, claims,
            own_tolerance=.1, social_tolerance=.1, envelopes=WIDE_ENVELOPES)
        for paraphrase in (0,1):
            t = deepcopy(task)
            preference = {1:'want', -1:'avoid'}[value]
            wording = WORDS[level][paraphrase]
            # Preserve qualifier wording, not exact probabilities or a type list.
            t['input']['qualitative'] = dict(description=(
                'This is YOUR supplied current assessment. It replaces the generator prior for this decision; '
                'do not infer its source or invent a precise percentage. Unknown preferences remain subject '
                'to the stated game constraints. A likely value is not certain; an unlikely value remains possible. '
                'These assessments are not additional public disclosures to other players.'),
                assessments=[dict(player=1, goal=0, preference=preference, qualifier=wording)])
            if level=='certain':
                t['input']['supplied_belief']['known_preferences'].append(dict(player=1,goal=0,preference=preference))
                t['input']['supplied_belief']['unresolved_preferences']=[]
            t['teacher'].update(acceptable_actions=[t['input']['legal_actions'][i] for i in cert['acceptable']],
                qualitative_certificate=cert, audit_envelopes=WIDE_ENVELOPES, claims=claims,
                per_world_payoffs=payoffs.tolist(), worlds=episode.tree.worlds)
            # Uniform-prior action_values must not masquerade as current values.
            t['teacher'].pop('action_values', None)
            t.update(source=f'qualitative_{preference}_{level}_{paraphrase}', skill='qualitative_belief',
                stage=1, split='development_probe', training_ready=False)
            t['id'] = digest((VERSION,t['source'],t['input']))
            yield t


def direct_fact_tasks():
    raw = fixture(types=((1,1),(0,1),(-1,1)),schedule=(0,1))
    for value in (1,0,-1):
        yield tasks_from_case(dict(name=f'short_private_fact_{value}', kind='B', skill='update',
            raw=raw, setup=[dict(action='INVESTIGATE',player=1,goal=0)], private_results=[(1,0,value)]))


def complete(task, answer, arm, explanation='Verified teaching example.'):
    if arm == 'action_tools':
        name, args = named.action_call(answer) if task['task']=='P' else ('SUBMIT_BELIEFS', answer)
        return dict(raw_message=dict(content=explanation, tool_calls=[dict(function=dict(
            name=name, arguments=json.dumps(args)))]))
    if arm == 'text':
        return dict(raw_message=dict(content=json.dumps(dict(reasoning=explanation, answer=answer))))
    args = answer if arm == 'separate_tool' else dict(reasoning=explanation, answer=answer)
    return dict(raw_message=dict(content=explanation if arm=='separate_tool' else None, tool_calls=[dict(
        function=dict(name='SUBMIT_BELIEFS' if task['task']=='B' else 'SUBMIT_ACTION', arguments=json.dumps(args)))]))


def make_lessons(tasks):
    sources = {t['source']: t for t in tasks}
    notes = {
        'one_response_accept': 'Blair chose to accept the offer, completing Orchard. A want preference benefits from accepting. A neutral preference accepts on the social tie-break because Alex benefits. An avoid preference would reject. Thus want and neutral remain possible, with neither favored.',
        'one_response_reject': 'Blair chose to reject the offer, leaving Orchard unfinished. Want would accept for its own benefit; neutral would accept to help Alex without losing anything. Avoid would reject the harmful goal. Only avoid is compatible.',
        'irrelevant_goal_response_maintains_three': 'The new response concerns Harbor. Blair is known to want Harbor for every candidate preference for Orchard. The response therefore does not distinguish the three Orchard candidates. Keep the supplied previous belief.',
        'short_private_fact_0': 'The environment privately reports neutral for the queried preference. This is a true fixed value, so want and avoid are no longer possible. Submit the singleton neutral and favor neutral.',
        'maintain_favored_goal_0': 'The supplied correct previous belief keeps want and neutral, with want favored. The new response is Alex accepting Blair\'s offer. Alex wants the achieved goal regardless of which of these preferences Blair has. This adds no distinguishing evidence about Blair. Keep both the previous set and its favored value; do not reintroduce avoid.',
        'joint_unknown_favored_disappears': 'Both of Blair\'s preferences are unknown, and at least one must be want. Blair chooses to propose Harbor. Wanting both goals permits either proposal; wanting only Harbor leads to this proposal. Thus the observation supports neutral-about-Orchard and avoid-Orchard more than want-Orchard, with those two tied. All three Orchard values remain possible, but the previous favored want no longer leads. Submit undetermined.',
        'complete_own_gain': 'Add Cedar for Alex and Cedar for Blair. If accepted, these satisfy every requirement of Orchard. Both players want Orchard, so Blair accepts and Alex gains. Leaving Alex without Cedar would complete no goal.',
        'complete_altruistic_tie': 'Add Maple for Alex and Cedar for Blair to complete Harbor without completing Orchard. Blair wants Harbor and avoids Orchard. This offer is accepted and helps Blair. Alex cannot gain from Orchard because Blair would reject it; helping Blair is preferred on Alex\'s own-utility tie.',
        'investigate_acquisition_root': 'Investigate Blair\'s Orchard preference. This spends the current opportunity, but after Blair\'s intervening turn Alex still has another proposal. A want or neutral answer supports completing Orchard; an avoid answer supports helping Blair complete Library while leaving Harbor unfinished. Under the stated partner policy this preserves Alex\'s best expected payoff and improves Blair\'s payoff. Querying either already-known preference cannot provide this distinction.',
        'acquisition_same_game_last_turn': 'Only the current proposal opportunity remains. Investigating would end the game without making commitments. Offer Cedar for Alex and Maple for Blair to complete Orchard if accepted. Blair accepts with want or neutral and rejects with avoid. This gives Alex a positive expected benefit; the safe Library goal is neutral for Alex.',
        'acquisition_avoid_next_proposal': 'The private answer establishes that Blair avoids Orchard. Both players also avoid Harbor. Add Maple for Alex and Cedar for Blair: this completes Library, which Blair wants and Alex is neutral about. Alex has not committed to Cedar, so neither avoided goal is achieved. This helps Blair on Alex\'s own-utility tie.'}
    lessons=[]
    for source, rationale in notes.items():
        task = sources[source]
        answer = named.gold_answer(task)
        assert named.score(task,complete(task,answer,'text'),'text')['reward']==1
        lessons.append(dict(source=source, task=task['task'], visible=named.present(task),
                            problem_text=social_prompt.render(named.present(task),task['task'],task['skill']),
                            reasoning=rationale, answer=answer, teacher_task_id=task['id']))
    return lessons


def acquisition_fixture():
    raw=dict(id='named-investigation-acquisition',ego=0,own_preferences=[1,-1,0],history=[],
        type_catalogues={'0':[[1,-1,0]],'1':[[v,-1,1] for v in (1,0,-1)]},
        game=dict(n_players=2,n_actions_per_player=[2,2],max_changes=1,menu_enabled=False,
            round_robin=[1,0,1,0],goals=[dict(goal_id=g,binary=True,required_actions=[
                dict(player_id=0,action_id=a),dict(player_id=1,action_id=b)])
                for g,(a,b) in enumerate(((0,1),(0,0),(1,0)))]))
    return raw,[dict(action='PASS')]


def acquisition_information_audit():
    raw,setup=acquisition_fixture()
    raw,_,_=expand_support(raw)
    episode=PrivateEpisode(raw,setup)
    native=audit_native(episode.tree)
    root=episode.choices(raw['own_preferences'])
    episode.observe(dict(action='INVESTIGATE',player=1,goal=0))
    episode.observe(dict(action='PASS'))
    entry=episode.tree.entries[episode.index]
    assert entry.actor==0 and entry.node.pending is None
    weights=episode.weights/episode.weights.sum()
    assert np.all(weights>0)
    av=np.array([episode.tree.values[c] for c in entry.children])
    # At this final decision, responder preferences and responses are fixed.
    # Remove ONLY the learner's answer-based choice, retaining the same public
    # history and best possible single action under its public posterior.
    blind=np.einsum('awp,w->ap',av,weights)
    best=acceptable(blind.tolist(),0,own_tolerance=0.,social_tolerance=0.)
    conditional=np.average(episode.tree.values[episode.index],axis=0,weights=weights)
    assert all(np.allclose(blind[i],blind[best[0]]) for i in best)
    return dict(native=native,selected_policy=episode.tree.certificate,root=root,
        same_public_history=[dict(action='INVESTIGATE',player=1,goal=0),dict(action='PASS')],
        public_posterior=weights.tolist(),with_private_answer=conditional.tolist(),
        best_without_answer=blind[best[0]].tolist(),
        blind_acceptable_actions=[entry.actions[i].to_dict() for i in best],
        scope='Same public history and terminal partner responses; optimize learner choice with vs without its true answer. This is an information-use ablation, separate from the root comparison of all actions.')


def acquisition_tasks():
    raw,setup=acquisition_fixture()
    t = tasks_from_case(dict(name='investigate_acquisition_root',kind='P',raw=raw,setup=setup))
    accepted = t['teacher']['acceptable_actions']
    query=dict(action='INVESTIGATE',player=1,goal=0)
    assert accepted==[query]
    t['stage']=1
    yield t
    expanded,public,_=expand_support(raw)
    episode=PrivateEpisode(expanded,setup)
    episode.observe(query)
    for value in (1,0,-1):
        branch=copy(episode)
        facts=[(1,0,value)]
        events=[query]
        inp=view(branch,public,0,raw['own_preferences'],facts,setup,events)
        belief=branch.belief(1,0,observer=0,own=raw['own_preferences'],private_results=facts)
        inp.update(task='update',queries=[dict(player=1,goal=0)],
            previous_belief=dict(possible_preferences=['want','neutral','avoid'],favored='undetermined'),
            new_evidence='The environment has just delivered the true private answer listed for you.')
        b=dict(task='B',skill='update',stage=0,input=inp,source='acquisition_answer_'+NAMES[value],
            teacher=dict(gold={k:belief[k] for k in ('possible_preferences','favored')},
                preference_weights=belief['preference_weights'],policy_sha256=episode.tree.certificate['policy_sha256']),
            split='development_probe',training_ready=False)
        b['id']=digest((VERSION,b['source'],inp));yield b
        wi=next(i for i,w in enumerate(branch.tree.worlds) if w[1][0]==value)
        # One reproducible positive-probability teacher path per true answer.
        # No intervening action is forced or re-solved under a different policy.
        for checkpoint in range(6):
            entry=branch.tree.entries[branch.index]
            if entry.actor is None:break
            if entry.actor==0:
                inp=view(branch,public,0,raw['own_preferences'],facts,setup,events)
                choices=branch.choices(raw['own_preferences'],facts)
                world=branch.tree.worlds[wi]
                inp.update(legal_actions=choices['actions'],supplied_belief=dict(
                    known_preferences=[dict(player=p,goal=g,preference=NAMES[v])
                        for p,row in enumerate(world) for g,v in enumerate(row)],unresolved_preferences=[],
                    support='These known facts completely specify YOUR current belief. Use them directly; your private answer was not publicly disclosed.'))
                p=dict(task='P',skill='investigate_then_use_answer',stage=1,input=inp,
                    source=f'acquisition_{NAMES[value]}_'+('response' if entry.node.pending else 'next_proposal'),
                    teacher=dict(acceptable_actions=[choices['actions'][i] for i in acceptable(choices['values'],0)],
                        action_values=choices['values'],all_legal_accepted=len(acceptable(choices['values'],0))==len(choices['actions']),
                        policy_sha256=episode.tree.certificate['policy_sha256']),
                    split='development_probe',training_ready=False)
                p['id']=digest((VERSION,p['source'],inp));yield p
                if entry.node.pending is None:break
            ai=next(i for i,prob in enumerate(branch.tree.policy[branch.index][:,wi]) if prob>0)
            action=entry.actions[ai].to_dict()
            branch.observe(action)
            events=events+[action]
        else:
            raise AssertionError('Short acquisition chain did not reach the next learner proposal')
    deadline=deepcopy(raw);deadline['game']['round_robin']=[1,0]
    yield tasks_from_case(dict(name='acquisition_same_game_last_turn',kind='P',raw=deadline,setup=setup))


def build(out):
    tasks=read('new/local_data/social_runs/bp_no_catalogue_probe_v4/tasks.jsonl')
    tasks.extend(direct_fact_tasks())
    tasks.extend(qualitative_tasks())
    tasks.extend(acquisition_tasks())
    lessons=make_lessons(tasks)
    contrast_sources={'one_response_accept','one_response_reject','three_player_1_update',
        'three_player_3_update','maintain_favored_goal_0','complete_own_gain',
        'complete_altruistic_tie','private_result_avoid'}
    acquisition_teaching={'investigate_acquisition_root','acquisition_same_game_last_turn',
                          'acquisition_want_next_proposal','acquisition_avoid_next_proposal'}
    requests=[]; indexed=[]; checks=0
    for task in tasks:
        conditions=[('action_tools',0,False)]
        if task['source'] in contrast_sources:
            conditions += [('action_tools',1,False),('action_tools',1,True)]
        elif task['source'] in acquisition_teaching:
            conditions += [('action_tools',1,False),('action_tools',1,True)]
        for arm,variant,taught in conditions:
            t=deepcopy(task)
            t.update(native_task_id=task['id'],output_arm=arm,name_variant=variant,short_teaching=taught)
            t['id']=digest((VERSION,task['id'],arm,variant,taught))
            payload=named.request(t,arm,variant)
            if taught:
                if task['source'] in acquisition_teaching:
                    selected={'investigate_acquisition_root','acquisition_same_game_last_turn','acquisition_avoid_next_proposal'}
                elif task['task']=='P':
                    selected={'complete_own_gain','complete_altruistic_tie'}
                elif 'three_player' in task['source']:
                    selected={'short_private_fact_0','one_response_accept'}
                elif 'maintain_favored' in task['source']:
                    selected={'maintain_favored_goal_0','joint_unknown_favored_disappears'}
                else:
                    selected={'one_response_accept','one_response_reject','irrelevant_goal_response_maintains_three'}
                examples=[dict(problem=x['problem_text'],explanation=x['reasoning'],answer=x['answer'])
                          for x in lessons if x['source'] in selected]
                for example in examples:
                    answer = example.pop('answer')
                    name, args = (named.action_call(answer) if 'judgments' not in answer
                                  else ('SUBMIT_BELIEFS', answer))
                    example['submission_tool_call'] = dict(name=name, arguments=args)
                t['worked_example_sources']=sorted(selected)
                example_text='Worked teaching examples. Apply their rules to the new case; names may change.\n\n'
                for i, example in enumerate(examples,1):
                    example_text += (f'WORKED EXAMPLE {i}\n'+example['problem']+'\n\nEXAMPLE EXPLANATION\n'+
                                     example['explanation']+'\nEXAMPLE TOOL CALL\n'+
                                     json.dumps(example['submission_tool_call'])+'\n\n')
                payload['messages'].insert(1,dict(role='user',content=example_text))
                payload['messages'].insert(2,dict(role='assistant',content='I will apply the rules to the new case and match my submitted answer to my conclusion.'))
            visible=json.dumps(payload)
            for forbidden in ('action_id','proposer_action','partner_action','commitments_after',
                              'type_catalogues','joint_alternatives','policy_sha256','action_values',
                              'audit_envelopes','per_world_payoffs'):
                assert forbidden not in visible,forbidden
            ambiguous=t['teacher'].get('qualitative_certificate',{}).get('status')=='ambiguous_information'
            if not ambiguous:
                gold=named.gold_answer(t,variant)
                assert named.score(t,complete(t,gold,arm),arm,variant)['reward']==1
                checks+=1
            requests.append(dict(task_id=t['id'],task=t['task'],output_arm=arm,request=payload))
            indexed.append(t)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    bundle=out/'bundle';bundle.mkdir()
    for name,rows in [('tasks.jsonl',indexed),('teaching_examples.jsonl',lessons)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (out/'investigate_certificate.json').write_text(json.dumps(acquisition_information_audit(),indent=2)+'\n')
    (bundle/'requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests))
    for source,target in [('remote_bp_probe.py','remote_bp_probe.py'),('run_no_catalogue_probe.sh','run_probe.sh')]:
        shutil.copyfile(Path('training/b_sft')/source,bundle/target)
    manifest=dict(version=VERSION,files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir()})
    (bundle/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summary=dict(version=VERSION,base_tasks=len(tasks),requests=len(requests),group_size=8,
        formal_samples=8*len(requests),preflight_requests=2,gold_roundtrips=checks,
        output_arms=dict(Counter(t['output_arm'] for t in indexed)),lessons=len(lessons),
        qualitative_statuses=dict(Counter(t['teacher']['qualitative_certificate']['status'] for t in tasks if 'qualitative_certificate' in t['teacher'])),
        acquisition_included=True,actual_LM=False,parameters_updated=False,training_ready=False,
        limitation='Development probe; teaching and renamed cases are not an independent generalization test. Qualitative interval ambiguity is not scored as wrong.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    preview=['# Model-visible prompt examples','',
        'Exact messages from the readable action_tools interface. Only API tool schemas are pretty-printed. '
        'Worked-example answers appear only in the explicitly taught condition; evaluation labels remain local.','']
    for source in ['one_response_reject','private_result_avoid','investigate_acquisition_root',
                   'acquisition_same_game_last_turn','acquisition_avoid_next_proposal',
                   'maintain_favored_goal_0','qualitative_avoid_certain_0','qualitative_avoid_unlikely_0']:
        t=next(t for t in indexed if t['source']==source and t['output_arm']=='action_tools' and t['name_variant']==0)
        req=next(r['request'] for r in requests if r['task_id']==t['id'])
        preview.extend(['## '+source,'','System:','',req['messages'][0]['content'],'','User:','','```text',
                        req['messages'][-1]['content'],'```','',
                        'Registered tools:','','```json',json.dumps(req['tools'],ensure_ascii=False,indent=2),'```',''])
    taught=next(t for t in indexed if t['source']=='one_response_accept' and t['short_teaching'])
    req=next(r['request'] for r in requests if r['task_id']==taught['id'])
    preview.extend(['## Complete renamed teaching condition: one_response_accept',''])
    for msg in req['messages']:
        preview.extend([msg['role']+':','','```text',msg['content'],'```',''])
    preview.extend(['Registered tools:','','```json',json.dumps(req['tools'],indent=2),'```',''])
    (out/'prompt_examples.md').write_text('\n'.join(preview))
    with tarfile.open(out/'visible_probe.tar.gz','w:gz') as tar:
        tar.add(bundle,arcname='bundle')
    return summary


def analyze(data, samples, out):
    data=Path(data)
    tasks={t['id']:t for t in read(data/'tasks.jsonl')}
    config=json.loads((Path(samples).parent/'run_config.json').read_text())
    if config['requests_sha256']!=hashlib.sha256((data/'bundle/requests.jsonl').read_bytes()).hexdigest():
        raise ValueError('Results do not match the supplied question bundle')
    if config['script_sha256']!=hashlib.sha256((data/'bundle/remote_bp_probe.py').read_bytes()).hexdigest():
        raise ValueError('Sampler checksum mismatch')
    if set(config['task_ids'])!=set(tasks):
        raise ValueError('Scoring requires the complete formal request list, not preflight')
    results=[]
    seen=set()
    counts={}
    for row in read(samples):
        t=tasks[row['task_id']]
        key=(row['task_id'],row['sample_index'])
        if key in seen or not 0<=row['sample_index']<config['group_size']:
            raise ValueError('Duplicate or out-of-range sample index')
        seen.add(key)
        result=named.score(t,row,t['output_arm'],t['name_variant'])
        results.append(dict(row,score=result))
        stratum=(t['task'],t['skill'],t['output_arm'],t['name_variant'],t['short_teaching'])
        c=counts.setdefault(stratum,Counter())
        c['samples']+=1;c['correct']+=result.get('correct') is True
        c['scored']+=result.get('reward') is not None
        c[result['status']]+=1
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    (out/'scored_samples.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results))
    summary=dict(samples=len(results),expected=len(tasks)*config['group_size'],
        complete=len(results)==len(tasks)*config['group_size'],correct=sum(r['score'].get('correct') is True for r in results),
        parameters_updated=False,provenance_verified=True,
        strata=[dict(task=k[0],skill=k[1],output_arm=k[2],name_variant=k[3],short_teaching=k[4],counts=dict(v)) for k,v in counts.items()])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    p.add_argument('--score-samples')
    p.add_argument('--data')
    args=p.parse_args()
    print(json.dumps(analyze(args.data,args.score_samples,args.out) if args.score_samples else build(args.out),indent=2))
