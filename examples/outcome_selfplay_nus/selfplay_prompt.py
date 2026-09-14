"""Readable full-game input from an actor's safe observation only."""
from bp_display import Names, action_tools, action_call, render_history, render_fact, preference_facts, _names

VERSION = 'outcome-readable-prompt-v3'
SYSTEM = ('You are a player in a negotiation game with binding commitments. '
          'Briefly explain your decision, then make one game-action tool call.')
RULES = '''GAME RULES
1. Goals and commitments: Each goal lists player-specific commitments. A binding commitment can contribute to several goals. Preferences do not change goal requirements. A BINARY goal has completion 1 only when ALL its requirements are binding, otherwise 0. A LINEAR goal has completion equal to the fraction of its requirements that are binding; it can score before all are met.
2. Payoffs: At the end of the game, each goal gives you its completion multiplied by +1 for want, 0 for neutral, or -1 for avoid. Your final utility is the sum across goals. There are no intermediate game rewards.
3. Offers: OFFER proposes NEW commitments for yourself and a partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed. The per-offer limit applies separately to each involved player.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal, including a preference already known to you. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.'''
RETRY = ('Your response did not complete one valid game-action tool call. The game state is unchanged. '
         'Make one actual call to a registered action tool using one of its allowed argument combinations. '
         'OFFER lists only NEW named commitments; PASS, ACCEPT and REJECT take no arguments.')


def visible(obs):
    names = Names(obs)
    game, state, player = obs['game'], obs['public_state'], obs['player']
    v = dict(you=names.players[player], public_preferences={},
             your_preferences={names.goals[g]: pref for g, pref in enumerate(obs['own_preferences'])},
             your_private_investigation_answers=names.pref(obs['private_results']),
             binding_commitments=names.bindings(state['commitments']),
             commitments_available={names.players[p]: a for p,a in enumerate(names.actions)},
             remaining_proposers=[names.players[p] for p in game['round_robin'][state['turn_index']:]],
             investigation_uses_remaining={names.players[p]: n for p,n in enumerate(state['investigation_remaining_by_player'])},
             legal_actions=[names.action(a,player,state['commitments']) for a in obs['legal_actions']],history=[])
    # The native transcript records resolved offers as one row. Expand it for
    # display, preserving when additions actually became binding.
    before = [[0]*n for n in game['n_actions_per_player']]
    for event in state['transcript']:
        actor = event['proposer_id']
        action = dict(action='OFFER', **event['offer']) if event['action']=='OFFER' else {k:event[k] for k in ('action','player','goal') if k in event}
        v['history'].append(dict(actor=names.players[actor],source='voluntary',**names.action(action,actor,before)))
        if event['action']=='OFFER':
            v['history'].append(dict(actor=names.players[event['offer']['partner_id']],source='voluntary',response=event['response']))
        before = event['commitments_after']
    if before != state['commitments']:raise ValueError('Public history and binding commitments disagree')
    if obs['pending_offer']:
        actor = state['current_proposer']
        offer = names.action(dict(action='OFFER',**obs['pending_offer']),actor,state['commitments'])
        v['pending_offer'] = dict(proposer=names.players[actor],**offer)
        v['history'].append(dict(actor=names.players[actor],source='voluntary',**offer))
    return v


def render(obs):
    v=visible(obs);names=Names(obs);game=obs['game'];state=obs['public_state']
    lines=[RULES,'','YOUR ROLE AND TASK',f'You are {v["you"]}.',
           'Maximize your own expected final utility. Other players choose their own actions; no fixed decision policy is promised.',
           '', 'GOALS AND COMMITMENTS']
    for g in game['goals']:
        requirements=[f'{names.players[a["player_id"]]} to commit to {names.actions[a["player_id"]][a["action_id"]]}' for a in g['required_actions']]
        met=sum(state['commitments'][a['player_id']][a['action_id']] for a in g['required_actions']);total=len(requirements)
        binary=g.get('binary',True);completion=float(met==total) if binary else met/total
        lines.append(f'- {names.goals[g["goal_id"]]} ({"BINARY: all required" if binary else "LINEAR: fraction of requirements"}): '+ '; '.join(requirements)+f'. Currently {met} of {total} requirements are binding; completion={completion:g}.')
    lines+=['Already binding (currently in force):']
    lines += [f'- {p}: {_names(a)}.' for p,a in v['binding_commitments'].items()]
    forbidden=names.bindings(game['forbidden_actions']) if game.get('forbidden_actions') is not None else {}
    lines+=['Commitment options still available to add (not yet binding):']
    for p,options in v['commitments_available'].items():
        lines.append(f'- {p}: '+_names([a for a in options if a not in v['binding_commitments'][p] and a not in forbidden.get(p,[])])+'.')
    if forbidden:
        lines+=['Forbidden commitments:']+[f'- {p}: {_names(a)}.' for p,a in forbidden.items()]
    lines += [f'An offer may add at most {game["max_changes"]} new commitment(s) per involved player.', '', 'WHAT YOU KNOW']
    lines += ['- '+render_fact(f,v['you']) for f in preference_facts(v)]
    known={(f['player'],f['goal']) for f in preference_facts(v)}
    lines += ['Other preferences not directly revealed to you: '+_names([f'{p}\'s preference for {g}' for p in names.players for g in names.goals if (p,g) not in known])+'.']
    values=game['preference_generation']['values']
    if values not in ([0,1],[-1,0,1]):raise ValueError('Unknown preference generation law')
    choices='want and neutral' if values==[0,1] else 'want, neutral and avoid'
    lines += ['', 'HOW PREFERENCES ARE DRAWN',
              f'Initially, every player-goal preference is drawn independently with equal chances of {choices}. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences. Preferences stay fixed throughout the game.',
              '',render_history(v),'','CURRENT DECISION',
              'Remaining proposal order (first entry is the current opportunity, including its response): '+' -> '.join(v['remaining_proposers'])+'.',
              f'Your proposal opportunities AFTER the current opportunity: {v["remaining_proposers"][1:].count(v["you"])}.',
              'Investigation uses remaining: '+'; '.join(f'{p}={n}' for p,n in v['investigation_uses_remaining'].items())+'.']
    if 'pending_offer' in v:
        o=v['pending_offer']
        lines += [f'Pending offer from {o["proposer"]} to {o["partner"]}: {o["proposer"]} would add {_names(o["self_commitments"])}; {o["partner"]} would add {_names(o["partner_commitments"])}. These additions are not yet binding.', 'Respond to this pending offer now.']
    else:lines+=['Make your proposal decision now.']
    lines += ['Choose one of the legal actions defined by the registered tools and their allowed argument combinations.',
              'Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. The registered tools list the legal choices.']
    return '\n'.join(lines)


def tools_for(obs):
    return action_tools(visible(obs))


def decode_call(obs,name,args):
    if not isinstance(args,dict):return None
    named=visible(obs)['legal_actions']
    for native,shown in zip(obs['legal_actions'],named):
        expected_name,expected_args=action_call(shown)
        if name!=expected_name or set(args)!=set(expected_args):continue
        # Commitment lists denote sets; their order has no game meaning.
        normalized=dict(args)
        for key in ('self_commitments','partner_commitments'):
            if key in args:
                a=args[key]
                if not isinstance(a,list) or any(not isinstance(x,str) for x in a) or len(set(a))!=len(a):break
                normalized[key]=sorted(a)
        else:
            expected={k:sorted(v) if isinstance(v,list) else v for k,v in expected_args.items()}
            if normalized==expected:return native
    return None
