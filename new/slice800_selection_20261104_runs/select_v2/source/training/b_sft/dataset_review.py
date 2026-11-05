"""Evidence, downstream-use and own-goal audits for native review fixtures.

Exact computations are conditional on the declared reference partner. A
next-decision evidence ablation is not an unrestricted value-of-information claim.
"""
from collections import defaultdict
from copy import deepcopy
from itertools import permutations, product
import json
from pathlib import Path
import time

from training.b_sft.catalogues import validate_catalogues
from training.b_sft.social_rollout import build,queries_for
from training.b_sft.favored_belief import marginal
from training.b_sft.structure_audit import digest,TOL
from training.b_sft.evidence_switch import decision_key
from benac_p.endgame import Node, fingerprint
from benac_p.endgame_diagnose import decode_action

VERSION='evidence-use-review-v1'


def family_id(raw):
    """Conservative split family, invariant to player/action/goal renaming.

    Round order anchors player canonical IDs. Native enumeration tie-breaking
    may change under renaming, so this is a leakage guard, not behavioral identity.
    """
    g=raw['game'];n=g['n_players'];order=g['round_robin'][:n]
    if len(set(order))!=n:raise ValueError('Expected a complete first round')
    counts=g['n_actions_per_player']
    if max(counts)>3:raise ValueError('Canonicalization budget supports <=3 actions per player')
    mapping={p:i for i,p in enumerate(order)};best=None
    for choices in product(*(permutations(range(k)) for k in counts)):
        goals=sorted((bool(goal.get('binary',True)),tuple(sorted((mapping[a['player_id']],choices[a['player_id']][a['action_id']]) for a in goal['required_actions']))) for goal in g['goals'])
        forbidden=g.get('forbidden_actions')
        flags=[]
        for p in order:
            row=[0]*counts[p]
            if forbidden is not None:
                for a in range(counts[p]):row[choices[p][a]]=int(forbidden[p][a])
            flags.append(row)
        value=json.dumps(dict(actions=[counts[p] for p in order],goals=goals,rounds=[mapping[p] for p in g['round_robin']],
                              max_changes=g['max_changes'],menu=g.get('menu_enabled',False),forbidden=flags),sort_keys=True)
        if best is None or value<best:best=value
    return 'family-'+digest(best)[:24]


def belief(node,types,ego):
    return [dict(**q,**marginal(node.worlds,q['player'],q['goal'])['answer']) for q in queries_for(types,ego)]


def timeline(raw,budget=3000):
    base=dict(raw,history=[]);search,node,types,partner=build(base,budget);events=[]
    for i,action in enumerate(raw.get('history',[])):
        actor=search.actor(node);a=decode_action(action);before=belief(node,types,search.ego);old=len(node.worlds)
        sensitivity={}
        if actor!=search.ego:
            chosen={w:search._partner_action(node,w) for w in node.worlds}
            worlds=tuple(w for w in node.worlds if chosen[w]==a)
            if not worlds:raise ValueError('Public history impossible under declared prior/kernel')
            public=fingerprint(node.state.public_state());pending=fingerprint(None if node.pending is None else node.pending.to_dict())
            relaxed=tuple(w for w in node.worlds if a.to_dict() in partner.labels[(actor,w[actor],public,pending)]['optimal_actions'])
            alternative=belief(Node(node.state,relaxed,node.pending),types,search.ego)
            exact=belief(Node(node.state,worlds,node.pending),types,search.ego)
            sensitivity=dict(excluded_only_by_tie_worlds=len(relaxed)-len(worlds),
                excluded_by_strict_value_worlds=old-len(relaxed),
                locally_tie_relaxed_B=alternative,
                local_tie_sensitive_queries=[dict(player=x['player'],goal=x['goal'],
                    set_sensitive=x['possible_preferences']!=y['possible_preferences'],favored_sensitive=x['favored']!=y['favored']) for x,y in zip(exact,alternative) if x!=y],
                scope='Only this observed action may use another optimal tie; the earlier posterior and future reference stay fixed. Not a new partner-policy posterior.')
            node=Node(node.state,worlds,node.pending)
        node=search._apply(node,a)
        events.append(dict(index=i,actor=actor,action=action,ego_intervention=actor==search.ego,
                           before_B=before,after_B=belief(node,types,search.ego),worlds_before=old,worlds_after=len(node.worlds),tie_sensitivity=sensitivity))
    return events


def conservative_b_masks(events,queries):
    """Do not use a component for local reward if its history had a tie-dependent update.

    This conservative flag never claims the current answer is wrong, and does
    not re-enable a component after later evidence. Labels remain exact for the
    declared deterministic teacher. It is not a posterior over unknown policies.
    """
    result=[]
    for q in queries:
        relevant=[x for e in events for x in e['tie_sensitivity'].get('local_tie_sensitive_queries',[])
                  if (x['player'],x['goal'])==(q['player'],q['goal'])]
        result.append(dict(**q,set_mask=not any(x['set_sensitive'] for x in relevant),
                           favored_mask=not any(x['favored_sensitive'] for x in relevant)))
    return result


def evidence_use(branches):
    """Allow adaptation to physical state, forbid using other new history at next choice.

    Input Q rows include fully adaptive continuation AFTER that choice. No
    partner policy, physical branch or hidden world is replaced by a fake one.
    """
    groups=defaultdict(list);terminal=0.
    for b in branches:
        if b['terminal']:terminal+=b['weight']*b['utility']
        else:groups[b['physical_key']].append(b)
    adaptive=terminal;blind=terminal;details=[]
    for key,rows in groups.items():
        acts=rows[0]['actions']
        if any(r['actions']!=acts for r in rows):raise ValueError('Aligned physical states have different legal actions')
        full=sum(r['weight']*max(r['q']) for r in rows)
        tied=[sum(r['weight']*r['q'][i] for r in rows) for i in range(len(acts))]
        restricted=max(tied);adaptive+=full;blind+=restricted
        details.append(dict(physical_key=key,branches=len(rows),adaptive=full,history_blind=restricted,gain=full-restricted))
    if adaptive+TOL<blind:raise ValueError('Restriction unexpectedly increases value')
    return dict(adaptive_value=adaptive,next_decision_history_blind_value=blind,gain=max(0.,adaptive-blind),groups=details,
                scope='Only the next ego choice ignores new history beyond its physical state; later choices retain full evidence.')


def audit(raw,budget=3000,check_own=0):
    started=time.monotonic();validate_catalogues(raw)
    search,node,types,partner=build(raw,budget)
    result=dict(id=raw['id'],family_id=family_id(raw),fixture=raw,status='ok',
                before_B=belief(node,types,search.ego),teacher_specification=partner.specification(),timeline=timeline(raw,budget),
                arms=[],own_goal_contrasts=[],own_goal_attempts=[])
    q=search.q_values(node);best=max(v for _,v in q);worst=min(v for _,v in q)
    result.update(root_Q=[dict(action=a.to_dict(),q=v,regret=best-v) for a,v in q],root_q_range=best-worst,
                  root_action_invariant=best-worst<=TOL,pass_optimal=any(a.to_dict().get('action')=='PASS' and best-v<=TOL for a,v in q))
    for a,v in q:
        branches=[]
        for b in search.step(node,a):
            history=raw.get('history',[])+[a.to_dict()]+[e['action'] for e in b.evidence]
            # Fresh builder: prove branch history itself implies the saved posterior.
            other=deepcopy(raw);other['history']=history
            replay,rnode,rtypes,_=build(other,budget)
            if set(rnode.worlds)!=set(b.node.worlds) or decision_key(rnode)!=decision_key(b.node):raise ValueError('Branch replay mismatch')
            row=dict(weight=b.weight,history=history,evidence=b.evidence,after_B=belief(b.node,types,search.ego),
                     terminal=b.node.state.is_terminal,physical_key=decision_key(b.node))
            if row['terminal']:row['utility']=search.utility(b.node)
            else:
                child_q=search.q_values(b.node);cbest=max(cv for _,cv in child_q)
                row.update(actions=[ca.to_dict() for ca,_ in child_q],q=[cv for _,cv in child_q],
                           optimal_actions=[ca.to_dict() for ca,cv in child_q if cbest-cv<=TOL],
                           action_value_range=cbest-min(cv for _,cv in child_q))
            branches.append(row)
        measure=evidence_use(branches)
        if abs(measure['adaptive_value']-v)>1e-8:raise ValueError('Bellman branch values disagree with root Q')
        result['arms'].append(dict(action=a.to_dict(),q=v,regret=best-v,branches=branches,information_use=measure,
            root_optimality_depends_on_next_evidence=(measure['gain']>TOL and best-v<=TOL and
                measure['next_decision_history_blind_value']<max((vv for aa,vv in q if aa!=a),default=v)-TOL)))
    # Same history and posterior over partners, changed own objective. Past
    # reference responses must still be possible under the new public own row.
    other_worlds=lambda n:{tuple(row for p,row in enumerate(w) if p!=search.ego) for w in n.worlds}
    attempts=0
    for goal,old in enumerate(raw['own_preferences']):
        for value in (-1,0,1):
            if value==old or attempts>=check_own:continue
            attempts+=1;cf=deepcopy(raw);cf['own_preferences'][goal]=value
            cf['type_catalogues'][str(search.ego)]=[cf['own_preferences'][:]]
            cf['id']=raw['id']+f'-own-g{goal}-{value}'
            try:
                validate_catalogues(cf);cs,cn,_,_=build(cf,budget)
                if decision_key(cn)!=decision_key(node) or other_worlds(cn)!=other_worlds(node):raise ValueError('Changed physical state or partner posterior')
                cq=cs.q_values(cn)
                if [a.to_dict() for a,_ in cq]!=[a.to_dict() for a,_ in q]:raise ValueError('Different legal actions')
                opt={i for i,(_,v) in enumerate(q) if best-v<=TOL};cmax=max(v for _,v in cq)
                copt={i for i,(_,v) in enumerate(cq) if cmax-v<=TOL}
                if not opt&copt:
                    result['own_goal_contrasts'].append(dict(fixture=cf,changed_goal=goal,old=old,new=value,
                        original_optimal_actions=[q[i][0].to_dict() for i in sorted(opt)],
                        counterfactual_Q=[dict(action=a.to_dict(),q=v) for a,v in cq],
                        counterfactual_optimal_actions=[cq[i][0].to_dict() for i in sorted(copt)],
                        scope='Same observable history and partner posterior; own row also publicly known to reference partners. Not a covert preference intervention.'))
                result['own_goal_attempts'].append(dict(goal=goal,value=value,status='verified',disjoint=not bool(opt&copt)))
            except (RuntimeError,ValueError) as exc:result['own_goal_attempts'].append(dict(goal=goal,value=value,status='unavailable',reason=str(exc)))
    live=[b for a in result['arms'] for b in a['branches'] if not b['terminal']]
    result.update(any_later_action_matters=any(b['action_value_range']>TOL for b in live),
                  max_next_evidence_gain=max(a['information_use']['gain'] for a in result['arms']),
                  evidence_pivotal_for_root=any(a['root_optimality_depends_on_next_evidence'] for a in result['arms']),
                  seconds=round(time.monotonic()-started,3))
    result['recommended_role']='P_action_invariant_control' if result['root_action_invariant'] else 'planning_cost_control_or_candidate'
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-nodes',type=int,default=3000);p.add_argument('--own-attempts',type=int,default=0);args=p.parse_args()
    if args.output.exists():p.error('Use a new output file')
    raw=json.loads(args.fixture.read_text());result=audit(raw,args.max_nodes,args.own_attempts)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('id','root_action_invariant','any_later_action_matters','max_next_evidence_gain','evidence_pivotal_for_root','seconds')}))
