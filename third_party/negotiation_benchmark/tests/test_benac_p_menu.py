"""Binding menu semantics, inference, exact values and native protocol."""
from dataclasses import replace
import math
import numpy as np
import pytest
from benac_p import (
    ActionRef, BayesPlanner, ExactBayesFilter, GameRunner, GameSpec, GameState,
    Goal, InvalidActionError, MenuOffer, Offer, OfferProposal, Preference,
    ResponseAction, ScriptedPolicy, SoftProgressPolicy, VLLMPlayerPolicy,
    build_player_observation,
)
from benac_p.schema import response_actions


def spec():
    return GameSpec(3, (2, 1, 1), (
        Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),
        Goal(1, (ActionRef(0, 1), ActionRef(1, 0), ActionRef(2, 0))),
    ), np.array([[1, 1], [1, -1], [-1, 1]]), (0, 0), 1, 7, menu_enabled=True)


def menu():
    return MenuOffer((Offer(1, (1, 0), (1,)), Offer(1, (0, 1), (1,))))


@pytest.mark.parametrize('response,expected', [
    ('REJECT', ((0, 0), (0,), (0,))),
    ('CHOOSE_1', ((1, 0), (1,), (0,))),
    ('CHOOSE_2', ((0, 1), (1,), (0,))),
])
def test_only_selected_option_binds_once(response, expected):
    state = GameState(spec()); event = state.resolve_offer(menu(), response)
    assert state.turn_index == 1 and state.snapshot_commitments() == expected
    assert event.action == 'MENU' and event.offer == menu()
    assert event.to_dict()['offer']['offers'] == [o.to_dict() for o in menu().offers]
    view = build_player_observation(state, 0).to_agent_dict()
    assert len(view['transcript'][0]['options']) == 2
    assert view['transcript'][0]['response'] == response


def test_invalid_menu_and_response_are_atomic():
    with pytest.raises(ValueError): MenuOffer((menu().offers[0],)*2)
    with pytest.raises(ValueError): MenuOffer((menu().offers[0], Offer(2, (0,1), (1,))))
    state = GameState(spec())
    for offer,response in [(menu(),'ACCEPT'), (menu().offers[0],'CHOOSE_1')]:
        with pytest.raises(InvalidActionError): state.resolve_offer(offer,response)
        assert state.turn_index == 0 and not state.commitments.any()
    with pytest.raises(InvalidActionError): GameState(replace(spec(),menu_enabled=False)).resolve_offer(menu(),'CHOOSE_1')
    with pytest.raises(InvalidActionError): state.resolve_offer(MenuOffer((menu().offers[0],Offer(1,(1,1),(1,)))), 'REJECT')


def test_menu_grounding_and_order_equivariance():
    state=GameState(spec()); m=menu(); policy=SoftProgressPolicy()
    obs=build_player_observation(state,1,pending_proposer_id=0,pending_offer=m)
    view=obs.to_agent_dict()
    assert [v['your_utility_if_terminal'] for v in view['if_chosen']] == [1,0]
    assert 'all_preferences' not in view
    assert view['pending_offer']['responses'] == ['CHOOSE_1','CHOOSE_2','REJECT']
    p=[p for _,p in policy.response_distribution(obs,m)]
    reverse=MenuOffer(m.offers[::-1])
    q=[p for _,p in policy.response_distribution(replace(obs,pending_offer=reverse),reverse)]
    assert p == pytest.approx([q[0],q[2],q[1]])
    assert sum(p) == pytest.approx(1) and min(p)>0
    proposal_obs=build_player_observation(state,0)
    assert set(proposal_obs.legal_proposals)==set(state.legal_proposals())
    assert sum(p for _,p in policy.proposal_distribution(proposal_obs))==pytest.approx(1)


def test_filter_joint_choice_likelihood_replay_and_pending_dedup():
    state=GameState(spec()); obs=build_player_observation(state,0)
    filt=ExactBayesFilter(obs); prior=filt.belief; m=menu(); policy=SoftProgressPolicy()
    filt.observe_proposal(OfferProposal(m)); assert filt.belief==prior
    robs=build_player_observation(state,1,pending_proposer_id=0,pending_offer=m)
    likelihood=[policy.response_probability(replace(robs,own_preferences=h[0]),m,ResponseAction('CHOOSE_2')) for h in prior.hypotheses]
    expected=np.array(prior.probabilities)*likelihood;expected/=expected.sum()
    filt.observe_response('CHOOSE_2');state.resolve_offer(m,'CHOOSE_2')
    assert filt.belief.probabilities==pytest.approx(expected)
    replay=ExactBayesFilter(build_player_observation(state,0))
    assert replay.belief==filt.belief
    assert replay.synchronize(build_player_observation(state,0))==filt.belief
    # The partner's MENU proposal is itself evidence for an ego responder.
    state=GameState(replace(spec(),round_robin=(1,0)))
    m=MenuOffer((Offer(0,(1,),(1,0)),Offer(0,(1,),(0,1))))
    pending=build_player_observation(state,0,pending_proposer_id=1,pending_offer=m)
    filt=ExactBayesFilter(pending);before=filt.belief
    state.resolve_offer(m,'CHOOSE_1');filt.synchronize(build_player_observation(state,0))
    assert filt.belief==before and sum(u['is_evidence'] for u in filt.updates)==1


def test_last_turn_menu_values_match_independent_expectation():
    state=GameState(replace(spec(),round_robin=(0,)))
    obs=build_player_observation(state,0);belief=ExactBayesFilter(obs).belief
    result=BayesPlanner().solve(obs,belief);m=menu()
    robs=build_player_observation(state,1,pending_proposer_id=0,pending_offer=m)
    expected=0
    for h,p in zip(belief.hypotheses,belief.probabilities):
        for response,q in SoftProgressPolicy().response_distribution(replace(robs,own_preferences=h[0]),m):
            child=state.clone();child.resolve_offer(m,response);expected+=p*q*child.reward(0)
    actual=next(v.value for v in result.action_values if v.action==OfferProposal(m))
    # Enumeration stores unordered menus in engine order, so also try reversed.
    assert actual==pytest.approx(expected)


class Client:
    def complete(self,**kwargs): raise AssertionError('legacy path')
    def complete_with_tools(self,messages,**kwargs):
        names=[t['function']['name'] for t in kwargs['tools']]
        if 'MENU' in names:
            return {'tool_calls':[{'name':'MENU','arguments':{'options':[
                {'partner':'P1','self_commitments':['A0'],'partner_commitments':['A0']},
                {'partner':'P1','self_commitments':['A1'],'partner_commitments':['A0']},
            ]}}]}
        return {'tool_calls':[{'name':'CHOOSE_2','arguments':{}}]}


def test_native_menu_and_runner_protocol():
    state=GameState(spec()); llm=VLLMPlayerPolicy(Client())
    action=llm.propose(build_player_observation(state,0)); assert action.offer==menu()
    obs=build_player_observation(state,1,pending_proposer_id=0,pending_offer=menu())
    assert llm.respond(obs,menu())==ResponseAction('CHOOSE_2')
    result=GameRunner(replace(spec(),round_robin=(0,)),[llm,llm,ScriptedPolicy()]).run()
    assert result.transcript[0].action=='MENU' and result.final_commitments==((0,1),(1,),(0,))
    with pytest.raises(InvalidActionError): llm._decode_responder_call({'name':'ACCEPT','arguments':{}},menu())


def test_certified_active_menu_and_same_state_belief_intervention():
    from benac_p.menu_diagnose import fixture, root_comparison
    game,prior,policies=fixture()
    result=root_comparison(game,prior,policies)
    best=result['adaptive_best']; frozen=result['frozen_best']
    assert best['action']['action']=='MENU' and frozen['action']['action']=='OFFER'
    assert best['adaptive']==pytest.approx(1.6730712950427735)
    assert result['root_action_regret']>0.16
    assert result['same_menu_update_gain']>0.16
    # Both options yield identical immediate ego utility, despite different states.
    obs=build_player_observation(GameState(game),0)
    assert [obs.state_facts(obs.commitments_if_accepted(Offer(**o)))['your_utility_if_terminal'] for o in best['action']['offers']]==[1,1]
    first=next(b for b in best['branches'] if b['response']=='CHOOSE_1')
    assert first['posterior'][0]==pytest.approx(.8225776331594974)
    assert first['adaptive_action']['partner_id']==2 and first['frozen_action']['partner_id']==1
    # No type uncertainty => Bayesian and frozen-prior continuation coincide.
    known=replace(prior,hypotheses=(prior.hypotheses[0],),log_probabilities=(0.,))
    control=root_comparison(game,known,policies)
    assert all(abs(r['adaptive']-r['frozen'])<1e-10 for r in control['rows'])
    reversed_menu=OfferProposal(MenuOffer(tuple(Offer(**o) for o in best['action']['offers'][::-1])))
    assert BayesPlanner(partner_policies=policies).solve(obs,prior).regret(reversed_menu)==pytest.approx(0)


def test_diagnostic_oracle_answers_and_invalid_outputs():
    from benac_p.menu_diagnose import export_tasks, score_answers
    tasks,labels=export_tasks();answers=[]
    assert len(tasks)==11 and all('q_values' not in t['input'] for t in tasks)
    for label in labels:
        if 'posterior' in label: answers.append({'id':label['id'],'probabilities':label['posterior']})
        else:answers.append({'id':label['id'],'action_index':int(np.argmax(label['q_values']))})
    scores=score_answers(tasks,labels,answers)
    assert scores['valid']==11
    for row in scores['results']:
        assert row.get('regret',0)<1e-10
        assert row.get('total_variation',0)<1e-10
        assert row.get('oracle_planner_with_model_belief_regret',0)<1e-10
    broken=[{'id':tasks[0]['id'],'action_index':True}]
    scores=score_answers(tasks,labels,broken)
    assert scores['valid']==0 and scores['results'][0]['status']=='invalid'
    with pytest.raises(ValueError):score_answers(tasks,labels,[answers[0],answers[0]])
