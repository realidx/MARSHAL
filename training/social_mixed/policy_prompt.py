"""Current decision objective over the preserved full-game observation renderer."""
from training.social_mixed.frozen import selfplay_prompt as frozen
from training.b_sft.decision_policy import VERSION as OBJECTIVE_VERSION
from training.b_sft.review_prompt import OBJECTIVE

VERSION = 'outcome-background-v8'
SYSTEM = 'You are a player in a negotiation game. Pursue the goals you want and avoid bringing about the goals you dislike.'
RETRY = frozen.RETRY
tools_for = frozen.tools_for
decode_call = frozen.decode_call
action_call = frozen.action_call
visible = frozen.visible


def render(obs):
    from training.b_sft.review_prompt import layout, chronology, decision
    from training.social_mixed.frozen.bp_display import Names
    v=visible(obs);names=Names(obs);game=obs['game']
    v['max_new_commitments_per_player_per_offer']=game['max_changes']
    v['goals']={names.goals[g['goal_id']]:{('ALL_OF' if g.get('binary',True) else 'LINEAR_FRACTION'):[
        names.players[a['player_id']]+'.'+names.actions[a['player_id']][a['action_id']] for a in g['required_actions']]} for g in game['goals']}
    if game.get('forbidden_actions') is not None:v['forbidden_commitments']=names.bindings(game['forbidden_actions'])
    from training.b_sft.preference_contract import description,profile
    law=game['preference_generation']
    if 'background_prior' in law:prior=law['background_prior']
    else:
        prior=profile('balanced')
        if law['values']==[0,1]:prior['weights']['avoid']=0
    background=description(prior)
    lines=['YOUR TASK',f'You are {v["you"]}.',
           'Choose your next action using the information available to you.',
           '', 'VISIBLE INFORMATION',
           'You see the public history, your own preferences and your private investigation answers. Other players see their own preferences and their own private answers.',
           '',frozen.game_rules(game),'',*layout(v),
           '', 'PREFERENCE CONDITIONS',
           background,
           '',*chronology(v),'',*decision(v),
           'Respond to the pending offer now.' if v.get('pending_offer') else 'Make your proposal decision now.',
           '', 'DECISION OBJECTIVE',OBJECTIVE+' When several choices remain equally suitable, each is equally likely to be chosen.',
           'Other players have their own goals and private information; infer their preferences from observed choices. Their choices are not guaranteed to be optimal.',
           '', 'RESPONSE INSTRUCTIONS',
           'Briefly explain your decision using the current state and available information, then make exactly one registered game-action tool call. Your explanation is private and not shown to other players. Keep it outside the tool arguments.',
           'OFFER adds NEW commitments. INVESTIGATE takes player and goal. PASS, ACCEPT and REJECT take no arguments. Use a legal argument combination from the registered tools.']
    return '\n'.join(lines)
