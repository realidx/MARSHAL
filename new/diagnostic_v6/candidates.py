"""Teacher-only candidate generation for the decision-sufficient suite."""
from contextlib import contextmanager
import random

import new.diagnostic_v4.build as v4
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.preference_contract import profile


ORIGINAL_CANDIDATE_RAW = v4.candidate_raw


def strong_binary_raw(seed, mode):
    """Trade-off motif whose preset semantic region can have a robust optimum.

    Relative to v4, goal 3 adds focal utility to the uncertain proposal without
    changing the partner's response incentive.  This makes it possible (but not
    automatic) for one action to remain optimal over the broad full-support,
    undetermined prior region while a support-eliminating observation favors a
    different action.  All candidates are still solved and certified exactly.
    """
    # Retain the original linear generator for the legacy seed range, then use
    # the stronger motif to enlarge the independently generated geometry pool.
    if mode == 'linear' and seed < 20000:
        return ORIGINAL_CANDIDATE_RAW(seed, mode)
    rng = random.Random(seed)
    counts = [rng.choice((2, 3)), rng.choice((2, 3))]
    goals = rng.choice((4, 5, 6, 7))
    target = 2
    own = [1, 1, 1, 1] + [rng.choice((1, 0, -1))
                             for _ in range(goals - 4)]
    partner = [1, 0, 0, 0] + [1 for _ in range(goals - 4)]
    pairs = [(1, 0), (1, 1), (0, 0), (0, 0)]
    for extra in range(goals - 4):
        left = 2 if extra == 0 and counts[0] == 3 else rng.randrange(counts[0])
        right = 2 if extra == 1 and counts[1] == 3 else rng.randrange(counts[1])
        pairs.append((left, right))
    requirements = [dict(
        goal_id=goal, binary=mode == 'binary',
        required_actions=[dict(player_id=0, action_id=left),
                          dict(player_id=1, action_id=right)])
        for goal, (left, right) in enumerate(pairs)]
    rows = []
    for value in v4.NUMERIC:
        row = partner.copy()
        row[target] = value
        rows.append(row)
    raw = dict(
        id=f'diagnostic-v6-{mode}-{seed}', ego=0,
        own_preferences=own, history=[],
        type_catalogues={'0': [own], '1': rows},
        game=dict(n_players=2, n_actions_per_player=counts, max_changes=1,
                  menu_enabled=False, round_robin=[1, 0], goals=requirements),
        background_prior=profile('balanced'))
    raw, public, expansion = expand_support(raw)
    if expansion['unknown_slots'] != [(1, target)]:
        return None
    return raw, public, target


@contextmanager
def _candidate_source():
    original = v4.candidate_raw
    v4.candidate_raw = strong_binary_raw
    try:
        yield
    finally:
        v4.candidate_raw = original


def matched_candidate(seed, mode, occupied):
    with _candidate_source():
        return v4.matched_candidate(seed, mode, occupied)
