"""Readable game instructions with the same visible facts and probability law.

v8 separates public and private facts without source/knowledge labels. Exact
factorized catalogues are written as independent draws; native tools are unchanged.
"""
from itertools import product
import math

from training.b_sft.review_prompt import SYSTEM, chronology, decision
from training.social_mixed.frozen.bp_display import action_tools
from .named_prompt_v7 import visible, calls_for, canonical, mock_call, LEGACY

VERSION='terminal-readable-named-v2'
V7='terminal-september-named-v1'


def check_independent_preferences(rules):
    """Reject restrictions/correlations that independent wording would conceal."""
    for rows in rules.catalogues.values():
        domains=[{row[g] for row in rows} for g in range(len(rows[0]))]
        if any(len(values)!=1 and values!={-1,0,1} for values in domains):
            raise ValueError('Readable independent prior requires fixed or want/neutral/avoid cells')
        if set(rows)!=set(product(*domains)):
            raise ValueError('Catalogue has joint restrictions; independent-prior wording is not valid')


def game_rules(game):
    noun='commitment' if game['max_changes']==1 else 'commitments'
    return [
        'GAME RULES',
        '1. Goals: Each goal is marked BINARY or LINEAR in the table below. '
        'For a BINARY goal, completion is 1 if ALL listed commitments are binding, and 0 otherwise. '
        'For a LINEAR goal, completion is the fraction of its listed commitments that are binding; '
        'for example, 1 of 2 required commitments gives completion 0.5. '
        'Requirements are player-specific: Alex undertaking Cedar and Blair undertaking Cedar '
        'are different commitments. One commitment can contribute to several goals.',
        '2. Final score: For each goal, multiply its completion by your preference: '
        'want = +1, neutral = 0, avoid = -1. Add these values across goals. '
        'Your objective is to maximize your own expected score at the END OF THE GAME.',
        '3. Commitments and offers: A commitment is an action a player agrees to undertake. '
        'OFFER proposes NEW commitments for yourself and one partner; it does not transfer items. '
        'ACCEPT makes all proposed additions binding; REJECT makes none binding. '
        'Existing binding commitments cannot be removed or added a second time. '
        f'Each offer may add at most {game["max_changes"]} new {noun} per involved player.',
        '4. Turns: An offer and its response together use one proposal opportunity. '
        'PASS uses that opportunity without changing commitments. Players follow the proposal order '
        'shown in the current state. The game ends after the last opportunity and its response, if any.',
        '5. Information and investigation: Everyone knows the public preferences and public event history. '
        'Each player also knows all of their own preferences. Each player can INVESTIGATE once per game. '
        'INVESTIGATE uses the current proposal opportunity and reveals the selected other player\'s '
        'true preference for the selected goal to the investigator only. '
        'The investigation action and its target are public; its answer is private. '
        'All preferences stay fixed throughout the game.',
    ]


def goal_requirements(v):
    players=list(v['commitments_available'])
    lines=['GOAL REQUIREMENTS BY PLAYER',
        '| Goal | Scoring | '+' | '.join(p+"'s required commitments" for p in players)+' |',
        '| --- | --- | '+' | '.join('---' for _ in players)+' |']
    for goal,rule in v['goals'].items():
        required=rule.get('ALL_OF',rule.get('LINEAR_FRACTION'));grouped={p:[] for p in players}
        for ref in required:
            p,action=ref.split('.',1);grouped[p].append(action)
        lines.append('| '+goal+' | '+('BINARY' if 'ALL_OF' in rule else 'LINEAR')+' | '+
            ' | '.join(', '.join(grouped[p]) or 'none' for p in players)+' |')
    lines+=['Cells list commitments required for the goal, not player preferences. '
        '"none" means the goal requires no commitment from that player.',
        'Possible commitment names by player: '+
        '; '.join(p+': '+(', '.join(actions) or 'none') for p,actions in v['commitments_available'].items())+'. '
        'The registered tools specify which NEW commitments can legally be proposed now.']
    if v.get('forbidden_commitments'):
        lines+=['Forbidden commitments: '+
            '; '.join(p+': '+(', '.join(actions) or 'none') for p,actions in v['forbidden_commitments'].items())+'.']
    return lines


def preference_information(v):
    """Only direct visible facts; no inferred beliefs or who-knows labels."""
    public=v['public_preferences'];private={}
    def add(player,goal,value):
        if goal in public.get(player,{}):
            if public[player][goal]!=value:raise ValueError('Private/public preference conflict')
            return
        key=player,goal
        if key in private and private[key]!=value:raise ValueError('Conflicting private facts')
        private[key]=value
    for goal,value in v['your_preferences'].items():add(v['you'],goal,value)
    for player,goals in v['your_private_investigation_answers'].items():
        for goal,value in goals.items():add(player,goal,value)
    header=['| Player | Goal | Preference |','| --- | --- | --- |']
    lines=['PUBLIC PREFERENCES','These preferences are fixed and known to every player.']
    rows=[f'| {player} | {goal} | {value} |' for player,goals in public.items() for goal,value in goals.items()]
    lines+=header+rows if rows else ['None.']
    lines+=['','YOUR PRIVATE INFORMATION',
        'These are the additional preference facts available to you through your private information.']
    rows=[f'| {player} | {goal} | {value} |' for (player,goal),value in private.items()]
    lines+=header+rows if rows else ['No additional private preference facts.']
    return lines


def background_preferences(rules):
    prior=getattr(rules,'background_prior',{'weights':{'want':1,'neutral':1,'avoid':1}})['weights']
    total=sum(prior.values())
    if set(prior)!={'want','neutral','avoid'} or total<=0 or any(not math.isfinite(value) or value<0 for value in prior.values()):
        raise ValueError('Invalid preference weights')
    chances=('want, neutral and avoid are equally likely (1/3 each)' if len(set(prior.values()))==1
        else ', '.join(f'{name} {100*prior[name]/total:g}%' for name in ('want','neutral','avoid')))
    return ['BACKGROUND PREFERENCE DISTRIBUTION',
        'Public preferences are fixed as listed above. Every other player-goal preference is drawn '
        f'independently with these starting probabilities: {chances}. '
        'Everyone knows this distribution. These are probabilities of preferences, not scoring weights. '
        'Your private information and observed choices can change your beliefs.']


def public_history(v):
    # The event itself names investigator/target. No additional who-knows label.
    lines=chronology(v)
    for event in v['history']:
        if event.get('action')=='INVESTIGATE':
            sentence=f'The answer was delivered only to {event["actor"]}; it is not public. '
            lines=[line.replace(sentence,'') for line in lines]
    return lines


def current_decision(v):
    lines=decision(v)
    lines[0]='COMMITMENTS ALREADY IN FORCE'
    return lines


def request(rules,node,world,seed,temperature=1.,remaining_decisions=None,cutoff=None,reference_others=False):
    check_independent_preferences(rules)
    obs,v,_=visible(rules,node,world[rules.actor(node)])
    lines=['YOUR TASK',f'You are {v["you"]}. '
        'Choose your next action to maximize your own expected score at the end of the game.',
        '',*game_rules(obs['game']),'',*goal_requirements(v),
        '',*preference_information(v),'',*background_preferences(rules),
        '',*public_history(v),'',*current_decision(v)]
    if remaining_decisions is not None:
        noun='decision' if remaining_decisions==1 else 'decisions'
        lines+=['','DECISIONS IN THIS EXERCISE',
            f'You will choose at most {remaining_decisions} more {noun}, including this one; '
            'the game may end sooner. A proposal decision and a response decision each count as one. '
            'Other players use precomputed game-playing strategies. If the game continues after your '
            'decisions in this exercise, a precomputed strategy also makes your later decisions. '
            'Each strategy uses only information available to the player taking that action. '
            'Your score is still calculated when the WHOLE GAME ends, not when these decisions end.']
    elif reference_others:
        lines+=['','OTHER PLAYERS',
            'Other players use precomputed game-playing strategies based on their own information. '
            'You choose your own decisions until the game ends.']
    if cutoff is not None:
        # Historical bounded evaluations are separate from terminal training.
        lines[1]=f'You are {v["you"]}. Choose your next action to maximize your own expected score at the scoring cutoff.'
        lines+=['','SCORING CUTOFF',f'For this bounded exercise, score the binding commitments after '
            f'proposal opportunity {cutoff} and its response, if any. This replaces end-of-game scoring.']
    lines+=['','RESPONSE INSTRUCTIONS',
        'Briefly explain your decision using the current state and available information, then make '
        'exactly one registered game-action tool call. Your explanation is private and is not shown '
        'to other players. Keep it outside the tool arguments.',
        'OFFER takes partner, self_commitments and partner_commitments, listing only NEW commitments. '
        'INVESTIGATE takes player and goal. PASS, ACCEPT and REJECT take no arguments. '
        'Use one of the legal argument combinations in the registered tools.']
    return dict(messages=[dict(role='system',content=SYSTEM),dict(role='user',content='\n'.join(lines))],
        tools=action_tools(v),seed=seed,temperature=temperature)
