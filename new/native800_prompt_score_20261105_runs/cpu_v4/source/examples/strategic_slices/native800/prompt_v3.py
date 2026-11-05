"""September system/tools, complete current state, native800 game protocol."""
from copy import copy
import math
from training.b_sft.review_prompt import SYSTEM
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.named_prompt import (
    visible, game_rules, goal_requirements, preference_information,
    public_history as previous_public_history, check_independent_preferences)
from training.social_mixed.frozen.bp_display import action_tools

VERSION='native800-readable-prompt-v3'


def actor_view(rules,node,world):
    """Deliver cumulative DIRECT answers for this actor, never inferred facts.

    Saved public trees use_apply rather than realized step. Reconstructing
    direct answers from their public query slots is the environment's job.
    Work on a clone so no global tree or another player's state is changed.
    """
    actor=rules.actor(node)
    if actor is None:raise ValueError('Terminal states do not request an action')
    world=tuple(tuple(row)for row in world)
    if world not in rules.worlds:raise ValueError('World outside this game')
    state=node.state.clone()
    answers=tuple((p,g,world[p][g])for p,g in observed_slots(node,actor))
    state.private_results=tuple(answers if p==actor else()for p in range(rules.spec.n_players))
    view=copy(node);view.state=state
    return view


def prior_text(rules):
    check_independent_preferences(rules)
    prior=rules.raw.get('background_prior',{}).get('weights')
    if (not isinstance(prior,dict)or set(prior)!={'want','neutral','avoid'}
            or any(not math.isfinite(v)or v<=0 for v in prior.values())
            or len(set(prior.values()))!=1):
        raise ValueError('This certified native800 version requires recorded independent uniform prior')
    return ['BACKGROUND PREFERENCE DISTRIBUTION',
        'Initially, every non-public player-goal preference is drawn independently: want, neutral '
        'and avoid each have probability 1/3. Everyone knows this starting distribution. '
        'Preferences stay fixed; use your private information and the public history to update your beliefs.']


def request(rules,node,world,seed,temperature=1.):
    if not hasattr(rules,'query_limit')or not hasattr(rules,'offer_limit'):
        raise ValueError('Native800 prompt requires explicit investigation and offer budgets')
    view=actor_view(rules,node,world)
    obs,v,names=visible(rules,view,world[rules.actor(view)])
    game=obs['game'];query_budget=rules.query_limit;offer_budget=rules.offer_limit
    lines=game_rules(game)
    lines[3]+=(f' Each player may make at most {offer_budget} OFFER action{"" if offer_budget==1 else "s"} in the whole game. '
        'Making an OFFER immediately spends one of the proposer\'s offer opportunities, '
        'whether the partner accepts or rejects; it is never refunded. '
        'Responding ACCEPT or REJECT does not spend the responder\'s offer opportunities.')
    lines[5]=('5. Information and investigation: Everyone sees the public preferences and the full '
        'public event history. Each player also knows all of their own preferences. '+
        ('Each player may INVESTIGATE at most once per game. 'if query_budget==1 else f'Each player may INVESTIGATE at most {query_budget} times per game. ')+
        'INVESTIGATE uses the current proposal opportunity and reveals the selected other player\'s '
        'true preference for the selected goal only to the investigator. '
        'The investigation action and target are public; its answer is private. '
        'You may investigate only another player\'s non-public preference that you have not directly '
        'investigated before. All preferences stay fixed throughout the game.')
    lines+=['6. Response tie-breaking (for EVERY player): When responding to an offer, first '
        'maximize your own expected FINAL score using the information available to you. '
        'Only if ACCEPT and REJECT give you the same expected final score, prefer the response '
        'that favours the other players more overall (a higher total expected final score for them). '
        'If both levels are tied, either response is acceptable.']
    goals=goal_requirements(v)
    goals=goals[:next(i for i,line in enumerate(goals)if line.startswith('Cells list'))]
    goals+=['Each cell lists that player\'s commitments required for the goal; none means no requirement from that player.']
    text=['YOUR TASK',f'You are {v["you"]}. Choose your next game action.',
        '',*lines,'',*goals,'',*preference_information(v),'',*prior_text(rules),
        '',*public_history(v),'','CURRENT COMMITMENTS',
        'These commitments have already been accepted and remain in force. Pending additions are not included.',
        '| Player | Binding commitments |','| --- | --- |']
    text += [f'| {player} | '+(', '.join(actions)or'none')+' |'for player,actions in v['binding_commitments'].items()]
    text += ['',*goal_status(rules,node,names),'','PUBLIC TURN STATUS',
        'Remaining proposal order (including the current opportunity and its response): '+
        ' -> '.join(v['remaining_proposers'])+'.',
        'Investigations remaining: '+'; '.join(f'{names.players[p]}={query_budget-node.state.query_used[p]}'for p in range(rules.spec.n_players))+'.',
        'Offer opportunities remaining: '+'; '.join(f'{names.players[p]}={offer_budget-node.state.offer_used[p]}'
            for p in range(rules.spec.n_players))+'.',
        '','CURRENT DECISION']
    if v.get('pending_offer'):
        offer=v['pending_offer']
        text+=['You are RESPONDING to an offer.',
            f'{offer["proposer"]} offers to {offer["partner"]}: '+
            f'{offer["proposer"]} would add '+(', '.join(offer['self_commitments'])or'nothing')+'; '+
            f'{offer["partner"]} would add '+(', '.join(offer['partner_commitments'])or'nothing')+'.',
            'These proposed additions are NOT yet binding. Choose ACCEPT or REJECT.',
            'Apply the response tie-breaking rule when your own expected final scores are equal.']
    else:
        legal=list(dict.fromkeys(a['action']for a in v['legal_actions']))
        text+=['You are taking your PROPOSAL opportunity. There is no pending offer.',
            'Choose one of the currently legal actions: '+', '.join(legal)+'.']
    text+=['','RESPONSE INSTRUCTIONS',
        'Briefly explain your decision using the current state and available information, then make '
        'exactly one registered game-action tool call. Your explanation is private and is not shown '
        'to other players. Keep it outside the tool arguments.']
    return dict(messages=[dict(role='system',content=SYSTEM),dict(role='user',content='\n'.join(text))],
        tools=action_tools(v),seed=seed,temperature=temperature)



def public_history(v):
    """Same complete events and historic commitment tables, direct action titles."""
    old=previous_public_history(v)
    if not v['history']:return old
    starts=[i for i,line in enumerate(old)if any(line.startswith(f'{n}.')for n in range(1,len(v['history'])+1))]
    assert len(starts)==len(v['history'])
    out=[old[0]]
    for n,(start,event)in enumerate(zip(starts,v['history']),1):
        stop=starts[n]if n<len(starts)else len(old)
        block=old[start+1:stop]
        if event.get('action')=='OFFER':main=next(i for i,line in enumerate(block)if ' proposed to 'in line)
        else:main=0
        prefix=f'{n}. '
        if event.get('source')!='voluntary':prefix+='Preset event, not chosen by the player: '
        out.append(prefix+block[main])
        out.extend(line.replace('Binding immediately BEFORE this offer:','Commitments immediately before this offer:')
            .replace('Binding immediately AFTER this response:','Commitments immediately after this response:')
            for i,line in enumerate(block)if i!=main)
    return out


def goal_status_data(rules,node):
    """Public physical bookkeeping only; no preferences, history or future Q."""
    from fractions import Fraction
    committed=node.state.snapshot_commitments();rows=[]
    for goal in rules.spec.goals:
        required=goal.required_actions
        if not required:raise ValueError('Goal needs explicit requirements')
        players=[];missing=[];met=0
        for player in range(rules.spec.n_players):
            refs=[ref for ref in required if ref.player_id==player]
            done=sum(bool(committed[player][ref.action_id])for ref in refs)
            players.append(dict(met=done,required=len(refs)));met+=done
            missing.extend((player,ref.action_id)for ref in refs if not committed[player][ref.action_id])
        completion=Fraction(int(met==len(required)))if goal.binary else Fraction(met,len(required))
        rows.append(dict(goal=goal.goal_id,players=players,met=met,required=len(required),
            completion=str(completion),missing=missing))
    return rows


def goal_status(rules,node,names):
    rows=goal_status_data(rules,node)
    lines=['CURRENT GOAL STATUS',
        'Player columns show fulfilled/required commitments, not preferences. Goal completion is shared by all players; their preferences determine their scores.',
        '| Goal | '+' | '.join(names.players)+' | Current completion | Still needed |',
        '| --- | '+' | '.join('---'for _ in names.players)+' | --- | --- |']
    for row in rows:
        players=[f'{p["met"]}/{p["required"]}'if p['required']else'not required'for p in row['players']]
        needed='; '.join(names.players[p]+'.'+names.actions[p][a]for p,a in row['missing'])or'none'
        lines.append('| '+names.goals[row['goal']]+' | '+' | '.join(players)+' | '+row['completion']+' | '+needed+' |')
    return lines
