"""September system/tools, complete current state, native800 game protocol."""
from copy import copy
import math
from training.b_sft.review_prompt import SYSTEM
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.named_prompt import (
    visible, game_rules, goal_requirements, preference_information,
    public_history, check_independent_preferences)
from training.social_mixed.frozen.bp_display import action_tools

VERSION='native800-readable-prompt-v1'


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
        'Public preferences are fixed as listed above. Every remaining player-goal preference '
        'is drawn independently: want, neutral and avoid each have probability 1/3. '
        'Everyone knows this starting distribution. Preferences stay fixed throughout the game. '
        'Your private information and public choices can change your beliefs.']


def request(rules,node,world,seed,temperature=1.):
    if not hasattr(rules,'query_limit')or not hasattr(rules,'offer_limit'):
        raise ValueError('Native800 prompt requires explicit investigation and offer budgets')
    view=actor_view(rules,node,world)
    obs,v,names=visible(rules,view,world[rules.actor(view)])
    game=obs['game'];query_budget=rules.query_limit;offer_budget=rules.offer_limit
    lines=game_rules(game)
    lines[3]+=(f' Each player may make at most {offer_budget} OFFER actions in the whole game. '
        'Making an OFFER immediately spends one of the proposer\'s offer opportunities, '
        'whether the partner accepts or rejects; it is never refunded. '
        'Responding ACCEPT or REJECT does not spend the responder\'s offer opportunities.')
    lines[5]=('5. Information and investigation: Everyone sees the public preferences and the full '
        'public event history. Each player also knows all of their own preferences. '
        f'Each player may INVESTIGATE at most {query_budget} times per game. '
        'INVESTIGATE uses the current proposal opportunity and reveals the selected other player\'s '
        'true preference for the selected goal only to the investigator. '
        'The investigation action and target are public; its answer is private. '
        'You may investigate only another player\'s non-public preference that you have not directly '
        'investigated before. A preference you inferred from behavior is still eligible if it '
        'meets those rules. All preferences stay fixed throughout the game.')
    lines+=['6. Response tie-breaking (for EVERY player): When responding to an offer, first '
        'maximize your own expected FINAL score using the information available to you. '
        'Only if ACCEPT and REJECT give you the same expected final score, prefer the response '
        'with the larger SUM of expected final scores for all other players. '
        'If both levels are tied, either response is acceptable. '
        'At proposal decisions (OFFER, PASS or INVESTIGATE), do not use other players\' scores '
        'to break your own-score ties.']
    goals=goal_requirements(v)
    goals=goals[:next(i for i,line in enumerate(goals)if line.startswith('Cells list'))]
    goals+=['Each cell lists that player\'s commitments required for the goal; none means no requirement from that player.']
    text=['YOUR TASK',f'You are {v["you"]}. Choose your next game action.',
        '',*lines,'',*goals,'',*preference_information(v),'',*prior_text(rules),
        '',*public_history(v),'','ALREADY ACCEPTED COMMITMENTS',
        'These commitments are already binding and remain in force.',
        '| Player | Binding commitments |','| --- | --- |']
    text += [f'| {player} | '+(', '.join(actions)or'none')+' |'for player,actions in v['binding_commitments'].items()]
    text += ['','PUBLIC TURN STATUS',
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
        'to other players. Keep it outside the tool arguments.',
        'OFFER takes partner, self_commitments and partner_commitments, listing only NEW commitments. '
        'INVESTIGATE takes player and goal. PASS, ACCEPT and REJECT take no arguments. '
        'Use one of the legal argument combinations in the registered tools.']
    return dict(messages=[dict(role='system',content=SYSTEM),dict(role='user',content='\n'.join(text))],
        tools=action_tools(v),seed=seed,temperature=temperature)
