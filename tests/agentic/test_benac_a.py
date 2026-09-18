import json
from pathlib import Path
from copy import deepcopy
import pytest
from examples.final_evaluation.benac_a_suite import DEFAULT, load
from examples.final_evaluation.benac_a import run_game, summarize, complete
from training.social_mixed.core import load_data
from training.social_mixed.structure_coverage import geometry_id


def reply(name='PASS',finish='stop'):
    return dict(completion=dict(finish_reason=finish,raw_message=dict(content='test',tool_calls=[dict(function=dict(name=name,arguments='{}'))])),usage=dict(completion_tokens=1))


def test_frozen_structure_split_and_scale():
    m,rows=load();data=load_data()
    train={geometry_id(r.get('raw',r.get('input'))['game']) for k,rs in data.items() if k.endswith('train') for r in rs}
    seen={geometry_id(r.get('raw',r.get('input'))['game']) for rs in data.values() for r in rs}
    assert len(rows)==16
    for r in rows:
        assert r['players']==3 and r['raw']['game']['n_actions_per_player']==[2,2,2]
        assert len(r['raw']['game']['goals'])==3
        assert len({g['binary'] for g in r['raw']['game']['goals']})==1
        assert (r['structure_family'] in train) if r['evaluation_split']=='ID' else (r['structure_family'] not in seen)
    assert len({r['structure_family'] for r in rows if r['evaluation_split']=='OOD'})==8


def test_routing_uses_focal_only_at_selected_seat(tmp_path):
    row=load()[1][0];routes={'focal':{'model':'M'},'q0':{'model':'Q0'}};seen=[]
    def generate(route,request):seen.append(route['model']);return reply()
    result=run_game(row,1,routes,tmp_path,generate)
    assert result['status']=='terminal'
    expected=['M' if p==1 else 'Q0' for p in row['raw']['game']['round_robin']]
    assert seen==expected


@pytest.mark.parametrize('finish,status',[('length','truncated_response'),('stop','invalid_action')])
def test_protocol_failure_preserves_missing_utility(tmp_path,finish,status):
    r=run_game(load()[1][0],0,{'focal':{},'q0':{}},tmp_path,lambda *_:reply('INVALID',finish))
    assert r['status']==status and r['focal_utility'] is None and r['calls']==2
    s=summarize([r])['strata']['ID/all']
    assert s['completion_rate']==0 and s['terminal_focal_utility_mean'] is None
    assert s['full_cohort_focal_utility_bounds']==r['missing_utility_bounds']


def test_infrastructure_failure_not_protocol_penalty(tmp_path):
    def fail(*_):raise TimeoutError('server unavailable')
    r=run_game(load()[1][0],0,{'focal':{},'q0':{}},tmp_path,fail)
    assert r['status']=='infrastructure_failure' and r['invalid_calls']==0
    assert r['protocol']==[0,0,0] and r['focal_utility'] is None
    assert summarize([r])['strata']['ID/all']['full_cohort_focal_utility_bounds'] is None


def test_initial_requests_independent_of_hidden_partner_world(tmp_path):
    from training.social_mixed.core import Episode
    row=load()[1][0];ep=Episode(row,row['id'],0,42);actor=ep.rules.actor(ep.node)
    other=deepcopy(row)
    other['realized_world']=next(w for w in ep.rules.worlds if w[actor]==ep.world[actor] and w!=ep.world)
    alt=Episode(other,row['id'],0,42)
    assert ep.request()==alt.request()
