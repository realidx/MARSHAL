"""Human-readable B/P prompts built solely from the existing visible projection.

No teacher labels or private worlds are accepted by this module. Legacy JSON
prompts remain available in social_named_probe for frozen experiment replay.
"""
import json

VERSION = 'bp-readable-prompt-v2'
SYSTEM = ('You are a player in a negotiation game with binding commitments. '
          'Briefly explain your answer, then make one tool call.')
RULES = '''GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.'''


def partner_rules(policy):
    # Only translate the reviewed policy. Do not silently replace a future
    # teacher's assumptions with this one, or expose solver implementation.
    from training.b_sft.debug.audit_private_teaching import POLICY
    if policy != POLICY:
        raise ValueError('Partner policy needs a reviewed plain-language description')
    return ('Other players plan for the end of the game using the actions everyone has seen, '
            'their own preferences and their own investigation answers. They choose actions that '
            'maximize their expected final score. On a tie, they prefer the highest total expected '
            'score for the other players. If actions still tie, they choose equally at random among them.')


def generation_rules(description):
    from training.b_sft.prepare_no_catalogue_probe import GENERATOR
    if description.removeprefix('This is a small teaching game. ') != GENERATOR:
        raise ValueError('Preference generation needs a reviewed plain-language description')
    return ('The preferences known to everyone are fixed. Initially, each other preference is drawn '
            'independently with equal chances of want, neutral and avoid. Draws are repeated until '
            'each player wants at least one goal and each goal has at least one player who is not '
            'neutral about it. Everyone knows these rules; there are no other restrictions on preferences.')


def belief_description(description):
    # Preserve distinctions between an initial conditional belief, a complete
    # belief and a qualitative replacement. These are not interchangeable.
    if description.startswith('Your CURRENT belief is the stated preference-generation distribution'):
        return ('For this decision, use the initial preference distribution conditioned on your known '
                'facts and the game constraints, without further updates from the history.')
    if description.startswith('These known facts completely specify YOUR current belief.'):
        return 'You know every preference needed to specify the current situation.'
    if description.startswith('This is YOUR supplied current assessment.'):
        return ('Use the following assessments for this decision in place of the initial distribution, '
                'while retaining the game constraints. These assessments have not been shared with '
                'other players. Likely does not mean certain; unlikely still means possible.')
    raise ValueError('Supplied belief needs a reviewed plain-language description')


def preference_facts(v):
    """Merge duplicate facts while retaining provenance and refusing conflicts."""
    facts = {}
    def add(rows, source):
        for player, goals in rows.items():
            for goal, value in goals.items():
                key = (player, goal)
                if key in facts and facts[key]['preference'] != value:
                    raise ValueError(f'Conflicting visible preference for {player}/{goal}')
                fact = facts.setdefault(key, dict(player=player, goal=goal, preference=value, sources=[]))
                if source not in fact['sources']: fact['sources'].append(source)
    add(v['public_preferences'], 'public to everyone')
    add({v['you']: v['your_preferences']}, 'your own preference')
    add(v['your_private_investigation_answers'], 'true investigation answer delivered privately to you')
    if 'your_current_belief' in v:
        add(v['your_current_belief']['known_preferences'], 'known in your supplied current belief')
    return list(facts.values())


def _names(values):
    return ', '.join(values) if values else 'none'


def render_fact(fact, you):
    player, goal, value = fact['player'], fact['goal'], fact['preference']
    own = player == you
    verbs = {'want': 'want' if own else 'wants', 'neutral': 'are neutral about' if own else 'is neutral about',
             'avoid': 'want to avoid' if own else 'wants to avoid'}
    claim = f'{"you" if own else player} {verbs[value]} {goal}'
    sources = fact['sources']
    if 'true investigation answer delivered privately to you' in sources:
        line = f'Your investigation revealed that {claim}. The answer was shown only to you.'
    elif own or 'public to everyone' in sources:
        line = claim[0].upper() + claim[1:] + '.'
    else:
        line = f'You know that {claim}.'
    if 'public to everyone' in sources:
        line += ' Everyone knows this preference.'
    return line


def render_history(v):
    lines = ['HISTORY VISIBLE TO EVERYONE']
    if not v['history']: return '\n'.join(lines + ['No earlier events.'])
    if any(e['source']=='imposed setup' for e in v['history']):
        lines.append('Starting events were provided by the task, independently of preferences, '
                     'rather than chosen by players. They do not reveal what a player prefers.')
    pending = None
    for i, event in enumerate(v['history'], 1):
        actor = event['actor']
        prefix = f'{i}. '
        if 'belief_period' in event: prefix += f'[{event["belief_period"]}] '
        setup = event['source']=='imposed setup'
        if event['source'] not in ('imposed setup', 'voluntary'):
            raise ValueError('Unknown history source')
        if setup: prefix += 'Starting event provided by the task: '
        def verb(base, third):
            return f'{actor} {third}' if setup else f'{actor} chose to {base}'
        if 'response' in event:
            if pending is None: raise ValueError('Response without a displayed pending offer')
            if event['response']=='ACCEPT':
                outcome = (f'New binding commitments: {pending["actor"]}: {_names(pending["self_commitments"])}; '
                           f'{pending["partner"]}: {_names(pending["partner_commitments"])}.')
            else: outcome = 'No proposed additions become binding.'
            response = event['response'].lower()
            lines.append(prefix + verb(response, response+'s') + f' {pending["actor"]}\'s offer. {outcome}')
            pending = None
        elif event['action']=='OFFER':
            lines.append(prefix + verb('propose', 'proposes') + f' to {event["partner"]}: '
                         f'{actor} would add {_names(event["self_commitments"])}; '
                         f'{event["partner"]} would add {_names(event["partner_commitments"])}. '
                         'This proposal alone binds nothing.')
            pending = event
        elif event['action']=='INVESTIGATE':
            lines.append(prefix + verb('investigate', 'investigates') + f' {event["player"]}\'s preference for {event["goal"]}. '
                         f'The answer is delivered privately to {actor}, not broadcast. No commitments are added.')
        elif event['action']=='PASS':
            lines.append(prefix + verb('pass', 'passes') + '. No commitments are added.')
        else: raise ValueError('Unknown history event')
    return '\n'.join(lines)


def render(v, task_kind, skill):
    lines = [RULES, '', 'YOUR ROLE AND TASK', f'You are {v["you"]}.',
             v['current_decision'].capitalize() + '.', '', 'GOALS AND COMMITMENTS']
    for goal, condition in v['goals'].items():
        requirements = [f'{p} to commit to {c}' for p,c in (x.split('.', 1) for x in condition['ALL_OF'])]
        lines.append(f'- {goal} requires ' + ' and '.join(requirements) + '.')
    lines += ['Already binding (currently in force):']
    for player, values in v['binding_commitments'].items():
        lines.append(f'- {player}: {_names(values)}.')
    lines += ['Commitment options still available to add (not yet binding):']
    for player, options in v['commitments_available'].items():
        blocked = v.get('forbidden_commitments', {}).get(player, [])
        remaining = [a for a in options if a not in v['binding_commitments'][player] and a not in blocked]
        lines.append(f'- {player}: {_names(remaining)}.')
    if 'forbidden_commitments' in v:
        lines += ['Forbidden commitments:']
        lines += [f'- {p}: {_names(a)}.' for p,a in v['forbidden_commitments'].items()]
    lines += [f'An offer may add at most {v["max_new_commitments_per_player_per_offer"]} new commitment(s) per involved player.',
              '', 'WHAT YOU KNOW']
    for fact in preference_facts(v):
        lines.append('- ' + render_fact(fact, v['you']))
    if task_kind=='P':
        belief = v['your_current_belief']
        lines += ['', 'YOUR CURRENT BELIEF',
                  'Use this belief directly to choose your action.',
                  'Preferences you have not determined: ' +
                  _names([f'{r["player"]}\'s preference for {r["goal"]}' for r in belief['unresolved_preferences']]) + '.',
                  belief_description(belief['description'])]
        lines += ['- Your current assessment: ' + statement for statement in belief.get('assessments', [])]
    if 'correct_previous_belief' in v:
        q = v['belief_question']; b = v['correct_previous_belief']
        lines += [f'Correct PREVIOUS belief about {q["player"]} / {q["goal"]} (before the new evidence): '
                  f'possible_preferences={json.dumps(b["possible_preferences"])}, favored={b["favored"]}.']
    if 'new_evidence' in v:
        evidence = v['new_evidence'].replace('other displayed setup actions were imposed independently of preferences',
            'other starting events were provided by the task independently of preferences')
        lines += ['New information: ' + evidence]
    lines += ['', 'HOW PREFERENCES ARE DRAWN', generation_rules(v['preference_generation']),
              '', 'HOW OTHER PLAYERS CHOOSE', partner_rules(v['partner_policy']),
              '', render_history(v), '', 'CURRENT DECISION']
    order = v['remaining_proposers']
    if order:
        lines += ['Remaining proposal order (first entry is the current opportunity, including its response): ' + ' -> '.join(order) + '.',
                  f'Your proposal opportunities AFTER the current opportunity: {order[1:].count(v["you"])}.']
    else: lines += ['No proposal opportunities remain; the game history is complete.']
    lines += ['Investigation uses remaining: ' + '; '.join(f'{p}={n}' for p,n in v['investigation_uses_remaining'].items()) + '.']
    if 'pending_offer' in v:
        offer = v['pending_offer']
        lines += [f'Pending offer from {offer["proposer"]} to {offer["partner"]}: '
                  f'{offer["proposer"]} would add {_names(offer["self_commitments"])}; '
                  f'{offer["partner"]} would add {_names(offer["partner_commitments"])}. These additions are not yet binding.']
    if task_kind=='B':
        q = v['belief_question']
        lines += [f'Assess ONLY {q["player"]}\'s preference for {q["goal"]}.',
                  v['belief_rules'].replace('observed voluntary behavior', 'observed choices'),
                  'Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of '
                  'objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.']
    else:
        lines += ['Prefer your expected final utility; on own-utility ties, prefer the total expected utility of the other players.',
                  'Choose one of the legal actions defined by the registered tools and their allowed argument combinations.',
                  'Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; '
                  'INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. '
                  'The registered tools list the legal choices.']
    return '\n'.join(lines)
