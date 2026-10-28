"""Frozen pure display helpers from the reviewed B/P interface.
No teacher imports, labels, beliefs, or partner assumptions.
See README for provenance; update explicitly with the self-play prompt.
"""

# Source: training/b_sft/social_named_probe.py; SHA256 0146e011a1f4f35826f56b30a555cd475869cdcff317f09b99454f8159132e27

PLAYERS = ('Alex', 'Blair', 'Casey', 'Drew')


GOALS = ('Orchard', 'Harbor', 'Library', 'Garden', 'Workshop', 'Market', 'Museum', 'Station', 'School', 'Bridge')


COMMITS = ('Cedar', 'Maple', 'Willow', 'Birch', 'Elm', 'Pine')


class Names:
    def __init__(self, inp, variant=0):
        game = inp['game']
        self.players = list(PLAYERS[:game['n_players']])
        self.goals = list(GOALS[:len(game['goals'])])
        # A semantic renaming control, not a reordering of native game actions.
        self.actions = [list(COMMITS[variant:]+COMMITS[:variant])[:n]
                        for n in game['n_actions_per_player']]
        if variant:
            self.players.reverse()
            self.goals.reverse()

    def pref(self, rows):
        result = {}
        for r in rows:
            result.setdefault(self.players[r['player']], {})[self.goals[r['goal']]] = r['preference']
        return result

    def bindings(self, vectors):
        return {self.players[p]: [self.actions[p][i] for i, bit in enumerate(row) if bit]
                for p, row in enumerate(vectors)}

    def action(self, action, actor, before):
        if 'response' in action:
            return dict(response=action['response'])
        kind = action['action']
        if kind == 'PASS':
            return dict(action=kind)
        if kind == 'INVESTIGATE':
            return dict(action=kind, player=self.players[action['player']], goal=self.goals[action['goal']])
        if kind != 'OFFER':
            raise ValueError('Unsupported teaching action')
        partner = action['partner_id']
        result = dict(action=kind, partner=self.players[partner])
        for key, p, vector in [('self_commitments', actor, action['proposer_action']),
                               ('partner_commitments', partner, action['partner_action'])]:
            if len(vector) != len(before[p]) or any(a < b for a, b in zip(vector, before[p])):
                raise ValueError('Cannot silently withdraw or truncate a native commitment')
            result[key] = [self.actions[p][i] for i, bit in enumerate(vector) if bit and not before[p][i]]
        return result


def action_call(action):
    """Lossless game action -> registered function name and arguments."""
    key = 'response' if 'response' in action else 'action'
    return action[key], {k:v for k,v in action.items() if k != key}


def action_tools(visible):
    groups = {}
    for action in visible['legal_actions']:
        name, args = action_call(action)
        groups.setdefault(name, []).append(args)
    descriptions = {
        'OFFER': 'Propose NEW commitments for yourself and your partner. Acceptance binds both sets of additions.',
        'PASS': 'Spend the current proposal opportunity without adding commitments.',
        'INVESTIGATE': 'Spend the current proposal opportunity and your investigation use to privately learn the selected player\'s true preference for the selected goal.',
        'ACCEPT': 'Accept the pending offer and bind its additions.',
        'REJECT': 'Reject the pending offer without binding its additions.',
    }
    tools = []
    for name, choices in groups.items():
        properties = {}
        for key in choices[0]:
            if key in ('self_commitments', 'partner_commitments'):
                choices_for_field = sorted({x for c in choices for x in c[key]})
                items = dict(type='string')
                if choices_for_field: items['enum'] = choices_for_field
                properties[key] = dict(type='array', items=items, uniqueItems=True,
                    maxItems=max(len(c[key]) for c in choices),
                    description=('Your own NEW commitments.' if key=='self_commitments' else 'Your partner\'s NEW commitments.'))
            else:
                properties[key] = dict(type='string', enum=sorted({c[key] for c in choices}))
        # enum preserves the exact legal combinations, not their Cartesian product.
        schema = dict(type='object', properties=properties, required=list(properties),
                      additionalProperties=False, enum=choices)
        tools.append(dict(type='function', function=dict(name=name,
            description=descriptions[name], parameters=schema)))
    return tools


# Source: training/b_sft/social_prompt.py; SHA256 f92d0ab4b0b40cc81774f86c357bfd2287b18cb0365c6b3a0c13d2c00b39464b

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
