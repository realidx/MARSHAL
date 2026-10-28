"""B-only data contract: independent focal preferences, exact set supervision.

The public prior remains finite. Focal goals vary independently of every
background row and of each other; no observed background can reveal their
values by a catalogue lookup. This does not assert causal independence after
conditioning on actions, nor robustness to a different partner policy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from itertools import product
import hashlib
import json
import random

import numpy as np

from benac_p.diagnose_protocol import submission_tool
from benac_p.b_oracle import CachedPrivateUCT
from benac_p.generator import generate_game
from benac_p.mcts_bp_audit import CELLS
from benac_p.mcts_oracle import Budget, LABELS, PrivateUCT, make_catalogues, stable_seed


VERSION = 'independent-focal-b-v1'
VALUES = (1, 0, -1)
OPTIONS = [LABELS[v] for v in VALUES]
SYSTEM = '''You are the stated learner in a native multiplayer commitment game.
Infer the named partner's preference for the queried goal from the public prior
and interaction history. Each player's own preferences belong to that player.
A goal's completion conditions do not determine who wants it. Include every
preference compatible with the declared partner policy and evidence. An initial
possibility is not a new observation. Learner actions are interventions and do
not eliminate learner types. All players' preferences are private. Background
preferences and independent focal preferences are separate random variables;
identifying a background does not by itself identify a focal preference.
Brief reasoning is allowed before submitting SUBMIT_JUDGMENT. Do not output
probabilities, utilities, Q values, or plan variables.'''


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def independent_catalogues(n_players, n_goals, seed, backgrounds=6, focal_count=2):
    if n_goals - focal_count < 3 or focal_count < 1:
        raise ValueError('Need at least one focal goal and three background goals.')
    if backgrounds < 3 or backgrounds % 3:
        raise ValueError('Background count must be a positive multiple of three.')
    rng = random.Random(stable_seed((VERSION, seed, 'focal-goals')))
    focal = tuple(tuple(sorted(rng.sample(range(n_goals), focal_count))) for _ in range(n_players))
    backgrounds_by_player = make_catalogues(n_players, n_goals - focal_count, seed, profiles=backgrounds)
    catalogues, public = [], []
    for p in range(n_players):
        other_goals = [g for g in range(n_goals) if g not in focal[p]]
        full_rows, descriptors = [], []
        for background in backgrounds_by_player[p]:
            template = [None] * n_goals
            for goal, value in zip(other_goals, background):
                template[goal] = value
            descriptors.append(template)
            for preferences in product(VALUES, repeat=focal_count):
                row = list(template)
                for goal, value in zip(focal[p], preferences):
                    row[goal] = value
                full_rows.append(tuple(row))
        assert len(set(full_rows)) == backgrounds * 3 ** focal_count
        catalogues.append(tuple(full_rows))
        public.append(dict(player_id=p, independent_goal_ids=list(focal[p]),
                           independent_goal_values=OPTIONS,
                           background_rows=descriptors,
                           distribution='Uniform independent background choice and independent uniform choice for each focal goal. null marks a focal slot, not a neutral preference.'))
    return tuple(catalogues), focal, public


def independence_certificate(catalogues, focal):
    """Exhaustively verify every background has the full focal Cartesian product."""
    checks = []
    for p, rows in enumerate(catalogues):
        groups = defaultdict(set)
        for row in rows:
            background = tuple(v for g, v in enumerate(row) if g not in focal[p])
            groups[background].add(tuple(row[g] for g in focal[p]))
        expected = set(product(VALUES, repeat=len(focal[p])))
        assert all(values == expected for values in groups.values())
        checks.append(dict(player_id=p, backgrounds=len(groups), combinations_per_background=len(expected),
                           focal_values_independent_of_background=True,
                           focal_values_mutually_independent_before_history=True))
    return checks


def make_game(seed, cell, budget=Budget(simulations=1024), backgrounds=6, focal_count=2, *, config=None):
    base = generate_game(seed, CELLS[cell] if config is None else config)
    rows, focal, public = independent_catalogues(base.n_players, base.n_goals, seed, backgrounds, focal_count)
    rng = random.Random(stable_seed((VERSION, seed, cell, 'realization')))
    actual = tuple(rng.randrange(len(r)) for r in rows)
    spec = replace(base, menu_enabled=True,
                   private_preferences=np.asarray([rows[p][t] for p, t in enumerate(actual)]),
                   metadata={'prior': VERSION})
    return spec, CachedPrivateUCT(spec, rows, budget), actual, focal, public


def payload(oracle, public_prior, node, learner, own, history, target, goal):
    game = oracle.spec.public_dict()
    game.pop('seed', None)
    return dict(game=game, learner_id=learner,
                own_preferences=list(oracle.catalogues[learner][own]),
                public_prior=public_prior,
                partner_policy=dict(version=oracle.policy_version, budget=vars(oracle.budget),
                    information='Own private row and public state/evidence-supported candidate rows only.',
                    behavior='Deterministic budgeted UCT optimizing own terminal utility, with depth limits and 75% immediate-reference / 25% exploratory continuation. All native actions are available. Learner actions are interventions.',
                    inference='At each public prefix, enumerate the acting oracle player\'s remaining rows, run this fixed policy for each row, and retain exactly those producing the observed action. Never exclude a row solely because a different policy would reject it.',
                    exact_algorithm='benac_p/mcts_oracle.py; ' + oracle.policy_version),
                history=list(history),
                state=dict(turn_index=node[1], remaining_proposers=oracle.spec.round_robin[node[1]:],
                           commitments=[[int(bool(node[0] & (1 << (oracle.offsets[p] + a))))
                                         for a in range(oracle.spec.n_actions_per_player[p])]
                                        for p in range(oracle.spec.n_players)]),
                pending_offer=None if node[2] is None else oracle.native_action((node[0], node[1], None), node[2]).offer.to_dict(),
                query=dict(player_id=target, goal_id=goal), initially_possible_preferences=OPTIONS)


def score_set(prediction, truth):
    """Validity and both directions of set error; never score just hidden truth."""
    valid = (isinstance(prediction, list) and 0 < len(prediction) <= 3
             and all(isinstance(v, str) and v in OPTIONS for v in prediction)
             and len(set(prediction)) == len(prediction))
    gold = set(truth)
    predicted = set(prediction) if valid else set()
    return dict(valid=valid, exact=valid and predicted == gold,
                false_exclusions=len(gold - predicted),
                unsupported_possibilities=len(predicted - gold),
                # An invalid output must not be rewarded for avoiding extras.
                set_error=None if not valid else len(gold ^ predicted))


def aggregate_scores(records, predictor):
    rows = [score_set(predictor(r), r['answer']['possible_preferences']) for r in records]
    n = len(rows)
    return dict(n=n, valid_rate=sum(r['valid'] for r in rows)/n if n else None,
                exact_rate=sum(r['exact'] for r in rows)/n if n else None,
                mean_false_exclusions=sum(r['false_exclusions'] for r in rows)/n if n else None,
                mean_unsupported_possibilities=sum(r['unsupported_possibilities'] for r in rows)/n if n else None)


class SamplePool:
    def __init__(self):
        self.records = {}
        self.duplicate_attempts = 0

    def add(self, source_id, input_data, answer, origin, certificate):
        # Input alone identifies a question. Contradictory answers are fatal.
        identifier = digest(input_data)
        if identifier in self.records:
            row = self.records[identifier]
            assert row['answer'] == answer, 'Identical input has contradictory B labels'
            row['origins'].append(origin)
            self.duplicate_attempts += 1
            return identifier
        self.records[identifier] = dict(id=identifier, source_id=source_id, input=input_data,
            answer=answer, label_status='exact_set_under_declared_prior_and_fixed_policy',
            origins=[origin], certificate=certificate)
        return identifier


def select_balanced(records, per_size=24):
    """Deterministic within-source quotas; retain available data without padding.

Prefer natural before/after observations, then lawful counterfactual branches.
No source game is discarded because it lacks a desired label class.
"""
    buckets = defaultdict(list)
    for row in records:
        buckets[len(row['answer']['possible_preferences'])].append(row)
    selected = []
    for size in (1, 2, 3):
        bucket = buckets[size]
        bucket.sort(key=lambda r: (not any(o['kind'] == 'natural' for o in r['origins']), r['id']))
        selected.extend(bucket[:per_size])
    return selected


def to_chat_sample(record):
    """Standard tool-call SFT interchange, not a frozen ROLL loader format.

Only the final verified tool call is a target. No unverified teacher chain of
thought is invented. Trainer must mask system/user/tool-description tokens.
"""
    tool = submission_tool(dict(kind='semantic_belief', belief_options=OPTIONS))
    messages = [dict(role='system', content=SYSTEM),
                dict(role='user', content=canonical(record['input'])),
                dict(role='assistant', content='', tool_calls=[dict(
                    id='call_judgment', type='function', function=dict(name='SUBMIT_JUDGMENT',
                        arguments=canonical(record['answer'])))])]
    return dict(id=record['id'], source_id=record['source_id'], messages=messages, tools=[tool],
                supervision='assistant_tool_call_only',
                reasoning_supervision=False)
