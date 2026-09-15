"""Deduplicate actual questions modulo names, player/goal/commitment numbering."""
import hashlib
from itertools import permutations, product
import json


def semantic_id(task):
    i = task['input']; game = i['game']; ego = i['observer']; n = game['n_players']
    counts = game['n_actions_per_player']; candidates = []
    public = {(r['player'], r['goal']): r['preference'] for r in i['public_preferences']}
    private = {(r['player'], r['goal']): r['preference'] for r in i['private_results']}
    belief = {(r['player'], r['goal']): r['preference'] for r in i.get('supplied_belief', {}).get('known_preferences', [])}
    assessments = {(r['player'], r['goal']): (r['preference'], r['qualifier']) for r in i.get('qualitative', {}).get('assessments', [])}
    query = i.get('queries', [{}])[0]
    for others in permutations(p for p in range(n) if p != ego):
        order = [ego]+list(others); pm = {p: j for j, p in enumerate(order)}
        for am in product(*(tuple(permutations(range(c))) for c in counts)):
            goals = []
            for g in game['goals']:
                q = g['goal_id']
                descriptor = [sorted((pm[a['player_id']], am[a['player_id']][a['action_id']]) for a in g['required_actions']),
                    [(public.get((p,q)), private.get((p,q)), belief.get((p,q)), assessments.get((p,q))) for p in order],
                    i['own_preferences'][f'goal_{q}'], pm[query['player']] if query.get('goal') == q else None]
                goals.append(json.dumps(descriptor, sort_keys=True))
            def vector(v, player):
                out = [0]*len(v)
                for old, bit in enumerate(v): out[am[player][old]] = bit
                return out
            def events(events):
                out = []; turn = 0
                for a in events:
                    if 'response' in a:
                        out.append(a); turn += 1; continue
                    kind = a['action']; actor = game['round_robin'][turn]
                    if kind == 'OFFER':
                        partner = a['partner_id']
                        out.append([kind, pm[actor], pm[partner], vector(a['proposer_action'], actor), vector(a['partner_action'], partner)])
                    elif kind == 'INVESTIGATE':
                        out.append([kind, pm[actor], pm[a['player']], goals[a['goal']]]); turn += 1
                    else: out.append([kind, pm[actor]]); turn += 1
                return out
            all_events = i['imposed_setup']+i['voluntary_history']
            obj = dict(task=task['task'], counts=[counts[p] for p in order], goals=sorted(goals),
                max_changes=game['max_changes'], schedule=[pm[p] for p in game['round_robin']],
                events=events(all_events), imposed_count=len(i['imposed_setup']),
                previous=i.get('previous_belief'), new_count=len(i.get('new_history', [])),
                new_evidence=i.get('new_evidence'), belief_description=i.get('supplied_belief', {}).get('support'),
                commitments=[vector(i['current_state']['commitments'][p], p) for p in order],
                remaining=[i['current_state']['investigation_remaining_by_player'][p] for p in order])
            candidates.append(json.dumps(obj, sort_keys=True, separators=(',', ':')))
    return hashlib.sha256(min(candidates).encode()).hexdigest()
