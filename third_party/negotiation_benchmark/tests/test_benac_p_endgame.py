from dataclasses import replace
import numpy as np
import pytest
from benac_p.schema import GameSpec, Goal, ActionRef, Offer, OfferProposal, PassProposal, ResponseAction, MenuOffer
from benac_p.endgame import Endgame, Node, SearchLimit
from benac_p.endgame_partner import immediate_reference, RationalPartner, transcript_actions


def spec():
    return GameSpec(3, (1,1,1), (Goal(0,(ActionRef(0,0),ActionRef(1,0))),
                                Goal(1,(ActionRef(1,0),ActionRef(2,0)))),
                    np.array([[1,0],[1,1],[0,1]]), (0,1,2), 1, 4, menu_enabled=True)


def game(kernel=immediate_reference):
    return Endgame(spec(), 0, (1,0), {1: ((1,1),(-1,1)), 2: ((0,1),(0,-1))}, kernel)


def test_independent_types_and_full_native_actions():
    g=game();root=g.initial()
    assert len(root.worlds)==4
    assert g.actions(root)==root.state.legal_proposals()
    assert {a.offer.partner_id for a in g.actions(root) if isinstance(a,OfferProposal)}=={1,2}
    assert any(isinstance(a,OfferProposal) and isinstance(a.offer,MenuOffer) for a in g.actions(root))
    assert not g.spec.private_preferences.any()


def test_partner_proposal_is_evidence_and_ego_response_not_skipped():
    g=game();branches=g.step(g.initial(),PassProposal())
    assert sum(b.weight for b in branches)==pytest.approx(1)
    pending=[b for b in branches if b.node.pending is not None]
    assert pending
    for b in pending:
        assert g.actor(b.node)==0
        assert b.node.state.current_proposer()!=0
        assert set(g.actions(b.node))==set(response_actions(b.node.pending))
        assert b.evidence[-1]['player_id']!=0


from benac_p.schema import response_actions


def test_native_history_round_trip_and_impossible_history_rejected():
    g=game();a=OfferProposal(Offer(1,(1,),(1,)))
    node=g.replay([a,ResponseAction('ACCEPT')])
    assert len(node.worlds)==2
    assert all(w[1][0]==1 for w in node.worlds)
    assert transcript_actions(node.state.public_state()['transcript'])==[a,ResponseAction('ACCEPT')]
    with pytest.raises(ValueError):
        g.replay([a,ResponseAction('CHOOSE_1')])


def test_ego_action_not_evidence_and_exact_search_limits():
    g=game();node=g._apply(g.initial(),PassProposal())
    assert node.worlds==g.worlds
    g.max_remaining_turns=1
    with pytest.raises(SearchLimit):g.q_values(g.initial())
    with pytest.raises(ValueError):g.utility(g.initial())
    with pytest.raises(ValueError):Endgame(replace(spec(),round_robin=(0,0,0)),0,(1,0),{1:((1,1),),2:((0,1),)},immediate_reference)


def test_exact_rational_partner_uses_own_information_only():
    s=spec();types={0:((1,0),),1:((1,1),(-1,1)),2:((0,1),)}
    partner=RationalPartner(s,types,max_nodes=2000)
    g=Endgame(s,0,(1,0),{1:types[1],2:types[2]},partner)
    a=OfferProposal(Offer(1,(1,),(1,)))
    branches=g.step(g.initial(),a)
    assert sum(b.weight for b in branches)==pytest.approx(1)
    assert partner.labels
    # No realized matrix is retained by the partner/search implementation.
    assert not partner.spec.private_preferences.any()
    assert any(b.evidence for b in branches)


def test_menu_history_round_trip():
    g=game()
    menu=OfferProposal(MenuOffer((Offer(1,(1,),(0,)),Offer(1,(1,),(1,)))))
    node=g.replay([menu,ResponseAction('CHOOSE_2')])
    assert transcript_actions(node.state.public_state()['transcript'])==[menu,ResponseAction('CHOOSE_2')]
    assert node.state.snapshot_commitments()==((1,),(1,),(0,))


def test_search_values_match_direct_world_enumeration():
    g=game();root=g.initial();q=g.q_values(root)
    # At a final ego response there is no hidden-type utility arithmetic: check
    # the solver against direct GameState terminal reward for every legal act.
    s=replace(spec(),round_robin=(1,2,0))
    h=Endgame(s,0,(1,0),{1:((1,1),),2:((0,1),)},immediate_reference)
    node=h.initial();node.state.turn_index=2
    vals=h.q_values(node)
    for a,v in vals:
        outcomes=h.step(node,a)
        assert all(b.node.state.is_terminal for b in outcomes)
        expected=sum(b.weight*np.dot(h.own,b.node.state.goal_satisfaction()) for b in outcomes)
        assert v==pytest.approx(expected)
    assert all(np.isfinite(v) for _,v in q)


def test_native_suite_synthetic_check_and_measurement_gate(tmp_path):
    import json
    from pathlib import Path
    from benac_p.endgame_diagnose import main
    fixtures=Path(__file__).resolve().parents[3]/'examples/benac_p/fixtures/native_smoke.json'
    out=tmp_path/'oracle'
    main(['--fixtures',str(fixtures),'--output-dir',str(out),'--oracle-check'])
    result=json.loads((out/'scores.json').read_text())
    assert all(r['belief_exact']==1 for r in result['cases'])
    assert all(r.get('OL',0)==0 and r.get('LL',0)==0 for r in result['cases'])
    main(['--fixtures',str(fixtures),'--output-dir',str(out),'--oracle-check','--resume'])
    # Never spend model calls or present a synthetic fixture as a research run.
    with pytest.raises(SystemExit):
        main(['--fixtures',str(fixtures),'--output-dir',str(tmp_path/'model')])


def test_joint_semantic_profiles_have_independent_prior_and_native_tools():
    from itertools import product
    from benac_p.endgame_diagnose import Fixture,Suite,measure
    from benac_p.diagnose_protocol import submission_tool
    raw=dict(id='joint-smoke',ego=0,game=spec().to_dict(include_private=False),
             own_preferences=[1,0],query=dict(player=1,goals=[0,1]),history=[],
             type_catalogues={'0':[[1,0]],'1':[list(r) for r in product((1,0,-1),repeat=2)],'2':[[0,0]]})
    f=Fixture(raw);suite=Suite([f]).build()
    assert len(f.root.worlds)==9
    assert f.belief_options[0]=='G0=want, G1=want'
    task=suite.tasks[0]
    schema=submission_tool(task)['function']['parameters']['properties']['possible_preferences']
    assert schema['maxItems']==9 and len(schema['items']['enum'])==9
    records={}
    for t in suite.tasks:records[t['id']]=dict(status='ok',answer=suite.answer(t,records))
    result=measure(suite,records)
    assert all(row['belief_exact']==1 for row in result['cases'])
    bad=dict(raw,type_catalogues=dict(raw['type_catalogues'],**{'1':[[1,1],[0,0],[-1,-1]]}))
    with pytest.raises(ValueError,match='Cartesian-product'):
        Fixture(bad)


def test_belief_task_does_not_reveal_history_posterior_as_initial_information():
    from benac_p.endgame_diagnose import Fixture,Suite
    raw=dict(id='history-belief',ego=0,game=replace(spec(),round_robin=(1,0,2)).to_dict(include_private=False),
             own_preferences=[1,0],query=dict(player=1,goal=0),
             type_catalogues={'0':[[1,0]],'1':[[1,0],[0,0],[-1,0]],'2':[[0,0]]},
             history=[OfferProposal(Offer(0,(1,),(1,))).to_dict()])
    f=Fixture(raw);suite=Suite([f]).build()
    t=suite.tasks[0]
    assert f.support(f.root)==['want']
    assert t['input']['initially_possible_preferences']==['want','neutral','avoid']
    assert suite.labels[t['id']]['support']==['want']


def test_planning_pairs_keep_full_history_and_replace_only_judgment():
    from copy import deepcopy
    from benac_p.endgame_diagnose import Fixture, Suite
    raw=dict(id='paired-history',ego=0,game=replace(spec(),round_robin=(1,0,2)).to_dict(include_private=False),
             own_preferences=[1,0],query=dict(player=1,goal=0),
             type_catalogues={'0':[[1,0]],'1':[[1,0],[0,0],[-1,0]],'2':[[0,0]]},
             history=[OfferProposal(Offer(0,(1,),(1,))).to_dict()])
    f=Fixture(raw);suite=Suite([f]).build()
    records={t['id']:dict(status='ok',answer=suite.answer(t,{}))
             for t in suite.tasks if t['kind']=='semantic_belief'}
    root='paired-history/root'
    records[root+'/belief']['answer']={'possible_preferences':['avoid']}
    tasks={t['id']:t for t in suite.tasks}
    for cid,case in suite.cases.items():
        if not case['q']:continue
        oracle=suite.payload(tasks[cid+'/plan_oracle'],records)
        model=suite.payload(tasks[cid+'/plan_model'],records)
        assert oracle['history']==model['history']==f.history_text(case['node'])
        assert oracle['history']  # Includes the pending original proposal.
        assert oracle['initially_possible_preferences']==['want','neutral','avoid']
        assert oracle['history'][0]['action'].startswith('OFFER')
        a,b=deepcopy(oracle),deepcopy(model)
        a.pop('partner_judgment');b.pop('partner_judgment')
        assert a==b
    assert suite.payload(tasks[root+'/plan_oracle'],records)['partner_judgment']['possible_preferences']==['want']
    assert suite.payload(tasks[root+'/plan_model'],records)['partner_judgment']['possible_preferences']==['avoid']
    assert not f.search.markov_partner


def test_next_ego_response_is_measured_not_automatically_folded():
    from benac_p.endgame_diagnose import Fixture, Suite
    raw=dict(id='response-window',ego=0,game=spec().to_dict(include_private=False),
             own_preferences=[1,0],query=dict(player=1,goal=0),history=[],
             type_catalogues={'0':[[1,0]],'1':[[1,0],[0,0],[-1,0]],'2':[[0,0]]})
    f=Fixture(raw)
    branches=f.window_step(f.root,PassProposal())
    offers=[b for b in branches if b.node.pending is not None]
    assert offers
    for b in offers:
        assert f.search.actor(b.node)==f.ego and b.node.state.turn_index==1
        assert ResponseAction('ACCEPT') in f.search.actions(b.node)
        assert f.history_text(b.node)[-1]['action'].startswith('OFFER')
    suite=Suite([f]).build()
    assert any(t['kind']=='planning' and t['input']['pending_offer'] for t in suite.tasks)
