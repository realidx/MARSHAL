from collections import Counter
from copy import deepcopy
from dataclasses import replace
from itertools import product
import json
import random

import numpy as np
import pytest

from benac_p.b_data_audit import audit_game, explicit_worlds, write_dataset
from benac_p.b_training_data import (
    OPTIONS, SamplePool, independence_certificate, independent_catalogues,
    make_game, payload, score_set, select_balanced, to_chat_sample,
)
from benac_p.mcts_oracle import Budget, PrivateUCT


def test_focal_values_are_independent_within_every_background_and_other_focal_value():
    rows, focal, public = independent_catalogues(4, 16, 91)
    cert = independence_certificate(rows, focal)
    assert all(c['backgrounds'] == 6 and c['combinations_per_background'] == 9 for c in cert)
    for p in range(4):
        assert len(rows[p]) == 54
        for g in focal[p]:
            groups = {}
            for row in rows[p]:
                key = tuple(v for i, v in enumerate(row) if i != g)
                groups.setdefault(key, set()).add(row[g])
            assert all(s == {-1, 0, 1} for s in groups.values())
        # Public compact description reconstructs the EXACT ordered catalogue.
        reconstructed = []
        for background in public[p]['background_rows']:
            for values in product((1, 0, -1), repeat=2):
                row = list(background)
                for g, v in zip(public[p]['independent_goal_ids'], values):
                    row[g] = v
                reconstructed.append(tuple(row))
        assert tuple(reconstructed) == rows[p]


@pytest.mark.parametrize('cell', ('n4_k2_g12_r4', 'n4_k3_g16_r6'))
def test_cached_oracle_is_bitwise_equivalent_to_frozen_policy(cell):
    spec, fast, actual, focal, _ = make_game(63001, cell, Budget(simulations=128), backgrounds=3)
    original = PrivateUCT(spec, fast.catalogues, fast.budget)
    rng = random.Random(8)
    node = (0, 0, None)
    for step in range(6):
        actor = fast.actor(node)
        for own in (0, 1, 3):
            a = fast.search(node, actor, own, fast.prior)
            b = original.search(node, actor, own, original.prior)
            for key in ('action', 'counts', 'means', 'root_action_coverage', 'tree_nodes'):
                assert a[key] == b[key]
        node = fast.step(node, rng.choice(fast.actions(node)))
    fast.clear_caches(); original.clear_caches()


def test_completed_goal_preference_constant_shift_does_not_reveal_itself_in_control():
    spec, oracle, actual, focal, _ = make_game(63000, 'n4_k2_g12_r4', Budget(simulations=256))
    actor = spec.round_robin[8]
    goal = spec.goals[focal[actor][0]]
    mask = sum(1 << (oracle.offsets[a.player_id] + a.action_id) for a in goal.required_actions)
    # These three rows differ ONLY at the first focal goal, already satisfied.
    rows = [oracle.catalogues[actor][t] for t in (0, 3, 6)]
    g = focal[actor][0]
    assert len({tuple(v for i, v in enumerate(r) if i != g) for r in rows}) == 1
    decisions = [oracle.search((mask, 8, None), actor, t, oracle.prior)['action'] for t in (0, 3, 6)]
    assert len(set(decisions)) == 1
    oracle.clear_caches()


def test_payload_and_chat_do_not_reveal_labels_domains_or_private_realization():
    spec, oracle, actual, focal, public = make_game(63001, 'n4_k2_g12_r4', Budget(simulations=16))
    learner = spec.round_robin[0]
    target = (learner+1) % 4
    p = payload(oracle, public, (0, 0, None), learner, actual[learner], [], target, focal[target][0])
    assert 'private_preferences' not in p['game'] and 'seed' not in p['game']
    assert not {'answer', 'domains', 'realized_type_ids', 'support_type_ids'} & set(p)
    row = dict(id='sample', source_id='source', input=p, answer=dict(possible_preferences=OPTIONS),
               certificate={'private_sentinel': 'do not expose'}, origins=[])
    chat = to_chat_sample(row)
    assert 'private_sentinel' not in json.dumps(chat)
    assert chat['messages'][-1]['content'] == ''
    assert json.loads(chat['messages'][-1]['tool_calls'][0]['function']['arguments']) == row['answer']
    assert chat['tools'][0]['function']['name'] == 'SUBMIT_JUDGMENT'
    oracle.clear_caches()


def test_set_scoring_distinguishes_guessing_and_overbroad_uncertainty():
    assert score_set(['want'], ['want', 'neutral'])['false_exclusions'] == 1
    assert score_set(OPTIONS, ['want'])['unsupported_possibilities'] == 2
    assert score_set(['neutral', 'want'], ['want', 'neutral'])['exact']
    for invalid in ([], ['want', 'want'], ['unknown'], 'want', None, [1]):
        score = score_set(invalid, ['want'])
        assert not score['valid'] and not score['exact']
        assert score['set_error'] is None


def test_dedup_refuses_contradictory_labels_and_balancing_does_not_invent_data():
    pool = SamplePool()
    for index, answer in enumerate((['want'], ['want', 'neutral'], OPTIONS, OPTIONS)):
        pool.add('source', {'query': index}, {'possible_preferences': answer}, {'kind': 'natural'}, {})
    pool.add('source', {'query': 0}, {'possible_preferences': ['want']}, {'kind': 'counterfactual'}, {})
    assert len(pool.records) == 4 and pool.duplicate_attempts == 1
    with pytest.raises(AssertionError):
        pool.add('source', {'query': 0}, {'possible_preferences': OPTIONS}, {}, {})
    selected = select_balanced(list(pool.records.values()), per_size=1)
    assert Counter(len(r['answer']['possible_preferences']) for r in selected) == {1: 1, 2: 1, 3: 1}


def test_exhaustive_world_array_and_b_only_episode_certificates(tmp_path):
    game, raw, selected, pairs = audit_game(63000, 'n4_k2_g12_r4', Budget(simulations=32),
                                           backgrounds=3, max_branches=3, per_size=8)
    assert game['stats']['native_replay_verified'] and game['stats']['explicit_joint_support_verified']
    assert game['stats']['initial_hidden_worlds'] == 27 ** 3
    by_id = {r['id']: r for r in raw}
    for pair in pairs:
        a = set(by_id[pair['before']]['answer']['possible_preferences'])
        b = set(by_id[pair['after']]['answer']['possible_preferences'])
        assert b <= a
        if pair['transition'] == 'intervention_unchanged':
            assert a == b
    assert any(not p['natural'] for p in pairs)
    assert set(game['stats']['selected_support_sizes']) == {1, 2, 3}
    summary = write_dataset(tmp_path, [game], raw, selected, pairs, expected_games=8)
    assert not summary['complete'] and not summary['training_started']


def test_same_topology_never_crosses_source_splits(tmp_path):
    games, selected = [], []
    for index, topology in enumerate(('a', 'b', 'c', 'a')):
        source = f's{index}'
        games.append(dict(source_id=source, topology=topology, stats={}))
        selected.append(dict(id=source, source_id=source, input={'query': index},
                             answer={'possible_preferences': OPTIONS}))
    summary = write_dataset(tmp_path, games, selected, selected, [], expected_games=4)
    assert summary['source_split']['s0'] == summary['source_split']['s3'] == 'train'
    assert summary['source_split']['s2'] == 'validation'
