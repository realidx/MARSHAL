"""Qualitative P-only inputs with interval-robust, native final-turn action labels.

Language has no universal numerical calibration. These deliberately broad audit
envelopes are stress-test assumptions, not a hidden exact probability target.
Terminal responses and final-turn proposals with stable partner responses are
certified here: their per-world payoffs are affine in belief. Multiple remaining
turns need a separate continuation-policy certificate.
"""
from copy import deepcopy
import json
import numpy as np
from scipy.optimize import linprog

from training.b_sft.shared_teacher import native, TOL
from training.b_sft.social_b_oracle import canonical
from training.b_sft.social_presentation import readable_action, LABELS
from training.b_sft.social_lm_eval import tool_for
from benac_p.endgame_diagnose import decode_action

VERSION = 'social-p-qualitative-final-turn-v1'
# Broad alternative calibrations; certification uses their union envelope.
ENVELOPES = {
    'possible': ((0.,1.),),
    'slightly_likely': ((.5,.65),(.5,.70)),
    'likely': ((.5,.8),(.5,.85)),
    'very_likely': ((.8,.97),(.75,.98)),
    'almost_certain': ((.95,1.),(.9,1.)),
    'unlikely': ((0.,.35),(0.,.4)),
    'impossible': ((0.,0.),),
    'certain': ((1.,1.),),
}
# Explicitly versioned, wider sensitivity assumptions for the new design audit.
# The v1 envelopes above remain available for replaying existing artifacts.
WIDE_ENVELOPES = {
    **ENVELOPES,
    'slightly_likely': ((.5, .75),),
    'likely': ((.5, .9),),
    'very_likely': ((.7, .99),),
    'almost_certain': ((.85, 1.),),
    'unlikely': ((0., .45),),
}
WORDS = {
    'possible': ('remains possible', 'cannot be ruled out'),
    'slightly_likely': ('seems somewhat more likely than not', 'is mildly favored, with substantial uncertainty'),
    'likely': ('is likely', 'appears more likely than not'),
    'very_likely': ('is very likely', 'is strongly supported, though alternatives remain possible'),
    'almost_certain': ('is almost certain, though an exception remains possible', 'is supported with very high confidence, without being guaranteed'),
    'unlikely': ('is unlikely, but remains possible', 'seems doubtful, though it cannot be ruled out'),
    'impossible': ('has been ruled out', 'is impossible under the supplied information'),
    'certain': ('is established', 'is known to hold'),
}


def event_mask(worlds, event):
    return np.array([all(w[c['player']][c['goal']] == c['value'] for c in event) for w in worlds],dtype=float)


def constraints(worlds, claims, *, envelopes=None):
    envelopes = ENVELOPES if envelopes is None else envelopes
    rows=[];rhs=[]
    for claim in claims:
        mask=event_mask(worlds,claim['event'])
        ranges=envelopes[claim['level']]
        low=min(x[0] for x in ranges);high=max(x[1] for x in ranges)
        rows.extend([mask,-mask]);rhs.extend([high,-low])
    return np.array(rows).reshape((-1,len(worlds))),np.array(rhs)


def robust_actions(payoffs, actor, worlds, claims, *, own_tolerance=0., social_tolerance=0., envelopes=None):
    """LP certificate across the full audit polytope, including social tie cases.

    payoffs[a,w,p]. Bound own regret for every feasible belief, and social regret
    on faces where own values tie. Zero tolerances recover strict optimality.
    Zero-mass boundary worlds are included conservatively; unlikely is never
    converted to impossible. No finite grid is passed off as a certificate.
    """
    values=np.asarray(payoffs,dtype=float)
    if values.ndim!=3 or values.shape[1]!=len(worlds) or not np.isfinite(values).all():
        raise ValueError('Finite action/world/player payoffs required')
    if any(not np.isfinite(v) or v < 0 for v in (own_tolerance, social_tolerance)):
        raise ValueError('Finite nonnegative regret tolerances required')
    a_ub,b_ub=constraints(worlds,claims,envelopes=envelopes)
    def minimize(c, tie=None):
        eq=[np.ones(len(worlds))];b=[1.]
        if tie is not None: eq.append(tie);b.append(0.)
        result=linprog(c,A_ub=a_ub if len(a_ub) else None,b_ub=b_ub if len(b_ub) else None,
                       A_eq=np.array(eq),b_eq=np.array(b),bounds=(0,None),method='highs')
        if result.status not in (0,2):raise ValueError('LP failed: '+result.message)
        return result
    if minimize(np.zeros(len(worlds))).status==2:
        return dict(status='inconsistent_information',acceptable=[],checks=[])
    accepted=[];checks=[]
    for action in range(len(values)):
        valid=True;comparisons=[]
        for other in range(len(values)):
            if action==other:continue
            own=values[action,:,actor]-values[other,:,actor]
            result=minimize(own)
            evidence=dict(against=other,worst_own_margin=float(result.fun),belief=result.x.tolist())
            if result.fun < -own_tolerance-TOL:valid=False
            else:
                social=values[action].sum(axis=1)-values[other].sum(axis=1)-own
                tie=minimize(social,own)
                evidence['own_tie_feasible']=tie.status==0
                if tie.status==0:
                    evidence['worst_social_margin_on_own_tie']=float(tie.fun)
                    if tie.fun < -social_tolerance-TOL:valid=False
            comparisons.append(evidence)
        checks.append(dict(action=action,stable=valid,comparisons=comparisons))
        if valid:accepted.append(action)
    return dict(status='certified' if accepted else 'ambiguous_information',acceptable=accepted,checks=checks,
                own_tolerance=own_tolerance,social_tolerance=social_tolerance,
                acceptance='Bound own regret against every alternative for every feasible belief; separately bound social loss on exact own-value tie faces',
                scope='All distributions in the documented audit envelopes; not universal semantics of English uncertainty words.')


def phrase(event):
    return ' and '.join(f"Player {c['player']} {dict(want='wants',neutral='is neutral about',avoid='wants to avoid')[LABELS[c['value']]]} goal_{c['goal']}" for c in event)


def proposal_payoffs(rules,node,worlds,claims, *, envelopes=None):
    """Certify a final-turn responder policy over the whole public-belief envelope.

    Reject policy changes and extra residual ties inside the envelope; otherwise
    each root action's payoff is affine in belief and the same LP applies to P.
    """
    result=[];audits=[]
    for action in rules.actions(node):
        child=rules._apply(node,action)
        if child.state.is_terminal:
            result.append(np.array(worlds)@child.state.goal_satisfaction());audits.append([]);continue
        if child.pending is None:raise ValueError('Nonterminal actions need continuation certification')
        player=rules.actor(child);responses=rules.actions(child);payoffs=[]
        for response in responses:
            end=rules._apply(child,response)
            if not end.state.is_terminal:raise ValueError('Nonterminal actions need continuation certification')
            payoffs.append(np.array(worlds)@end.state.goal_satisfaction())
        payoffs=np.array(payoffs);expected=np.zeros_like(payoffs[0]);policies=[]
        for own in dict.fromkeys(w[player] for w in worlds):
            mask=np.array([w[player]==own for w in worlds],dtype=float)
            masked=payoffs*mask[None,:,None]
            # Partner behavior stays strictly optimal regardless of learner tolerance.
            cert=robust_actions(masked,player,worlds,claims,envelopes=envelopes)
            accepted=cert['acceptable']
            if not accepted:raise ValueError('Ambiguous partner policy across qualitative envelope')
            base=accepted[0];a_ub,b_ub=constraints(worlds,claims,envelopes=envelopes)
            for other in set(range(len(responses)))-set(accepted):
                own_diff=masked[base,:,player]-masked[other,:,player]
                social_diff=masked[base].sum(axis=1)-masked[other].sum(axis=1)-own_diff
                tie=linprog(-mask,A_ub=a_ub if len(a_ub) else None,b_ub=b_ub if len(b_ub) else None,
                            A_eq=np.array([np.ones(len(worlds)),own_diff,social_diff]),b_eq=[1,0,0],
                            bounds=(0,None),method='highs')
                if tie.status not in (0,2):raise ValueError('Partner tie LP failed')
                if tie.status==0 and tie.fun < -TOL:
                    raise ValueError('Residual partner tie set changes inside qualitative envelope')
            indices=np.flatnonzero(mask)
            expected[indices]=payoffs[accepted][:,indices,:].mean(axis=0)
            policies.append(dict(player=player,own=own,actions=[responses[i].to_dict() for i in accepted]))
        result.append(expected);audits.append(policies)
    return result,audits


def terminal_task(raw, prefix, claims, *, supported_worlds=None, variant=0, allow_proposal=False,
                  own_tolerance=0., social_tolerance=0., envelopes=None):
    """Use supplied qualitative information, never visible history to redo B."""
    rules,all_worlds,_=native(raw);node=rules.initial()
    for action in prefix:node=rules._apply(node,decode_action(action))
    if rules.actor(node)!=raw['ego'] or node.pending is None and not allow_proposal:
        raise ValueError('This certifier requires the learner to respond to a pending offer')
    worlds=tuple(tuple(tuple(row) for row in w) for w in (all_worlds if supported_worlds is None else supported_worlds))
    if not worlds or len(set(worlds))!=len(worlds) or not set(worlds)<=set(all_worlds):
        raise ValueError('Supported worlds must be distinct native catalogue worlds')
    worlds=tuple(w for w in worlds if w[raw['ego']]==tuple(raw['own_preferences']))
    for claim in claims:
        if claim['level'] in ('impossible','certain'):
            mask=event_mask(worlds,claim['event'])
            worlds=tuple(w for w,m in zip(worlds,mask) if bool(m)==(claim['level']=='certain'))
    if not worlds:raise ValueError('No world compatible with learner private information')
    actions=rules.actions(node);payoffs=[];partner_policies=[]
    if node.pending is None:
        if len(raw['type_catalogues'][str(raw['ego'])])!=1:
            raise ValueError('Proposal certificate currently requires publicly known learner preferences')
        payoffs,partner_policies=proposal_payoffs(rules,node,worlds,claims,envelopes=envelopes)
    else:
        for action in actions:
            child=rules._apply(node,action)
            if not child.state.is_terminal:
                raise ValueError('Nonterminal actions need continuation certification; no terminal surrogate label')
            payoffs.append(np.array(worlds)@child.state.goal_satisfaction())
    certificate=robust_actions(payoffs,raw['ego'],worlds,claims,own_tolerance=own_tolerance,
                               social_tolerance=social_tolerance,envelopes=envelopes)
    variable=[(p,g) for p in range(raw['game']['n_players']) for g in range(len(raw['own_preferences']))
              if len({w[p][g] for w in worlds})>1]
    # Explicit disjunction preserves correlations; no inferred independence.
    situations=[phrase([dict(player=p,goal=g,value=w[p][g]) for p,g in variable]) for w in worlds] if variable else []
    known=[dict(player=p,goal=g,preference=LABELS[worlds[0][p][g]])
           for p in range(raw['game']['n_players']) for g in range(len(raw['own_preferences'])) if (p,g) not in variable]
    statements=['Current assessment: '+phrase(c['event'])+' — '+WORDS[c['level']][variant%len(WORDS[c['level']])]+'.' for c in claims]
    if variant%2:situations.reverse();statements.reverse()
    proposer=node.state.current_proposer()
    shown=[readable_action(a.to_dict(),proposer) for a in actions]
    visible=dict(player=raw['ego'],game=rules.spec.to_dict(),
        own_preferences=raw['own_preferences'],known_preferences=known,
        current_commitments=node.state.snapshot_commitments(),
        decision=dict(phase='response' if node.pending else 'proposal',proposer=proposer,responder=raw['ego'] if node.pending else None,last_proposer_turn=True),
        pending_offer=readable_action(node.pending.to_dict(),proposer) if node.pending else None,legal_actions=shown,
        supplied_belief=dict(perspective=('These current judgments are public; each player additionally knows their own preferences.' if node.pending is None else
                                          f"Player {raw['ego']}'s current information; do not assume others have this private information."),
            possible_situations=situations or ['All preferences are known.'],
            joint_constraint='These are the complete possible situations. Do not combine parts from different situations.',
            assessments=statements),
        task='Use the supplied current judgments to choose an action. Maximize your expected goal utility; among own-value ties maximize the expected total goal utility of other players. Any action tied on both criteria is acceptable. Respond with one native SUBMIT_ACTION call.')
    system=('Choose from legal_actions using the supplied current information. Uncertainty descriptions are qualitative; do not invent exact percentages. '
            'A goal contributes +1 for want, 0 for neutral, -1 for avoid when all required actions are committed, otherwise 0. '
            'Accepted offers bind their commitments immediately. There is one proposer turn left; PASS or resolving an offer ends the game. '
            'A partner first maximizes their own expected goal utility, then the total utility of the other players among own-value ties, and responds uniformly among remaining ties. '
            'Briefly explain your decision, then call SUBMIT_ACTION with the complete selected legal action object.')
    req=dict(messages=[dict(role='system',content=system),dict(role='user',content=json.dumps(visible))],
             tools=[tool_for('P',visible)],tool_choice='auto',parallel_tool_calls=False,max_tokens=1024)
    if own_tolerance or social_tolerance:
        visible['task'] += ' Closely competitive actions may also be accepted; still prefer higher own utility and, on own-value ties, higher total utility for others.'
        req['messages'][1]['content'] = json.dumps(visible)
    return dict(version=VERSION if envelopes is None and not (own_tolerance or social_tolerance) else 'social-p-qualitative-near-optimal-audit-v2',input=visible,request=req,
        teacher=dict(certificate=certificate,audit_envelopes=ENVELOPES if envelopes is None else envelopes,claims=claims,worlds=worlds,payoffs=np.array(payoffs).tolist(),partner_policies=partner_policies,
                     acceptable_actions=[shown[i] for i in certificate['acceptable']]))


def score(task, completion):
    if completion.get('status') in ('infrastructure_failure','request_error'):
        return dict(status='infrastructure_failure',reward=None)
    if completion.get('finish_reason')=='length':return dict(status='truncated',reward=-1)
    try:
        calls=completion['raw_message']['tool_calls']
        if len(calls)!=1 or calls[0]['function']['name']!='SUBMIT_ACTION':raise ValueError('Expected one native action call')
        action=json.loads(calls[0]['function']['arguments'])
        if canonical(action) not in {canonical(a) for a in task['input']['legal_actions']}:raise ValueError('Illegal action')
    except (KeyError,TypeError,ValueError):return dict(status='format_failure',reward=-1)
    if task['teacher']['certificate']['status']!='certified':
        return dict(status=task['teacher']['certificate']['status'],reward=None)
    return dict(status='ok',reward=int(canonical(action) in {canonical(a) for a in task['teacher']['acceptable_actions']}))


def confidence_fixture():
    """Native final response: own values tie; others gain 2*v-1 on ACCEPT.

    Two hidden slots of one partner are correlated. The last, unsatisfied goal
    keeps a positive preference in every catalogue profile. This is a supplied
    belief P unit fixture, not a claim that an autonomous history generated it.
    """
    goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=0,action_id=0),dict(player_id=2,action_id=0)]) for g in range(4)]
    goals.append(dict(goal_id=4,binary=True,required_actions=[dict(player_id=1,action_id=0),dict(player_id=2,action_id=1)]))
    raw=dict(id='qualitative-confidence-response',ego=0,history=[],own_preferences=[1,1,-1,-1,1],
        type_catalogues={'0':[[1,1,-1,-1,1]],'1':[[v,v,0,0,1] for v in (1,-1)],'2':[[0,0,-1,0,1]]},
        game=dict(n_players=3,n_actions_per_player=[1,1,2],goals=goals,round_robin=[0,1,2],max_changes=1,menu_enabled=False))
    prefix=[dict(action='PASS'),dict(action='PASS'),dict(action='OFFER',partner_id=0,proposer_action=[1,0],partner_action=[1])]
    return raw,prefix


def proposal_fixture():
    """Final native proposal: a risky four-goal agreement vs a safe three-goal one."""
    goals=[]
    for g in range(8):
        req=[(0,0),(1,0)] if g<4 else [(0,1),(2,0)] if g<7 else [(1,1),(2,1)]
        goals.append(dict(goal_id=g,binary=True,required_actions=[dict(player_id=p,action_id=a) for p,a in req]))
    raw=dict(id='qualitative-risky-proposal',ego=0,history=[],own_preferences=[1]*8,
        type_catalogues={'0':[[1]*8],'1':[[v,0,0,0,0,0,0,1] for v in (1,-1)],'2':[[0,0,0,0,1,0,0,1]]},
        game=dict(n_players=3,n_actions_per_player=[2]*3,goals=goals,round_robin=[1,2,0],max_changes=1,menu_enabled=False))
    return raw,[dict(action='PASS'),dict(action='PASS')]


def build_examples(out):
    from pathlib import Path
    from collections import Counter
    out=Path(out)
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True)
    tasks=[]
    for fixture in (confidence_fixture,proposal_fixture):
        raw,prefix=fixture()
        for level in ('possible','slightly_likely','likely','very_likely','almost_certain','unlikely','impossible','certain'):
            claims=[dict(event=[dict(player=1,goal=0,value=1)],level=level)]
            for variant in (0,1):
                task=terminal_task(raw,prefix,claims,variant=variant,allow_proposal=fixture==proposal_fixture)
                task['id']=f'{raw["id"]}-{level}-{variant}';tasks.append(task)
    (out/'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    (out/'requests.jsonl').write_text(''.join(json.dumps(dict(id=t['id'],request=t['request']))+'\n' for t in tasks if t['teacher']['certificate']['status']=='certified'))
    summary=dict(version=VERSION,training_ready=False,development_only=True,actual_LM=False,
        tasks=len(tasks),statuses=dict(Counter(t['teacher']['certificate']['status'] for t in tasks)),
        levels={t['id']:dict(status=t['teacher']['certificate']['status'],actions=t['teacher']['acceptable_actions']) for t in tasks},
        limitation='Two final-turn fixtures and paraphrases, covering own-risk decisions and social ties. No multi-turn continuation or transfer validation. Ambiguous tasks receive no exact action label.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True)
    build_examples(p.parse_args().out)
