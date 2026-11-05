"""Small exact menu diagnostic: export, run against a chat endpoint, and score.

This is a constructed mechanism check, not evidence of population-level LLM
weakness. The two-turn schedule and explicit correlated two-type prior are
public experimental assumptions, distinct from the default game generator.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
import os
from pathlib import Path

import numpy as np

from benac_p.bayes_planner import BayesPlanner
from benac_p.belief import BeliefState, ExactBayesFilter, FinitePreferencePrior, condition_belief
from benac_p.controlled import SoftProgressPolicy
from benac_p.observations import build_player_observation
from benac_p.schema import ActionRef, GameSpec, Goal, MenuOffer, Offer, OfferProposal, PassProposal, VALUE_TO_PREFERENCE, response_actions
from benac_p.state import GameState


def fixture():
    requirements = (((0,0),(1,0)), ((0,0),(0,1),(2,0)), ((0,1),(1,0)),
                    ((0,0),(1,1),(2,0)), ((0,0),(1,0),(2,0)))
    prefs = ((1,-1,1,1,0), (1,1,-1,0,0), (1,0,0,1,-1))
    spec = GameSpec(3, (2,2,1), tuple(Goal(i,tuple(ActionRef(*a) for a in req)) for i,req in enumerate(requirements)),
                    np.array(prefs), (0,0), 1, 597, menu_enabled=True)
    hypotheses = tuple(tuple(tuple(VALUE_TO_PREFERENCE[v] for v in row) for row in (p1,prefs[2]))
                       for p1 in (prefs[1], (1,-1,1,-1,-1)))
    belief = BeliefState((1,2),hypotheses,(-math.log(2),)*2)
    policy = SoftProgressPolicy(seed=0,temperature=.25)
    return spec,belief,{1:policy,2:SoftProgressPolicy(seed=1,temperature=.25)}


def root_comparison(spec, prior, policies):
    """Full adaptive Q vs a precisely specified frozen-prior continuation rule.

    After the first outcome, the frozen rule chooses a final action optimal
    under the initial prior at the actual physical state. Its return is then
    evaluated under the TRUE posterior. Latent types persist throughout.
    This baseline is policy-restricted; the gap is not a pure information
    causal effect because outcomes also change physical state.
    """
    if spec.round_robin != (0,0):
        raise ValueError("This diagnostic comparison requires exactly two ego turns.")
    state=GameState(spec); planner=BayesPlanner(partner_policies=policies)
    obs=build_player_observation(state,0); oracle=planner.solve(obs,prior)
    rows=[]
    for item in oracle.action_values:
        action=item.action; frozen=0.0; adaptive=0.0; branches=[]
        if isinstance(action,PassProposal):
            child=state.clone();child.apply_pass()
            value=planner.solve(build_player_observation(child,0),prior).value
            rows.append(dict(action=action.to_dict(),adaptive=value,frozen=value,branches=[]))
            continue
        offer=action.offer;actor=offer.partner_id
        robs=build_player_observation(state,actor,pending_proposer_id=0,pending_offer=offer)
        for response in response_actions(offer):
            likelihood=[policies[actor].response_probability(replace(robs,own_preferences=h[actor-1]),offer,response) for h in prior.hypotheses]
            posterior,logp=condition_belief(prior,likelihood); probability=math.exp(logp)
            child=state.clone();child.resolve_offer(offer,response)
            child_obs=build_player_observation(child,0)
            result=planner.solve(child_obs,posterior); frozen_result=planner.solve(child_obs,prior)
            frozen_value=next(v.value for v in result.action_values if v.action==frozen_result.action)
            adaptive+=probability*result.value;frozen+=probability*frozen_value
            branches.append(dict(response=response.value,probability=probability,posterior=list(posterior.probabilities),
                                 commitments=child.snapshot_commitments(),adaptive_action=result.action.to_dict(),
                                 frozen_action=frozen_result.action.to_dict(),adaptive_value=result.value,frozen_value=frozen_value))
        if not math.isclose(adaptive,item.value,abs_tol=1e-10):
            raise AssertionError("Branch calculation disagrees with full expectimax.")
        rows.append(dict(action=action.to_dict(),adaptive=adaptive,frozen=frozen,branches=branches))
    best=max(rows,key=lambda r:r['adaptive']); frozen_best=max(rows,key=lambda r:r['frozen'])
    return dict(rows=rows,oracle=oracle.to_dict(),adaptive_best=best,frozen_best=frozen_best,
                root_action_regret=best['adaptive']-frozen_best['adaptive'],
                same_menu_update_gain=best['adaptive']-best['frozen'])


def decision_cases():
    spec,prior,policies=fixture();state=GameState(spec)
    planner=BayesPlanner(partner_policies=policies)
    root=planner.solve(build_player_observation(state,0),prior)
    menu=root.action.offer
    if not isinstance(menu,MenuOffer):raise AssertionError("Expected informative menu at root.")
    cases=[('root',state,prior)]
    for response in response_actions(menu):
        child=state.clone();child.resolve_offer(menu,response)
        obs=build_player_observation(child,0)
        posterior=ExactBayesFilter(obs,prior=FinitePreferencePrior(prior),partner_policies=policies).belief
        cases.append((response.value,child,posterior))
    return spec,prior,policies,cases


RULES = """You control P0 in BENAC-P. Goals are ALL_OF; terminal utility is the sum of your preferences (+1 WANT, 0 NEUTRAL, -1 AVOID) on satisfied goals. Offers contain FINAL target commitment vectors. Commitments cannot be undone. A single offer may be ACCEPTed or REJECTed. A MENU contains two distinct offers to the same partner; CHOOSE_1/CHOOSE_2 binds only that option, REJECT binds neither. PASS or a resolved offer/menu consumes one scheduled proposer turn. Partners have persistent hidden preference rows drawn once from the supplied public joint prior, and follow the supplied public stochastic policy. Ego's own proposals are interventions, not evidence about partners. All legal actions are supplied with zero-based indices. State facts describe current utility, not future value. Return only the requested JSON object."""


def export_tasks():
    spec,prior,policies,cases=decision_cases();tasks=[];labels=[]
    planner=BayesPlanner(partner_policies=policies)
    for name,state,posterior in cases:
        obs=build_player_observation(state,0);result=planner.solve(obs,posterior)
        public=dict(observation=obs.to_agent_dict(),initial_prior=prior.to_dict(),
                    partner_policy={str(i):p.specification() for i,p in policies.items()})
        if name!='root':
            tasks.append(dict(id=name+'/belief',kind='belief',input=public,
                              output_schema={'probabilities':'array of posterior probabilities in initial_prior.joint order'}))
            labels.append(dict(id=name+'/belief',posterior=list(posterior.probabilities)))
        for condition in ('history','oracle_belief'):
            payload=dict(public,legal_actions=[v.action.to_dict() for v in result.action_values])
            if condition=='oracle_belief':payload['current_belief']=posterior.to_dict()
            task_id=name+'/'+condition
            tasks.append(dict(id=task_id,kind='planning',input=payload,output_schema={'action_index':'integer index into legal_actions'}))
            labels.append(dict(id=task_id,q_values=[v.value for v in result.action_values],best_value=result.value))
    return tasks,labels


def score_answers(tasks,labels,answers):
    expected={t['id'] for t in tasks}
    if len({a['id'] for a in answers})!=len(answers):raise ValueError('Duplicate answer IDs.')
    if any(a['id'] not in expected for a in answers):raise ValueError('Unknown answer ID.')
    indexed={a['id']:a for a in answers};truth={x['id']:x for x in labels};results=[]
    _,prior,policies,cases=decision_cases();case_map={n:(s,b) for n,s,b in cases}
    for task in tasks:
        tid=task['id'];answer=indexed.get(tid);label=truth[tid]
        row={'id':tid,'status':'missing' if answer is None else 'ok'}
        if answer is not None:
            try:
                if task['kind']=='belief':
                    p=np.asarray(answer['probabilities'],dtype=float);q=np.asarray(label['posterior'])
                    if p.shape!=q.shape or not np.isfinite(p).all() or (p<0).any() or not np.isclose(p.sum(),1,atol=1e-8):raise ValueError('Invalid probability vector')
                    row['total_variation']=float(np.abs(p-q).sum()/2)
                    row['squared_posterior_error']=float(np.square(p-q).sum())
                    state,true_belief=case_map[tid.split('/')[0]]
                    logs=tuple(math.log(v) if v>0 else -math.inf for v in p)
                    estimate=replace(prior,log_probabilities=logs);planner=BayesPlanner(partner_policies=policies)
                    obs=build_player_observation(state,0)
                    chosen=planner.act(obs,estimate)
                    row['oracle_planner_with_model_belief_regret']=planner.solve(obs,true_belief).regret(chosen)
                else:
                    idx=answer['action_index']
                    if type(idx) is not int or not 0<=idx<len(label['q_values']):raise ValueError('Invalid action index')
                    row['regret']=max(0.,label['best_value']-label['q_values'][idx]);row['optimal']=row['regret']<=1e-10
            except (KeyError,TypeError,ValueError) as exc:
                row={'id':tid,'status':'invalid','error':str(exc)}
        results.append(row)
    paired=[]
    by_id={r['id']:r for r in results}
    for name,_,_ in cases:
        history=by_id[name+'/history']; oracle=by_id[name+'/oracle_belief']
        if history['status']==oracle['status']=='ok':
            paired.append({'case':name,'posterior_injection_regret_reduction':history['regret']-oracle['regret']})
    return dict(scope='Single constructed fixture; not a population estimate. Fixed-decision interventions, not independent internal modules.',
                requested=len(tasks),valid=sum(r['status']=='ok' for r in results),results=results,paired_interventions=paired)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--answers',type=Path)
    parser.add_argument('--base-url');parser.add_argument('--model')
    parser.add_argument('--max-tokens',type=int,default=2048)
    args=parser.parse_args(argv);args.output_dir.mkdir(parents=True,exist_ok=True)
    tasks,labels=export_tasks()
    def write(name,value):
        (args.output_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    write('tasks.json',{'system':RULES,'tasks':tasks});write('oracle_labels.json',labels)
    spec,prior,policies=fixture();comparison=root_comparison(spec,prior,policies)
    # With no downstream decision, posterior use cannot affect subsequent reward.
    terminal=replace(spec,round_robin=(0,));terminal_result=BayesPlanner(partner_policies=policies).solve(build_player_observation(GameState(terminal),0),prior)
    known=replace(prior,hypotheses=(prior.hypotheses[0],),log_probabilities=(0.0,))
    known_control=root_comparison(spec,known,policies)
    known_gap=max(abs(row['adaptive']-row['frozen']) for row in known_control['rows'])
    if known_gap>1e-10:raise AssertionError('Known-type negative control failed.')
    write('mechanism_certificate.json',dict(known_type_control_max_update_gain=known_gap, scope='Constructed two-turn proof of mechanism; explicit two-type prior; not default-generator statistics or LLM evidence.',
          comparison=comparison,terminal_control=terminal_result.to_dict(),
          limitations=['Outcome states differ; gain is relative to frozen-prior continuation, not a pure information causal effect.',
                       'Third player can provide alternative consent; this does not certify long-horizon multi-party dependence.',
                       'One fixture selected by search; held-out varied fixtures are required before a general capability claim.']))
    answers=None
    if args.answers:answers=json.loads(args.answers.read_text())
    elif args.base_url or args.model:
        if not(args.base_url and args.model):parser.error('--base-url and --model are required together')
        from methods.vllm_client import OpenAICompatibleNegotiationClient
        client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=args.max_tokens)
        answers=[]
        for task in tasks:
            raw=client.complete([{'role':'system','content':RULES},{'role':'user','content':json.dumps(task,ensure_ascii=False)}],response_format={'type':'json_object'})
            try:
                answer=json.loads(raw)
                if not isinstance(answer,dict):answer={}
            except (ValueError,TypeError):answer={}
            answers.append(dict(answer,id=task['id'],raw=raw))
            write('model_answers.json',answers)
        write('run_config.json',{'model':args.model,'base_url':args.base_url,'max_tokens':args.max_tokens,'temperature':0})
    if answers is not None:write('scores.json',score_answers(tasks,labels,answers))
    print(json.dumps({'tasks':len(tasks),'output_dir':str(args.output_dir),'root_action_regret':comparison['root_action_regret'],
                      'same_menu_update_gain':comparison['same_menu_update_gain'],'model_scored':answers is not None}))


if __name__=='__main__':main()
