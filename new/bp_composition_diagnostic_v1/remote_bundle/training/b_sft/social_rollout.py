"""CPU reference rollout: fixed all-hidden B queries, native P, actual terminal U.

Agent callbacks see only public payloads. This is not a PPO trainer or an LM
client. Reference partner simulation may still require expensive search.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import random
import numpy as np

from training.b_sft.favored_belief import marginal, score_belief
from training.b_sft.catalogues import validate_catalogues
from benac_p.schema import GameSpec, Goal, ActionRef
from benac_p.endgame import Endgame
from benac_p.endgame_partner import RationalPartner
from benac_p.endgame_diagnose import decode_action


def queries_for(types,ego):
    """Fixed public catalogue dimensions; independent of evidence, Q and true world."""
    return [dict(player=p,goal=g) for p in sorted(types) if p!=ego
            for g in range(len(types[p][0])) if len({row[g] for row in types[p]})>1]


def build(raw,max_nodes):
    if raw.get('teacher_model',{}).get('version','').startswith('shared-information-set-'):
        raise ValueError('Shared teacher fixture must use SharedGame; do not silently relabel with the legacy RationalPartner')
    if 'initially_possible_preferences' in raw:raise ValueError('Injected posterior not allowed')
    validate_catalogues(raw)
    public=raw['game']
    if any(not g.get('binary',True) for g in public['goals']):
        raise ValueError('Reference partner does not yet support linear goals faithfully')
    goals=tuple(Goal(g['goal_id'],tuple(ActionRef(**a) for a in g['required_actions'])) for g in public['goals'])
    types={int(p):tuple(tuple(row) for row in rows) for p,rows in raw['type_catalogues'].items()}
    ego=raw['ego'];own=tuple(raw['own_preferences'])
    if set(types)!=set(range(public['n_players'])) or types.get(ego)!=(own,):
        raise ValueError('Provide every player; ego catalogue must contain only its known own row')
    spec=GameSpec(public['n_players'],tuple(public['n_actions_per_player']),goals,
                  np.zeros((public['n_players'],len(goals)),dtype=np.int8),tuple(public['round_robin']),
                  public['max_changes'],0,forbidden_actions=None if public.get('forbidden_actions') is None else np.array(public['forbidden_actions']),
                  menu_enabled=public.get('menu_enabled',False))
    partner=RationalPartner(spec,types,ego,max_nodes)
    search=Endgame(spec,ego,own,{p:rs for p,rs in types.items() if p!=ego},partner,max_nodes=max_nodes)
    node=search.replay([decode_action(a) for a in raw.get('history',[])])
    return search,node,types,partner


def belief_payload(search,node,types,partner,history,queries,ratio):
    return dict(ego=search.ego,own_preferences=list(search.own),public_state=node.state.public_state(),
                rules=dict(menu_enabled=search.spec.menu_enabled,
                    goals='Binary ALL_OF: a goal is satisfied only when every listed commitment is 1.',
                    utility='Terminal utility is the sum of own preference (-1 avoid, 0 neutral, +1 want) times goal satisfaction. No interim reward.',
                    commitments='Offer vectors are complete target commitments, not deltas. Existing 1s cannot be unset; each party may add at most max_changes non-forbidden commitments; at least one addition is required.',
                    turns='PASS, rejected offers and resolved accepted offers each consume one proposal turn. Responses consume no additional proposal turn. The game ends after the listed round_robin schedule.',
                    menus='If enabled, a menu has two distinct ordinary offers to the same partner. REJECT changes nothing; CHOOSE_1/CHOOSE_2 executes only that option.'),
                pending_offer=None if node.pending is None else node.pending.to_dict(),
                history=deepcopy(history),public_type_catalogues=deepcopy(types),
                partner_model=partner.specification(),queries=deepcopy(queries),
                instruction='For every listed query, return player, goal, possible_preferences, favored. Brief text is allowed; no probability or count outputs.',
                favored_rule=dict(robustness_ratio=ratio,rule='Uniform joint prior filtered by partner evidence; require a unique leader robust to remaining-world weight multipliers in [1, ratio]. Otherwise undetermined.'))


def valid_b(response,queries):
    if not isinstance(response,dict) or not isinstance(response.get('text'),str):return False
    answers=response.get('answer')
    if not isinstance(answers,list) or len(answers)!=len(queries):return False
    for a,q in zip(answers,queries):
        if not isinstance(a,dict) or set(a)!={'player','goal','possible_preferences','favored'}:return False
        if {k:a[k] for k in ('player','goal')}!=q:return False
        if not score_belief({k:a[k] for k in ('possible_preferences','favored')},None)['format_valid']:return False
    return True


def run_episode(raw,agent,seed=0,max_nodes=3000,max_calls=64,world=None,robustness_ratio=1.25):
    """agent(phase, payload) -> {'text': str, 'answer': list[B] or native P dict}.

    Incomplete/invalid episodes have no terminal return. B gold never goes into
    the P payload. The optional world is solely an environment/test input.
    """
    search,node,types,partner=build(raw,max_nodes)
    if node.state.is_terminal:raise ValueError('Episode must start before termination')
    fixed_queries=queries_for(types,search.ego)
    if not fixed_queries:raise ValueError('B rollout requires at least one hidden dimension')
    actual=random.Random(seed).choice(node.worlds) if world is None else world
    if actual not in node.worlds:raise ValueError('Realized world incompatible with visible prefix')
    history=deepcopy(raw.get('history',[]));calls=[];events=[];teachers=[]
    result=dict(version='social-rollout-reference-v1',id=raw['id'],seed=seed,queries=fixed_queries,
                calls=calls,events=events,teacher_sidecar=teachers,status='incomplete',terminal_utility=None,
                normalized_return=None,training_ready=False)
    def advance(branches):
        nonlocal node
        matches=[b for b in branches if actual in b.node.worlds]
        if len(matches)!=1:raise ValueError('Actual world must select exactly one environment branch')
        b=matches[0];node=b.node
        for e in b.evidence:
            events.append(deepcopy(e));history.append(deepcopy(e['action']))
    try:
        if search.actor(node)!=search.ego:advance(search.advance(node))
        while not node.state.is_terminal:
            if len(calls)+2>max_calls:
                result['status']='call_budget';return result
            payload=belief_payload(search,node,types,partner,history,fixed_queries,robustness_ratio)
            b=agent('B',deepcopy(payload))
            calls.append(dict(phase='B',input=payload,output=deepcopy(b),actor_output=True))
            if not valid_b(b,fixed_queries):
                result['status']='invalid_B';return result
            # Teacher-only assessment; does not replace any part of model B.
            marks=[]
            for answer,q in zip(b['answer'],fixed_queries):
                gold=marginal(node.worlds,q['player'],q['goal'],robustness_ratio)
                pred={k:answer[k] for k in ('possible_preferences','favored')}
                marks.append(dict(**q,gold=gold,assessment=score_belief(pred,gold['answer'])))
            teachers.append(dict(call_index=len(calls)-1,items=marks,
                                 mean_score=sum(m['assessment']['score'] for m in marks)/len(marks)))
            p_payload=deepcopy(payload)
            p_payload.update(instruction='Use your preceding judgment and visible history; submit a native legal action, not an action index.',
                             model_belief=deepcopy(b),legal_actions=[a.to_dict() for a in search.actions(node)])
            p=agent('P',deepcopy(p_payload))
            calls.append(dict(phase='P',input=p_payload,output=deepcopy(p),actor_output=True))
            try:
                if not isinstance(p,dict) or not isinstance(p.get('text'),str) or not isinstance(p.get('answer'),dict):raise ValueError('Malformed response')
                # Exact semantic dictionary membership also rejects extra keys.
                if p['answer'] not in p_payload['legal_actions']:raise ValueError('Illegal native action')
                action=decode_action(p['answer'])
            except (ValueError,KeyError,TypeError):
                result['status']='invalid_P';return result
            events.append(dict(turn_index=node.state.turn_index,player_id=search.ego,action=action.to_dict()))
            history.append(action.to_dict());advance(search.step(node,action))
        utility=search.utility(node);scale=max(1,sum(abs(v) for v in search.own))
        result.update(status='terminal',terminal_utility=utility,utility_scale=scale,normalized_return=utility/scale,
                      final_commitments=node.state.snapshot_commitments(),history=history,
                      note='Actual terminal utility, not reference optimal Q. No value/log-prob/PPO update computed.')
    except (RuntimeError,ValueError) as exc:
        result.update(status='environment_error',error=f'{type(exc).__name__}: {exc}')
    return result


def scripted_agent(phase,payload):
    """Conservative protocol probe; no solver access and no competence claim."""
    if phase=='B':
        return dict(text='Retain the public prior candidates; this is a protocol probe.',answer=[dict(**q,
            possible_preferences=[label for v,label in [(1,'want'),(0,'neutral'),(-1,'avoid')]
                                  if any(row[q['goal']]==v for row in payload['public_type_catalogues'][q['player']])],
            favored='undetermined') for q in payload['queries']])
    actions=payload['legal_actions']
    action=next((a for a in actions if a.get('action')=='PASS' or a.get('response')=='REJECT'),actions[0])
    return dict(text='Use the fixed protocol-probe action.',answer=action)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=0);p.add_argument('--max-nodes',type=int,default=3000)
    args=p.parse_args(argv)
    if args.output.exists():p.error('Use a new output file')
    raw=json.loads(args.fixture.read_text());raw=raw.get('fixture',raw)
    result=run_episode(raw,scripted_agent,args.seed,args.max_nodes)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['status','queries','terminal_utility','normalized_return']}))
    if result['status']!='terminal':raise SystemExit(2)


if __name__=='__main__':main()
