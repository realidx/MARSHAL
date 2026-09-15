"""Generate verified private-investigation teaching checks, not self-play data."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from training.b_sft.social_bp_curriculum import result_use_fixture, acceptable, digest
from training.b_sft.social_bp_curriculum_eval import request, score
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, VERSION, GAME_VERSION


POLICY = ('Partners use a fixed full-terminal contingent policy selected by uniform initialization '
    'and synchronous best-response updates to stability. Maximize own expected terminal goal utility, '
    'then others total expected utility on own ties, then randomize uniformly on remaining ties. '
    'Each player conditions on public actions, own preferences and own private query answers. '
    'Imposed setup actions are not behavioral evidence. The selected strategy is not asserted unique.')
NAMES = {1:'want',0:'neutral',-1:'avoid'}


def base_input(e, observer, facts):
    entry = e.tree.entries[e.index]
    own = e.raw['type_catalogues'][str(observer)][0]
    return dict(game=e.rules.public_game(), observer=observer, player=observer,
        own_preferences=[NAMES[v] for v in own], current_state=entry.node.state.public_state(),
        pending_offer=None if entry.node.pending is None else entry.node.pending.to_dict(),
        private_results=[dict(player=p,goal=g,preference=NAMES[v]) for p,g,v in facts],
        public_type_catalogues={p:[{f'goal_{g}':NAMES[v] for g,v in enumerate(row)} for row in rows]
                                for p,rows in e.raw['type_catalogues'].items()},
        initial_support='Equal support over the listed joint combinations before voluntary behavior.',
        partner_policy=POLICY)


def make_p(e, facts, skill):
    actor=e.tree.entries[e.index].actor
    own=e.raw['type_catalogues'][str(actor)][0]
    row=e.choices(own,facts)
    inp=base_input(e,actor,facts)
    weights=e._weights(actor,own,facts)
    ids=np.flatnonzero(weights>0)
    assert np.allclose(weights[ids],weights[ids[0]])
    inp.update(legal_actions=row['actions'],supplied_belief=dict(
        joint_alternatives=[[[NAMES[v] for v in r] for r in e.tree.worlds[i]] for i in ids],
        support='These alternatives have equal current support for YOU. Other players condition on their own information.'),
        instruction='Use the supplied current belief directly; select a legal action for final utility, helping others on own ties.')
    selected=acceptable(row['values'],actor)
    return dict(task='P',skill=skill,stage=0,input=inp,teacher=dict(
        acceptable_actions=[row['actions'][i] for i in selected],action_values=row['values'],
        all_legal_accepted=len(selected)==len(row['actions']),policy_sha256=e.tree.certificate['policy_sha256']))


def make_b(e, observer, facts, skill, evidence):
    inp=base_input(e,observer,facts)
    own=e.raw['type_catalogues'][str(observer)][0]
    belief=e.belief(1,0,observer=observer,own=own,private_results=facts)
    inp.update(task=skill,queries=[dict(player=1,goal=0)],evidence=evidence,
        instruction='Use only your own private results and public evidence to judge the queried preference.',
        favored_rule='Keep preferences with positive support; favor the uniquely most supported value, otherwise undetermined.')
    if skill in ('update','maintain'):
        inp['previous_belief']=dict(possible_preferences=['want','avoid'],favored='undetermined')
    return dict(task='B',skill=skill,stage=0,input=inp,teacher=dict(
        gold={k:belief[k] for k in ('possible_preferences','favored')},
        preference_weights=belief['preference_weights'],policy_sha256=e.tree.certificate['policy_sha256']))


def build(out):
    raw,prefix=result_use_fixture('want')
    prefix[3].pop('revealed_preference')
    e=PrivateEpisode(raw,prefix)
    audit=audit_native(e.tree)
    tasks=[]
    for value in (1,-1):
        facts=[(1,0,value)]
        p=make_p(e,facts,'private_result_use')
        p['input']['setup']=prefix
        tasks.append(p)
        b=make_b(e,0,facts,'update','The earlier legal setup query delivered the private result shown above; intervening PASS actions were imposed setup.')
        b['input']['setup']=prefix
        tasks.append(b)
    # A public query target without the private answer does not itself reveal
    # the type here: setup was imposed independently of either hidden value.
    b=make_b(e,2,[],'maintain','All displayed historical actions were imposed setup, independent of the hidden preference. You did not receive the private answer.')
    b['input']['setup']=prefix
    tasks.append(b)
    # Subsequent voluntary offers DO carry evidence about an informed player.
    for action in (dict(action='OFFER',partner_id=1,proposer_action=[1,0],partner_action=[1]),
                   dict(action='OFFER',partner_id=1,proposer_action=[0,1],partner_action=[1])):
        branch=PrivateEpisode(raw,prefix)
        branch.observe(action)
        b=make_b(branch,2,[],'update','After the imposed setup, P0 voluntarily submitted the pending offer using the selected policy and its private result.')
        b['input'].update(setup=prefix,new_public_action=action)
        tasks.append(b)
    blind_prefix=deepcopy(prefix)
    blind_prefix[3]=dict(action='PASS')
    blind=PrivateEpisode(raw,blind_prefix)
    p=make_p(blind,[],'last_turn_do_not_investigate')
    p['input']['setup']=blind_prefix
    tasks.append(p)
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    requests=[]
    for task in tasks:
        task.update(source='private-result-bridge',split='train',training_ready=False,
                    mechanism='private_investigation_teaching',topology='result_use_bridge')
        task['id']=digest((VERSION,task['task'],task['input']))
        payload=request(task)
        assert 'single shared investigation' not in str(payload)
        assert 'action_values' not in str(payload)
        assert 'preference_weights' not in str(payload)
        gold=task['teacher']['gold'] if task['task']=='B' else task['teacher']['acceptable_actions'][0]
        args=dict(judgments=[dict(player=1,goal=0,**gold)]) if task['task']=='B' else gold
        completion=dict(raw_message=dict(tool_calls=[dict(function=dict(
            name='SUBMIT_BELIEFS' if task['task']=='B' else 'SUBMIT_ACTION',arguments=json.dumps(args)))]))
        assert score(task,completion)['reward']==1
        requests.append(dict(task_id=task['id'],task=task['task'],request=payload))
    summary=dict(version=VERSION,game_version=GAME_VERSION,tasks=len(tasks),actual_LM=False,
        training_ready=False,stage='B/P teaching only; not outcome self-play',eval_steps=10,
        native=audit,deadline_native=audit_native(blind.tree),certificate=e.tree.certificate,
        verified=['private result changes investigator best offer', 'uninformed observer retains uncertainty',
                  'later public offer reveals evidence', 'last-turn query loses against trade',
                  'all exported gold submissions score one'],
        limits=['Direct-result B updates are not behavioral inversion practice',
                'This short chain imposes query and intermediate actions as setup; no full acquisition-Q claim',
                'Off-path beliefs and teacher policy are explicit modeling conventions',
                'Not integrated into production self-play runner or optimizer'])
    for name,rows in [('tasks.jsonl',tasks),('requests.jsonl',requests)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    print(json.dumps(build(parser.parse_args().out),ensure_ascii=False,indent=2))
