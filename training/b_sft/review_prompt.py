"""Scoring-aware chronological B/P presentation, from visible facts only."""
import json
from training.b_sft import social_prompt as legacy
# Presentation wording only; numerical teacher policy is unchanged.
OBJECTIVE = ("Pursue the goals you want and avoid bringing about the goals you dislike. "
             "When responding to someone else's offer, if accepting and rejecting are equally good for you, "
             "choose whichever helps the other players more. When making a proposal, passing or investigating, "
             "base your choice on your own interests.")
PARTNER_POLICY = ("Other players pursue the goals they want and avoid bringing about the goals they dislike. "
                  "When responding to an offer, if accepting and rejecting are equally good for them, "
                  "they choose whichever helps the other players more. When making a proposal, passing or "
                  "investigating, they base their choice on their own interests.")
PREFERENCE_CONDITIONS = ("Each preference is want, neutral or avoid. Each player wants at least one goal, "
                         "and each goal has at least one player who is not neutral about it. "
                         "Everyone knows these conditions. Preferences stay fixed throughout the game.")
BELIEF_OUTPUT = ("possible_preferences: the preferences consistent with the available information. "
                 "favored: the preference most clearly supported by the available evidence; use undetermined "
                 "when no single preference is clearly better supported. These fields describe the evidence, "
                 "not your confidence in your answer.")
VERSION = 'bp-background-margin-v6'
SYSTEM = ('You are answering a reasoning question about a negotiation game. '
          'Use the stated rules and visible information. Briefly explain your answer, then make exactly one requested tool call.')

def state_table(v, bindings, heading):
    return [heading, '| Player | Binding commitments |', '| --- | --- |'] + [
        f'| {p} | {legacy._names(bindings[p])} |' for p in v['commitments_available']]

def goal_table(v):
    players=list(v['commitments_available'])
    lines=['GOAL REQUIREMENTS BY PLAYER', '| Goal | Scoring | '+' | '.join(players)+' |',
           '| --- | --- | '+' | '.join('---' for _ in players)+' |']
    for goal,c in v['goals'].items():
        refs=c.get('ALL_OF',c.get('LINEAR_FRACTION'));grouped={p:[] for p in players}
        for ref in refs:
            p,a=ref.split('.',1);grouped[p].append(a)
        lines.append('| '+goal+' | '+('BINARY' if 'ALL_OF' in c else 'LINEAR')+' | '+' | '.join(legacy._names(grouped[p]) for p in players)+' |')
    return lines

def facts_table(v):
    return ['KNOWN PREFERENCES', '| Player | Goal | Preference | Who knows / source |', '| --- | --- | --- | --- |']+[
        '| '+' | '.join([f['player'],f['goal'],f['preference'],'; '.join(f['sources'])])+' |' for f in legacy.preference_facts(v)]

def chronology(v):
    # The projection contains the full public history. Reconstruct from the
    # final state backwards so even nonzero initial bindings are preserved.
    additions={p:set() for p in v['commitments_available']};pending=None
    for e in v['history']:
        if e.get('action')=='OFFER':pending=e
        if e.get('response'):
            if pending is None:raise ValueError('Response without offer')
            if e['response']=='ACCEPT':
                additions[pending['actor']].update(pending['self_commitments'])
                additions[pending['partner']].update(pending['partner_commitments'])
            pending=None
    current={p:[a for a in values if a not in additions[p]] for p,values in v['binding_commitments'].items()}
    lines=['EVENTS IN ORDER'];pending=None
    if not v['history']:return lines+['No earlier events.']
    for i,e in enumerate(v['history'],1):
        marker='Preset event: the player was required to do this, rather than choosing it' if e['source']=='imposed setup' else 'Observed player choice'
        period=f' [{e["belief_period"]}]' if 'belief_period' in e else ''
        lines.append(f'{i}.{period} {marker}.')
        if e.get('action')=='OFFER':
            pending=e
            lines+=state_table(v,current,'Binding immediately BEFORE this offer:')
            lines.append(f'{e["actor"]} proposed to {e["partner"]}: {e["actor"]} would add {legacy._names(e["self_commitments"])}; {e["partner"]} would add {legacy._names(e["partner_commitments"])}. These proposed additions are not yet binding.')
        elif 'response' in e:
            lines.append(f'{e["actor"]} chose {e["response"]}.')
            if e['response']=='ACCEPT':
                for p,key in [(pending['actor'],'self_commitments'),(pending['partner'],'partner_commitments')]:
                    current[p]+= [a for a in pending[key] if a not in current[p]]
            lines+=state_table(v,current,'Binding immediately AFTER this response:');pending=None
        elif e.get('action')=='INVESTIGATE':
            lines.append(f'{e["actor"]} investigated {e["player"]} / {e["goal"]}. The answer was delivered only to {e["actor"]}; it is not public. No commitments changed.')
        elif e.get('action')=='PASS':lines.append(f'{e["actor"]} passed. No commitments changed.')
        else:raise ValueError('Unknown history event')
    if any(set(current[p])!=set(v['binding_commitments'][p]) for p in current):raise ValueError('History/state mismatch')
    return lines

def layout(v):
    lines=goal_table(v)+['','COMMITMENT OPTIONS']
    lines += [f'- {p}: {legacy._names(a)}.' for p,a in v['commitments_available'].items()]
    lines += [f'Each offer may add at most {v["max_new_commitments_per_player_per_offer"]} NEW commitments per involved player. This is a per-offer limit, not a one-commitment limit for the whole game. Different commitments are not mutually exclusive.',
              '',*facts_table(v)]
    if v.get('forbidden_commitments'):
        lines+=['Forbidden commitments:']+[f'- {p}: {legacy._names(a)}.' for p,a in v['forbidden_commitments'].items()]
    return lines

def decision(v):
    lines=state_table(v,v['binding_commitments'],'CURRENT BINDING STATE')
    order=v['remaining_proposers']
    if order:
        if v.get('pending_offer'):
            lines += [f'Now: {v["pending_offer"]["partner"]} must accept or reject {v["pending_offer"]["proposer"]}\'s offer.']
        else:
            lines += [f'Now: {order[0]} may make an offer, pass or investigate, as allowed by the tools.']
        lines += ['After this turn, proposal turns: '+(' -> '.join(order[1:]) if order[1:] else 'none; the game ends')+'.']
    else:
        lines += ['No proposal opportunities remain; the game has ended.']
    lines += ['Investigation uses remaining: '+'; '.join(f'{p}={n}' for p,n in v['investigation_uses_remaining'].items())+'.']
    if v.get('pending_offer'):
        o=v['pending_offer'];lines += [f'PENDING OFFER: {o["proposer"]} to {o["partner"]}: {o["proposer"]} would add {legacy._names(o["self_commitments"])}; {o["partner"]} would add {legacy._names(o["partner_commitments"])}. These additions are NOT included in the current binding state.']
    return lines

def render(v,task_kind,skill):
    lines=['YOUR TASK',f'You are {v["you"]}.',*(['Choose your next action using the supplied belief.'] if task_kind=='P' else [f"What do you believe {v['belief_question']['player']}'s preference for {v['belief_question']['goal']} is?"]),'',game_rules(v),'',*layout(v),
           '', 'PREFERENCE CONDITIONS',preference_conditions(v),
           '', 'HOW OTHER PLAYERS CHOOSE',partner_policy(v)]
    if task_kind=='P':
        b=v['your_current_belief'];lines+=['','YOUR CURRENT BELIEF', 'Use this supplied belief directly; do not reconstruct it from the history.',legacy.belief_description(b['description'])]
        lines+=['Preferences you have not determined: '+legacy._names([f'{r["player"]} / {r["goal"]}' for r in b['unresolved_preferences']])+'.']
        lines+=b.get('assessments',[])
        for term,bounds in v.get('qualitative_ranges',{}).items():
            lines.append(f'In this question, {term.replace("_"," ")} means a probability from {100*bounds[0]:g}% to {100*bounds[1]:g}%.')
        for row in b.get('joint_distribution',[]):
            lines.append(f'Probability {row["probability"]}: '+'; '.join(f'{p}: '+', '.join(f'{g}={value}' for g,value in goals.items()) for p,goals in row['preferences'].items()))
    if 'correct_previous_belief' in v:
        q=v['belief_question'];lines+=['',f'Correct belief about {q["player"]} / {q["goal"]} BEFORE the new evidence: '+json.dumps(v['correct_previous_belief'])]
    if 'new_evidence' in v:lines+=['New evidence: '+v['new_evidence']]
    lines+=['',*chronology(v),'',*decision(v),'','RESPONSE INSTRUCTIONS']
    if task_kind=='B':
        q=v['belief_question'];lines += [f'Assess ONLY {q["player"]} / {q["goal"]}.',belief_output(v),
            'Briefly explain your answer, then make exactly one SUBMIT_BELIEFS call. Keep the explanation outside the tool arguments.']
    else:lines += [OBJECTIVE,'An action is acceptable if it loses at most 0.1 goal-completion points compared with the best action. When responses are equally good for you, the allowance for helping others is also 0.1 points in total.','Briefly explain your decision using your supplied belief, then make exactly one registered game-action tool call. Keep the explanation outside the tool arguments.']
    return '\n'.join(lines)


def preference_conditions(v):
    legacy.generation_rules(v['preference_generation'])  # Validate the source contract.
    from training.b_sft.preference_contract import description,profile
    return description(v.get('background_prior',profile('balanced')),public_fixed=True)

def partner_policy(v):
    legacy.partner_rules(v['partner_policy'])  # Do not silently accept another policy.
    return PARTNER_POLICY+' When several choices remain equally suitable, each is equally likely to be chosen.'

def game_rules(v):
    text=legacy.visible_game_rules(v)
    if all('LINEAR_FRACTION' in c for c in v['goals'].values()):
        lines=text.splitlines()
        lines[1] = ("1. Goals and commitments: Each goal lists player-specific commitments. A goal's completion "
                    "is the fraction of its listed commitments that are binding. A player's preference does not "
                    "change this condition. One binding commitment can contribute to several goals.")
        text='\n'.join(lines)
    return text


def belief_output(v):
    margin=v.get('favored_margin',.1)
    return ("possible_preferences lists every preference still possible, including unlikely ones. "
            f"favored is the leading preference only when its current probability exceeds the next highest by more than {100*margin:g} percentage points. "
            "Otherwise use undetermined. If only one preference remains possible, use that preference as favored. "
            "The background distribution is not your final belief; use the information in this question.")
