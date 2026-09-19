"""CPU checks for the v2 protocol; no teacher continuation or model calls."""
from itertools import product


def prefix_bounds(game, commitments, own_preferences):
    """Superset of reachable terminal states, preserving irreversible bindings.

    Ignores remaining time and bilateral feasibility: conservative, not exact
    reachable bounds. Includes avoid-goal losses; current utility is not a bound.
    """
    free=[(p,a) for p,row in enumerate(commitments) for a,bound in enumerate(row) if not bound]
    if len(free)>16:raise ValueError('Enumeration budget exceeded')
    values=[]
    for bits in product((0,1),repeat=len(free)):
        state=[list(row) for row in commitments]
        for (p,a),v in zip(free,bits):state[p][a]=v
        utility=0.
        for goal in game['goals']:
            required=goal['required_actions']
            matches=[state[r['player_id']][r['action_id']] for r in required]
            satisfaction=float(all(matches)) if goal.get('binary',True) else sum(matches)/len(matches)
            utility+=own_preferences[goal['goal_id']]*satisfaction
        values.append(utility)
    return dict(lower=min(values),upper=max(values),compatible_states=len(values),
                scope='Binding-compatible superset; not exact reachable terminal states')


def paired_bounds(model,baseline):
    return [model['lower']-baseline['upper'],model['upper']-baseline['lower']]


def ownership_graph(game):
    """Typed relation description; canonical hash uses ownership-preserving mapping."""
    from training.social_mixed.structure_coverage import geometry_id
    return dict(structure_hash=geometry_id(game),
        ownership=[(p,a) for p,n in enumerate(game['n_actions_per_player']) for a in range(n)],
        dependencies=[(r['player_id'],r['action_id'],g['goal_id']) for g in game['goals'] for r in g['required_actions']],
        has_cross_player_goal=any(len({r['player_id'] for r in g['required_actions']})>1 for g in game['goals']))
