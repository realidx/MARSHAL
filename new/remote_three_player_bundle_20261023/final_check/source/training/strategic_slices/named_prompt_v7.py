"""September presentation and named action tools, adapted to terminal slices.

No oracle values, opponent private truth, old 0.1 tolerance, or social tie goal.
The September SYSTEM and pure layout/tool helpers are reused explicitly.
"""
import json
from training.b_sft.review_prompt import SYSTEM, layout, chronology, decision
from training.social_mixed.frozen import selfplay_prompt as september
from training.social_mixed.frozen.bp_display import Names, action_tools, action_call

VERSION='terminal-september-named-v1'
LEGACY='terminal-json-act-v6'


def visible(rules,node,own):
    actor=rules.actor(node)
    obs=rules.observation(node,actor,own)
    obs.update(game=rules.public_game(),legal_actions=[a.to_dict() for a in rules.actions(node)])
    names=Names(obs)
    if (len(names.players)!=rules.spec.n_players or len(names.goals)!=len(rules.spec.goals)
            or any(len(names.actions[p])!=n for p,n in enumerate(rules.spec.n_actions_per_player))):
        raise ValueError('September name catalogue does not cover this game')
    v=september.visible(obs)
    v['max_new_commitments_per_player_per_offer']=rules.spec.max_changes
    v['goals']={names.goals[g['goal_id']]:{('ALL_OF' if g.get('binary',True) else 'LINEAR_FRACTION'):[
        names.players[a['player_id']]+'.'+names.actions[a['player_id']][a['action_id']]
        for a in g['required_actions']]} for g in obs['game']['goals']}
    for p,rows in rules.catalogues.items():
        known={names.goals[g]:('want' if rows[0][g]==1 else 'neutral' if rows[0][g]==0 else 'avoid')
               for g in range(len(names.goals)) if all(r[g]==rows[0][g] for r in rows)}
        if known:v['public_preferences'][names.players[p]]=known
    if rules.spec.forbidden_actions is not None:
        v['forbidden_commitments']=names.bindings(rules.spec.forbidden_actions.tolist())
    return obs,v,names


def calls_for(rules,node):
    actor=rules.actor(node);before=node.state.public_state()['commitments']
    names=Names(dict(game=rules.public_game()))
    calls=[action_call(names.action(a.to_dict(),actor,before)) for a in rules.actions(node)]
    if len({canonical(*c) for c in calls})!=len(calls):raise ValueError('Named action mapping is not one-to-one')
    return calls


def canonical(name,args):
    if not isinstance(name,str) or not isinstance(args,dict):raise ValueError('Invalid named call')
    args=dict(args)
    for field in ('self_commitments','partner_commitments'):
        if field in args:
            values=args[field]
            if not isinstance(values,list) or not all(isinstance(x,str) for x in values) or len(set(values))!=len(values):
                raise ValueError('Commitments must be distinct names')
            args[field]=sorted(values)
    return name+':'+json.dumps(args,sort_keys=True,separators=(',',':'))


def request(rules,node,world,seed,temperature=1.,remaining_decisions=None,cutoff=None,reference_others=False):
    obs,v,names=visible(rules,node,world[rules.actor(node)])
    prior=getattr(rules,'background_prior',{'weights':{'want':1,'neutral':1,'avoid':1}})['weights']
    lines=['YOUR TASK',f'You are {v["you"]}.','Choose your next action using the information available to you.',
        '', 'VISIBLE INFORMATION',
        'You see the public history, your own preferences and your private investigation answers. '
        'Other players see their own preferences and their own private answers.',
        '',september.game_rules(obs['game']),'',*layout(v),
        '', 'PUBLIC PREFERENCE SUPPORT',
        'For each player, the following are all allowed complete preference rows. '
        'They are public possibilities, not observations of that player\'s actual private row.']
    for p,rows in rules.catalogues.items():
        lines.append(names.players[p]+':')
        for row in rows:
            lines.append('- '+'; '.join(names.goals[g]+'='+{1:'want',0:'neutral',-1:'avoid'}[value] for g,value in enumerate(row)))
    lines+=['', 'BACKGROUND PROBABILITIES',
        f'Preference weights: want={prior["want"]}, neutral={prior["neutral"]}, avoid={prior["avoid"]}. '
        'For an allowed joint assignment, multiply the weights of all player-goal preferences, '
        'then normalize over joint assignments allowed by the public support. '
        'These are probability weights, not utility multipliers. '
        'Condition on your own preferences, public observations and private answers; preferences stay fixed.',
        '',*chronology(v),'',*decision(v)]
    if remaining_decisions is not None:
        lines+=['', 'YOUR CONTROL WINDOW',f'Remaining controlled decisions: {remaining_decisions}. '
            'Both proposals and responses count as your decisions. The game may end earlier.',
            'Other players, and you after this control window, follow the same fixed certified reference policy '
            'until the native game ends. That policy conditions only on the acting player\'s own information; '
            'it does not see other players\' hidden preferences.']
    elif reference_others:
        lines+=['', 'OTHER PLAYERS','Other players follow the fixed certified reference policy, '
            'conditioned on their own information. You control your decisions until the game ends.']
    objective='Maximize your own expected terminal utility in the original game. '
    if cutoff is not None:
        objective=f'Maximize your own expected commitment utility at proposal cutoff {cutoff}. '
        lines+=['', 'SCORING CUTOFF',f'Score after proposal opportunity {cutoff}, including its pending response.']
    lines+=['', 'DECISION OBJECTIVE',objective+
        'A binary goal contributes only when all its required commitments bind; a linear goal contributes its '
        'binding fraction. Multiply goal completion by your want=+1, neutral=0 or avoid=-1 preference and sum.',
        '', 'RESPONSE INSTRUCTIONS',
        'Briefly explain your decision using the current state and available information, then make exactly one '
        'registered game-action tool call. Your explanation is private and not shown to other players. '
        'Keep it outside the tool arguments.',
        'OFFER adds NEW commitments. INVESTIGATE takes player and goal. PASS, ACCEPT and REJECT take no arguments. '
        'Use a legal argument combination from the registered tools.']
    return dict(messages=[dict(role='system',content=SYSTEM),dict(role='user',content='\n'.join(lines))],
        tools=action_tools(v),seed=seed,temperature=temperature)


def mock_call(req,index=None):
    choices=[(t['function']['name'],args) for t in req['tools'] for args in t['function']['parameters']['enum']]
    name,args=choices[(req['seed'] if index is None else index)%len(choices)]
    return dict(name=name,arguments=json.dumps(args))
