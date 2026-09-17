"""Current teacher objective; terminal utility itself is unchanged."""
import numpy as np

VERSION = 'response-only-altruism-v1'
DESCRIPTION = (
    'Maximize your expected final score. Only when responding to another player\'s '
    'offer, if ACCEPT and REJECT give you the same expected final score, prefer '
    'the response with the highest total expected final score for the other players. '
    'At proposal decisions (OFFER, PASS or INVESTIGATE), do not use other players\' '
    'scores to break your own-score ties. Choose uniformly at random among any '
    'remaining optimal actions.')


def is_offer_response(actions):
    rows = [a if isinstance(a, dict) else a.to_dict() for a in actions]
    return bool(rows) and all(r.get('response') in ('ACCEPT', 'REJECT') for r in rows)


def optimal_indices(values, actor, actions, tolerance=1e-9):
    values = np.asarray(values, dtype=float)
    own = values[:, actor]
    best = np.flatnonzero(own >= own.max() - tolerance)
    if is_offer_response(actions):
        others = values.sum(axis=1) - own
        best = best[others[best] >= others[best].max() - tolerance]
    return best
