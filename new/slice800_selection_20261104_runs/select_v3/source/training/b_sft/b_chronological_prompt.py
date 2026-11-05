"""Review-only chronological rendering of a final-response B lesson.

Accepts the visible projection only. No labels, solver values, or private worlds.
The formal B/P renderer is unchanged.
"""
import json
from training.b_sft.social_prompt import RULES, generation_rules, partner_rules, preference_facts

def names(values):
    return ', '.join(values) if values else 'none'

def render(v):
    if any('LINEAR_FRACTION' in c for c in v['goals'].values()):
        raise ValueError('This frozen final-response renderer supports binary goals only; use the scoring-aware B/P renderer')
    history=v['history']
    if len(history)!=3 or history[0].get('action')!='PASS' or history[1].get('action')!='OFFER' or history[2].get('response') not in ('ACCEPT','REJECT'):
        raise ValueError('Only PASS / OFFER / final response supported')
    if [e['source'] for e in history]!=['imposed setup','imposed setup','voluntary'] or v['remaining_proposers'] or v.get('pending_offer'):
        raise ValueError('Expected two imposed events and a completed final response')
    if v.get('forbidden_commitments') or v.get('new_evidence'):
        raise ValueError('Additional facts need explicit rendering')
    players=list(v['commitments_available']);offer=history[1];response=history[2]
    before={p:[] for p in players}
    after={p:[] for p in players}
    if response['response']=='ACCEPT':
        after[offer['actor']]=offer['self_commitments'][:]
        after[offer['partner']]=offer['partner_commitments'][:]
    if after!=v['binding_commitments']:raise ValueError('Displayed history and state disagree')
    q=v['belief_question'];b=v['correct_previous_belief']
    lines=['YOUR ROLE AND QUESTION',f'You are {v["you"]}.',
           f'Assess ONLY {q["player"]}\'s preference for {q["goal"]} after the observed response. Do not take a game action.',
           '',RULES,'','GOAL REQUIREMENTS — ALL LISTED COMMITMENTS ARE REQUIRED',
           '| Goal | '+' | '.join(players)+' |','| --- | '+' | '.join('---' for _ in players)+' |']
    for goal,condition in v['goals'].items():
        grouped={p:[] for p in players}
        for ref in condition['ALL_OF']:
            p,a=ref.split('.',1);grouped[p].append(a)
        lines.append('| '+goal+' | '+' | '.join(names(grouped[p]) for p in players)+' |')
    lines+=['','COMMITMENT OPTIONS (THE FULL SET, NOT A STATE SNAPSHOT)']
    lines += [f'- {p}: {names(actions)}.' for p,actions in v['commitments_available'].items()]
    lines += [f'An offer may add at most {v["max_new_commitments_per_player_per_offer"]} new commitment(s) per involved player.',
              '', 'KNOWN PREFERENCES', '| Player | Goal | Preference | Who knows |', '| --- | --- | --- | --- |']
    for fact in preference_facts(v):
        # Explicit names preserve ownership; provenance is retained independently.
        lines.append('| '+' | '.join([fact['player'],fact['goal'],fact['preference'], '; '.join(fact['sources'])])+' |')
    lines+=['','HOW PREFERENCES ARE DRAWN',generation_rules(v['preference_generation']),
            '', 'HOW OTHER PLAYERS CHOOSE',partner_rules(v['partner_policy']),
            '', 'EVENTS IN ORDER',
            'The following PASS and OFFER were imposed by the task, independently of preferences. Neither is evidence of a player\'s preference.',
            f'1. Imposed setup: {history[0]["actor"]} passed. No commitments were added.',
            '2. Immediately before the offer:', *[f'   {p}: {names(before[p])} binding.' for p in players],
            f'3. Imposed offer: {offer["actor"]} proposed to {offer["partner"]}:',
            f'   {offer["actor"]} would add {names(offer["self_commitments"])}.',
            f'   {offer["partner"]} would add {names(offer["partner_commitments"])}.',
            '   These are proposed additions, not yet binding. This is the final proposal opportunity, including its response.',
            f'   Correct belief about {q["player"]} / {q["goal"]} BEFORE the response: possible_preferences={json.dumps(b["possible_preferences"])}, favored={b["favored"]}.',
            f'4. New voluntary evidence: {response["actor"]} chose {response["response"]}.',
            '5. After that response, the game ended. The binding commitments are:',
            *[f'   {p}: {names(after[p])}.' for p in players],
            '   No proposal opportunities remain.',
            '   Unused investigation uses: '+'; '.join(f'{p}={n}' for p,n in v['investigation_uses_remaining'].items())+'.',
            '', 'YOUR BELIEF SUBMISSION',v['belief_rules'].replace('observed voluntary behavior','observed choices'),
            'Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.']
    return '\n'.join(lines)
