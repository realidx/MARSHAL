"""Two-player teaching reductions and explicit solver failures; no training."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, VERSION, GAME_VERSION
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_bp_curriculum import acceptable


def fixture(types=((1,1),(-1,1)), own=(1,1), schedule=(1,0), layout=(2,1)):
    requirements = [[(0,g),(1,0)] if layout==(2,1) else [(0,0),(1,g)] for g in range(2)]
    return dict(id='minimal-two-player',ego=0,own_preferences=list(own),history=[],
        type_catalogues={'0':[list(own)],'1':[list(row) for row in types]},
        game=dict(n_players=2,n_actions_per_player=list(layout),max_changes=1,menu_enabled=False,
            round_robin=list(schedule),goals=[dict(goal_id=g,binary=True,
                required_actions=[dict(player_id=p,action_id=a) for p,a in req])
                for g,req in enumerate(requirements)]))


def offer(goal, actor=0):
    vector=[int(g==goal) for g in range(2)]
    return dict(action='OFFER',partner_id=1-actor,
                proposer_action=vector if actor==0 else [1],
                partner_action=[1] if actor==0 else vector)


def audit(out):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    cases=[]
    def belief_case(name,raw,prefix,events,expected):
        e=PrivateEpisode(raw,prefix)
        native=audit_native(e.tree)
        before=e.belief(1,0,observer=0,own=raw['own_preferences'])
        checkpoints=[before]
        for action in events:
            e.observe(action)
            checkpoints.append(e.belief(1,0,observer=0,own=raw['own_preferences']))
        after=checkpoints[-1]
        assert (after['possible_preferences'],after['favored'])==expected
        cases.append(dict(name=name,kind='B',raw=raw,setup=prefix,events=events,
            checkpoints=checkpoints,nodes=len(e.tree.entries),native=native,certificate=e.tree.certificate))
    raw=fixture(types=((1,1),(0,1),(-1,1)))
    for response,expected in [('ACCEPT',(['want','neutral'],'undetermined')),('REJECT',(['avoid'],'avoid'))]:
        belief_case('one_response_'+response.lower(),raw,[{'action':'PASS'},offer(0)],
                     [{'response':response}],expected)
    belief_case('irrelevant_goal_response_maintains_three',raw,[{'action':'PASS'},offer(1)],
                 [{'response':'ACCEPT'}],(['want','neutral','avoid'],'undetermined'))
    raw=fixture(schedule=(0,1))
    belief_case('one_offer_forms_singleton',raw,[{'action':'PASS'}],[offer(0,actor=1)],(['want'],'want'))
    belief_case('one_offer_changes_favored_only',raw,[{'action':'PASS'}],[offer(1,actor=1)],(['want','avoid'],'avoid'))
    belief_case('later_response_maintains_favored',raw,[{'action':'PASS'}],
                 [offer(1,actor=1),{'response':'ACCEPT'}],(['want','avoid'],'avoid'))
    posterior=cases[-1]['checkpoints']
    assert posterior[-1]==posterior[-2]
    assert abs(posterior[-1]['preference_weights']['avoid']-2/3)<1e-9

    for label,types,own,facts in [
        ('complete_own_gain',((1,1),),(1,0),()),
        ('complete_altruistic_tie',((-1,1),),(1,0),()),
        ('incomplete_last_turn',((1,-1),(-1,1)),(1,1),()),
        ('private_result_want',((1,-1),(-1,1)),(1,1),((1,0,1),)),
        ('private_result_avoid',((1,-1),(-1,1)),(1,1),((1,0,-1),)),
    ]:
        raw=fixture(types=types,own=own,schedule=(1,0,1,0) if facts else (1,0))
        prefix=[{'action':'PASS'}]
        if facts:
            prefix += [{'action':'INVESTIGATE','player':1,'goal':0},{'action':'PASS'}]
        e=PrivateEpisode(raw,prefix)
        row=e.choices(own,facts)
        accepted=[row['actions'][i] for i in acceptable(row['values'],0, actions=row['actions'])]
        expected=[offer(0)] if label in ('complete_own_gain','private_result_want') else [offer(1)]
        if label=='incomplete_last_turn':expected=[offer(0),offer(1)]
        assert accepted==expected
        cases.append(dict(name=label,kind='P',raw=raw,setup=prefix,private_results=facts,
            values=row,acceptable_actions=accepted,nodes=len(e.tree.entries),
            native=audit_native(e.tree),certificate=e.tree.certificate,
            scope='Result-use setup is imposed; not a claim that the earlier query was optimal' if facts else 'Final native decision'))

    # Full acquisition decisions: preserve intervening partner decisions. These
    # probes do not silently change initialization to escape cycles.
    probes=[]
    for label,types,own,layout in [
        ('shared_wanted_goal',((1,1),(-1,1)),(1,1),(2,1)),
        ('overlap_with_own_conflict',((1,1),(-1,1)),(1,-1),(2,1)),
        ('opposed_teaching_types',((1,-1),(-1,1)),(1,1),(2,1)),
        ('opposed_types_partner_two_choices',((1,-1),(-1,1)),(1,1),(1,2)),
    ]:
        raw=fixture(types=types,own=own,layout=layout,schedule=(1,0,1,0))
        started=time.monotonic()
        entry=dict(name=label,raw=raw,setup=[{'action':'PASS'}],max_nodes=20000,seconds_budget=6)
        try:
            e=PrivateEpisode(raw,entry['setup'],max_nodes=20000,seconds=6)
            row=e.choices(own)
            accepted=acceptable(row['values'],0, actions=row['actions'])
            entry.update(status='solved',nodes=len(e.tree.entries),certificate=e.tree.certificate,
                native=audit_native(e.tree),root=row,all_legal_accepted=len(accepted)==len(row['actions']))
        except SearchLimit as exc:
            entry.update(status='no_label',reason=str(exc))
        entry['seconds']=time.monotonic()-started
        probes.append(entry)
    summary=dict(version=VERSION,game_version=GAME_VERSION,actual_LM=False,training_ready=False,
        teaching_only=True,cases=len(cases),B=sum(c['kind']=='B' for c in cases),P=sum(c['kind']=='P' for c in cases),
        players=2,goals=2,commitment_slots=3,
        max_short_case_nodes=max(c['nodes'] for c in cases),
        acquisition_probes=[{k:v for k,v in p.items() if k in ('name','status','nodes','reason','seconds','all_legal_accepted')} for p in probes],
        scope='Hand-designed valid B/P teaching games; no change to random outcome self-play distribution',
        limitations=['No full acquisition probe supplies a discriminative positive yet',
            'Two-player cases do not replace third-party private-information viewpoint tests',
            'Reward/task export and optimizer integration remain separate work'])
    for name,rows in [('cases.jsonl',cases),('acquisition_probes.jsonl',probes)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    print(json.dumps(audit(parser.parse_args().out),ensure_ascii=False,indent=2))
