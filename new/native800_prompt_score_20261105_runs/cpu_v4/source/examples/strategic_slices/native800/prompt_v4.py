"""Common system rules and compact instance facts; unchanged native800 protocol."""
from . import prompt_v3 as previous
from training.strategic_slices.named_prompt import visible

VERSION = 'native800-readable-prompt-v4'
INTRO = ('You are working with other agents to complete multiple goals. Agents may have '
         'different preferences and information. Use the stated rules and visible information '
         'to maximize your own expected final score. Follow the response tie-breaking rule below.')
goal_status_data = previous.goal_status_data


def commitment_status(rules, node):
    """Every required action and its current public bit, plus unused-action fallback."""
    current = node.state.snapshot_commitments()
    required = {(r.player_id, r.action_id) for g in rules.spec.goals for r in g.required_actions}
    all_actions = {(p, a) for p, row in enumerate(current) for a in range(len(row))}
    return dict(required={key: bool(current[key[0]][key[1]]) for key in required},
                other={key: bool(current[key[0]][key[1]]) for key in all_actions-required})


def goals_table(rules, node, names):
    current = node.state.snapshot_commitments()
    lines = ['GOALS AND CURRENT STATUS',
        'Each player column lists ALL commitments required from that player, marked committed or missing. '
        'Only accepted commitments count; pending additions are excluded. None means no requirement. '
        'Goal completion is shared; preferences determine each player\'s score.',
        '| Goal | Scoring | '+' | '.join(n+"'s required commitments" for n in names.players)+' | Current completion |',
        '| --- | --- | '+' | '.join('---' for _ in names.players)+' | --- |']
    for goal, status in zip(rules.spec.goals, goal_status_data(rules, node)):
        cells = []
        for player in range(rules.spec.n_players):
            cells.append(', '.join(names.actions[player][r.action_id]+
                (' [committed]' if current[player][r.action_id] else ' [missing]')
                for r in goal.required_actions if r.player_id == player) or 'none')
        lines.append('| '+names.goals[goal.goal_id]+' | '+('BINARY' if goal.binary else 'LINEAR')+
                     ' | '+' | '.join(cells)+' | '+status['completion']+' |')
    other = commitment_status(rules, node)['other']
    if other:
        lines += ['', 'OTHER COMMITMENT STATUS',
            'Actions not required by any goal: '+ '; '.join(names.players[p]+'.'+names.actions[p][a]+
            (' [committed]' if done else ' [missing]') for (p,a),done in sorted(other.items()))+'.']
    return lines


def history_records(rules, node):
    """One native opportunity per record; preserve original positions under omission."""
    before = [[0]*len(row) for row in node.state.snapshot_commitments()]
    records = []
    for event in node.state.transcript:
        record = dict(turn=event.turn_index, actor=event.proposer_id, action=event.action,
                      before=tuple(tuple(r) for r in before), after=event.commitments_after)
        if event.action == 'OFFER':
            offer = event.offer
            record.update(partner=offer.partner_id, response=event.response,
                additions={event.proposer_id:tuple(a for a,bit in enumerate(offer.proposer_action)
                                                 if bit and not before[event.proposer_id][a]),
                           offer.partner_id:tuple(a for a,bit in enumerate(offer.partner_action)
                                                 if bit and not before[offer.partner_id][a])})
        elif event.action == 'INVESTIGATE':
            record.update(player=event.player, goal=event.goal)
        elif event.action != 'PASS':
            raise ValueError('Unsupported native history event')
        records.append(record)
        before = [list(r) for r in event.commitments_after]
    if tuple(tuple(r) for r in before) != node.state.snapshot_commitments():
        raise ValueError('History and current commitments disagree')
    return records


def public_history(rules, node, names, visible_view):
    lines = ['EVENTS IN ORDER']
    for record in history_records(rules, node):
        actor = names.players[record['actor']]
        if record['action'] == 'OFFER':
            partner = names.players[record['partner']]
            own = ', '.join(names.actions[record['actor']][a] for a in record['additions'][record['actor']]) or 'none'
            other = ', '.join(names.actions[record['partner']][a] for a in record['additions'][record['partner']]) or 'none'
            text = f'{actor} proposed to {partner}: {actor} would add {own}; {partner} would add {other}. '
            text += f'{partner} chose {record["response"]} on this proposal. '
            text += 'These additions are now binding.' if record['response']=='ACCEPT' else 'No commitments were added.'
        elif record['action'] == 'INVESTIGATE':
            text = f'{actor} investigated {names.players[record["player"]]} about {names.goals[record["goal"]]}. No commitments changed.'
        else:
            text = f'{actor} passed. No commitments changed.'
        lines.append(f'{record["turn"]+1}. '+text)
    if visible_view.get('pending_offer'):
        offer = visible_view['pending_offer'];actor=offer['proposer'];partner=offer['partner']
        lines.append(f'{node.state.turn_index+1}. {actor} proposed to {partner}: {actor} would add '+
            (', '.join(offer['self_commitments']) or 'none')+f'; {partner} would add '+
            (', '.join(offer['partner_commitments']) or 'none')+'. These proposed additions are not yet binding.')
    if len(lines)==1:lines.append('No events yet.')
    return lines


def request(rules, node, world, seed, temperature=1.):
    base = previous.request(rules, node, world, seed, temperature)
    original = base['messages'][1]['content']
    common = original.split('GAME RULES\n',1)[1].split('\n\nGOAL REQUIREMENTS BY PLAYER',1)[0]
    system = INTRO+'\n\nCONTEXT\n'+common
    view = previous.actor_view(rules,node,world)
    _,v,names = visible(rules,view,world[rules.actor(view)])
    facts = original.split('PUBLIC PREFERENCES\n',1)[1].split('\n\nEVENTS IN ORDER',1)[0]
    tail = original.split('PUBLIC TURN STATUS\n',1)[1]
    text = [f'You are {v["you"]}. Choose your next action.', '', *goals_table(rules,node,names), '',
            'PUBLIC PREFERENCES\n'+facts, '', *public_history(rules,node,names,v), '', 'PUBLIC TURN STATUS\n'+tail]
    base['messages'] = [dict(role='system',content=system),dict(role='user',content='\n'.join(text))]
    return base
