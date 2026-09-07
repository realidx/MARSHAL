from types import SimpleNamespace
from pathlib import Path
import json
from benac_p.schema import PassProposal, ResponseAction
from benac_p.dependency_certificate import certify
from benac_p.endgame_diagnose import Fixture, selection_readiness


def fake_fixture(frozen_q):
    # A two-action continuation with a strict updated preference; this isolates
    # the anti-tie-cherry-picking contract, not native game legality.
    root=SimpleNamespace(name='root');state=SimpleNamespace(is_terminal=False,snapshot_commitments=lambda:((0,),(0,),(0,)))
    updated=SimpleNamespace(name='updated',state=state,pending=None)
    frozen=SimpleNamespace(name='frozen')
    actions=(ResponseAction('REJECT'),ResponseAction('ACCEPT'))
    def q(node):
        if node is root:return ((PassProposal(),1.),)
        return tuple(zip(actions,(0.,1.) if node is updated else frozen_q))
    return SimpleNamespace(root=root,search=SimpleNamespace(q_values=q),
        window_step=lambda n,a:(SimpleNamespace(weight=1.,node=updated),),
        with_judgment=lambda n,s:frozen,support=lambda n:['want','avoid'] if n is root else ['want'],
        history_text=lambda n:[dict(player='P1',action='ACCEPT')])


def test_update_certificate_requires_strict_gain_even_with_favorable_frozen_ties():
    assert not certify(fake_fixture((1.,1.)))['passed']
    c=certify(fake_fixture((1.,0.)))
    assert c['passed'] and c['expected_strict_update_gain']==1.
    assert c['witnesses'][0]['frozen_optimal_indices']==[0]
    assert c['witnesses'][0]['updated_optimal_indices']==[1]


def test_old_information_only_opportunities_cannot_pass_dependency_gate():
    c=dict(split='discovery',bundle='old',same_action_update_gain=0.,evidence_channel_span=1.)
    result=selection_readiness(SimpleNamespace(certificates={'old':c}),1,dependency_only=True)
    assert not result['passed'] and result['independent_games']['discovery']==0


def test_known_native_position_has_no_update_value():
    path=Path(__file__).resolve().parents[3]/'examples/benac_p/fixtures/native_validation.json'
    raw=json.loads(path.read_text())['fixtures'][0]
    result=certify(Fixture(raw))
    assert not result['passed']


def test_real_native_menu_has_strictly_valuable_update_and_measured_witness():
    from benac_p.endgame_diagnose import Suite
    from benac_p.dependency_certificate import attach
    path=Path(__file__).resolve().parents[3]/'examples/benac_p/fixtures/dependency_validation.json'
    raw=json.loads(path.read_text())['fixtures'][0]
    f=Fixture(raw);proof=certify(f)
    assert proof['passed'] and proof['first_action']['action']=='MENU'
    assert abs(proof['expected_strict_update_gain']-1/3)<1e-9
    assert proof['witnesses'][0]['strict_gap']==1.
    suite=Suite([f]).build();attach(suite,{f.id:proof})
    cert=suite.certificates[f.id]
    assert cert['condition']=='dependency'
    assert cert['root_condition']=='unknown_irrelevant'  # Root ties do not erase continuation dependence.
    assert suite.cases[cert['primary_case']]['node'].pending is None
    q=suite.cases[cert['primary_case']]['q']
    assert max(v for _,v in q)==5.
