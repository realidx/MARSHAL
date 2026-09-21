"""P = current decision state + qualitative beliefs; no evidence reconstruction."""
import json
from copy import deepcopy
from training.b_sft import social_named_probe as named
from training.b_sft import review_prompt as prompt
from training.social_mixed.prompt_clarification import clarify, VERSION


def request(task, variant=0):
    # The native scorer retains the original source input for replay. Build a
    # separate model-facing projection without reading any historical event.
    clean = deepcopy(task)
    inp = clean['input']
    for key in ('background_prior', 'previous_belief', 'old_history', 'new_history',
                'new_evidence', 'qualitative', 'qualitative_ranges'):
        inp.pop(key, None)
    inp['voluntary_history'] = []; inp['imposed_setup'] = []
    inp['private_results'] = []; inp['public_preferences'] = []
    actual = deepcopy(inp['current_state']['commitments'])
    # named.present's legacy history validator expects zero bindings for empty
    # history. Restore the actual decision fields immediately after projection.
    inp['current_state']['commitments'] = [[0]*n for n in inp['game']['n_actions_per_player']]
    v = named.present(clean, variant)
    names = named.Names(inp, variant)
    v['binding_commitments'] = names.bindings(actual)
    v['legal_actions'] = [names.action(a, inp['player'], actual) for a in inp['legal_actions']]
    if inp['pending_offer']:
        proposer = inp['current_state']['current_proposer']
        v['pending_offer'] = dict(proposer=names.players[proposer],
            **names.action(dict(action='OFFER', **inp['pending_offer']), proposer, actual))
    # An allowlisted rendering: never render chronology, prior, generation
    # conditions, public/private evidence, or a canonical O prompt.
    v['public_preferences'] = {}
    v['your_private_investigation_answers'] = {}
    beliefs = [dict(player=names.players[b['player']], goal=names.goals[b['goal']],
                    possible_preferences=b['possible_preferences'], favored=b['favored'])
               for b in task['input']['supplied_belief']['semantic_beliefs']]
    lines = ['YOUR TASK', f'You are {v["you"]}.',
             'Choose your next action using the supplied correct current belief.',
             '', prompt.game_rules(v), '', *prompt.layout(v),
             '', 'HOW OTHER PLAYERS CHOOSE', prompt.partner_policy(v),
             '', *prompt.decision(v), '', 'SUPPLIED BELIEF',
             'Use these correct current beliefs directly. possible_preferences lists the preferences still possible; favored states which preference is better supported, or undetermined if none is clearly favored.',
             json.dumps(beliefs, ensure_ascii=False),
             '', 'RESPONSE INSTRUCTIONS', prompt.OBJECTIVE,
             'An action is acceptable if it loses at most 0.1 goal-completion points compared with the best action. When responses are equally good for you, the allowance for helping others is also 0.1 points in total.',
             'Briefly explain your decision, then make exactly one registered game-action tool call. Keep the explanation outside the tool arguments.']
    text = '\n'.join(lines)
    if task.get('prompt_clarification') == VERSION: text = clarify(text)
    return dict(messages=[dict(role='system', content=prompt.SYSTEM), dict(role='user', content=text)],
                tools=named.action_tools(v), tool_choice='auto', parallel_tool_calls=False, max_tokens=1024)
