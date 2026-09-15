"""Causal and native-rule checks for retaining public INVESTIGATE in self-play.

No LM calls, no training and no new partner behavior. Visibility ablations are
counterfactual diagnostics with other players' original policies held fixed.
"""
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

from training.b_sft.catalogues import validate_catalogues
from training.b_sft.social_b_oracle import canonical
from training.b_sft.social_terminal_teacher import TerminalEpisode,TerminalWindow,Investigate,VERSION,GAME_VERSION
from training.b_sft.debug.audit_social_design_iteration import (
    fixture,root_report,independent_values,blind_to_revelation_response,renaming_audit,
)
from benac_p.endgame_diagnose import decode_action


def information_value_fixture(*,deadline=False,extra_target=False):
    raw,prefix=fixture(225,hidden_goal=3)
    raw['id']='public-information-value'+('-deadline' if deadline else '-target-choice' if extra_target else '')
    if deadline:
        raw['game']['round_robin']=[1,2,0]
        prefix=[dict(action='PASS')]*2
    if extra_target:
        if deadline:
            raise ValueError('Use a separate deadline contrast')
        # Preserve the active game, adding a legally completed, additive goal.
        # Its independent hidden preference is a genuinely irrelevant query.
        raw['game']['n_actions_per_player']=[2,2,1]
        for goal in raw['game']['goals']:
            for action in goal['required_actions']:
                if action['player_id'] in (0,1):
                    action['action_id']=1
        raw['game']['goals'].append(dict(goal_id=4,binary=True,
            required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=0)]))
        for p,rows in raw['type_catalogues'].items():
            raw['type_catalogues'][p]=[row+[0] for row in rows]
        row=raw['type_catalogues']['2'][0]
        raw['type_catalogues']['2']=[row[:-1]+[v] for v in (1,-1)]
        raw['own_preferences']=raw['type_catalogues']['0'][0]
        raw['game']['round_robin']=[0,1,2]*2
        prefix=[dict(action='OFFER',partner_id=1,proposer_action=[1,0],partner_action=[1,0]),
                dict(response='ACCEPT'),dict(action='PASS'),dict(action='PASS')]
    validate_catalogues(raw)
    return raw,prefix


def exact_values(tree,policy=None):
    """Rational arithmetic through the policy; recompute all terminal utilities."""
    policy=tree.policy if policy is None else policy
    values=[None]*len(tree.entries)
    for i in reversed(range(len(tree.entries))):
        entry=tree.entries[i]
        if entry.actor is None:
            assert entry.node.state.is_terminal
            c=entry.node.state.snapshot_commitments()
            flags=[all(c[a.player_id][a.action_id] for a in g.required_actions) for g in tree.rules.spec.goals]
            values[i]=[tuple(Fraction(sum(v*f for v,f in zip(row,flags))) for row in world) for world in tree.worlds]
        else:
            values[i]=[]
            for wi in range(tree.w):
                probabilities=[Fraction(float(p)).limit_denominator(len(entry.actions)) for p in policy[i][:,wi]]
                assert all(float(p)==float(q) for p,q in zip(probabilities,policy[i][:,wi]))
                values[i].append(tuple(sum(probabilities[ai]*values[child][wi][p]
                    for ai,child in enumerate(entry.children)) for p in range(tree.n)))
    return values


def expected(tree,values,index):
    weights=[Fraction(float(w)).limit_denominator(1000000) for w in tree.world_weights]
    assert sum(weights)==1
    return tuple(sum(w*values[index][wi][p] for wi,w in enumerate(weights)) for p in range(tree.n))


def exact_root_rows(episode):
    tree=episode.tree
    exact=exact_values(tree)
    rows=[]
    for action,child in zip(tree.entries[0].actions,tree.entries[0].children):
        means=expected(tree,exact,child)
        np.testing.assert_allclose([float(v) for v in means],np.average(tree.values[child],axis=0,weights=tree.world_weights),atol=1e-9,rtol=0)
        rows.append(dict(action=action.to_dict(),expected_payoffs=[str(v) for v in means]))
    return rows


def visibility_effects(episode):
    tree=episode.tree
    reports=[]
    for player in range(tree.n):
        _,policy=blind_to_revelation_response(tree,player)
        exact=exact_values(tree,policy)
        for action,child in zip(tree.entries[0].actions,tree.entries[0].children):
            if isinstance(action,Investigate):
                reports.append(dict(result_hidden_from=player,action=action.to_dict(),
                    expected_payoffs=[str(v) for v in expected(tree,exact,child)],
                    scope='This player computes a best response without reading revelation values; can still infer from later behavior. Other players retain their original policies.'))
    return reports


def pivotal_decision(raw,prefix,value):
    """Same AB commitments and final proposer, different public revelation."""
    e=TerminalEpisode(raw,prefix)
    e.observe(dict(action='INVESTIGATE',player=1,goal=3),revelation=value)
    e.observe(dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1]))
    e.observe(dict(response='ACCEPT'))
    assert e.tree.entries[e.index].node.state.snapshot_commitments()==((1,),(1,),(0,))
    assert e.tree.entries[e.index].actor==2
    row=e.choices(raw['type_catalogues']['2'][0])
    return dict(revelation=value,public_state=e.tree.entries[e.index].node.state.public_state(),
                choices=row)


def no_result_control(episode):
    """Same physical turn/quota expenditure but no disclosed information.

    This is an environment intervention, not an additional legal game action.
    Solve the remaining counterfactual problem under the same default procedure.
    """
    tree=episode.tree
    node=episode.rules._apply(tree.entries[0].node,decode_action(dict(action='PASS')))
    node.state.investigation_used=True
    other=TerminalWindow(episode.rules,node,tree.worlds,world_weights=tree.world_weights).solve()
    return dict(expected_payoffs=[str(v) for v in expected(other,exact_values(other),0)],
        commitments=node.state.snapshot_commitments(),turn_index=node.state.turn_index,
        remaining_investigations=node.state.public_state()['investigation_remaining'],
        certificate=other.certificate,
        scope='Re-solved no-information counterfactual after identical turn and quota expenditure; not a fixed-policy causal estimate by itself')


def run(out):
    if out.exists():
        raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True)
    reports=[]
    for name,kwargs in [('useful',{}),('too_late',dict(deadline=True)),('target_choice',dict(extra_target=True))]:
        raw,prefix=information_value_fixture(**kwargs)
        episode=TerminalEpisode(raw,prefix,seconds=15)
        rows=exact_root_rows(episode)
        report=dict(name=name,raw=raw,prefix=prefix,exact_root_values=rows,
            root=root_report(episode),native=independent_values(episode.tree))
        if name!='too_late':
            report['visibility']=visibility_effects(episode)
            report['spent_without_result']=no_result_control(episode)
            report['renaming']=renaming_audit(raw,prefix,episode)
        if name=='useful':
            report['pivotal_decisions']=[pivotal_decision(raw,prefix,v) for v in (1,-1)]
        reports.append(report)
        print(json.dumps(dict(case=name,root_values=rows)),flush=True)
    by_name={r['name']:r for r in reports}
    useful=by_name['useful']['exact_root_values']
    assert [r['expected_payoffs'][0] for r in useful if r['action'].get('action')=='INVESTIGATE']==['1/3']
    assert {r['expected_payoffs'][0] for r in useful if r['action'].get('action')!='INVESTIGATE'}=={'0'}
    assert by_name['useful']['spent_without_result']['expected_payoffs'][0]=='0'
    visibility={r['result_hidden_from']:r for r in by_name['useful']['visibility']}
    assert visibility[0]['expected_payoffs'][0]=='1/3'
    assert visibility[2]['expected_payoffs'][0]=='0'
    deadline=by_name['too_late']['exact_root_values']
    assert max(Fraction(r['expected_payoffs'][0]) for r in deadline if r['action'].get('action')!='INVESTIGATE')==1
    assert [r['expected_payoffs'][0] for r in deadline if r['action'].get('action')=='INVESTIGATE']==['0']
    targets={r['action']['goal']:r['expected_payoffs'][0] for r in by_name['target_choice']['exact_root_values'] if r['action'].get('action')=='INVESTIGATE'}
    assert targets=={3:'1/3',4:'0'}
    summary=dict(version=VERSION,game_version=GAME_VERSION,actual_LM=False,training_ready=False,
        useful_investigation_payoff='1/3',best_ordinary_payoff='0',
        no_result_same_cost_payoff='0',hide_from_investigator_payoff='1/3',hide_from_pivotal_partner_payoff='0',
        deadline_investigation='0',deadline_best_ordinary='1',
        relevant_target='1/3',irrelevant_target='0',
        finding='Public information acquisition has instrumental value for the initiator by changing another player information and continuation policy. It can be costly or target-irrelevant.',
        limitations=['Existence and causal mechanism under the selected teacher, not a guarantee that an LM self-play population learns or preserves the same response',
            'The witness uses the already-declared prosocial and uniform residual tie rules',
            'Does not establish direct information-use improvement by the investigating player',
            'Production runner integration remains a separate task'],
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path('training/b_sft/social_terminal_teacher.py'),Path('training/b_sft/debug/audit_social_design_iteration.py'))})
    (out/'cases.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.out)
