"""Isolated native-game OFFER-quota research; not connected to training.

Only new physical rule: an OFFER immediately consumes the proposer's quota.
Investigation, goals, scoring, complete native offers and responses are retained.
"""
from copy import copy, deepcopy
from itertools import product
import time

import numpy as np

from training.b_sft.social_private_teacher import (
    PrivateInvestigationRules, PrivateState, observed_slots,
)
from training.b_sft.social_terminal_teacher import Investigate
from training.b_sft.shared_teacher import TOL
from training.b_sft.decision_policy import optimal_indices
from training.b_sft.preference_contract import profile
from training.strategic_slices.oracle_consistent import oracle_reach
from benac_p.endgame import Node
from benac_p.schema import OfferProposal

VERSION = 'native-offer-quota-research-v2'


class OfferQuotaState(PrivateState):
    def __init__(self, spec, limit):
        super().__init__(spec)
        self.offer_limit = limit
        self.offer_used = (0,) * spec.n_players

    def public_state(self):
        return dict(super().public_state(),
            offer_limit_per_player=self.offer_limit,
            offer_used_by_player=list(self.offer_used),
            offer_remaining_by_player=(None if self.offer_limit is None else
                [self.offer_limit - n for n in self.offer_used]),
            offer_quota_scope='per player per game; charged when proposed; never refunded')


class OfferQuotaRules(PrivateInvestigationRules):
    def __init__(self, raw, limit):
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError('Nonnegative integer quota or None required')
        super().__init__(raw)
        self.limit = limit

    def initial(self):
        return Node(OfferQuotaState(self.spec, self.limit), self.worlds)

    def public_game(self):
        return dict(super().public_game(), variant=VERSION,
            offer_quota=dict(limit=self.limit, scope='per player per game',
                charged='Immediately when OFFER creates a pending offer, before response',
                refunds='Never, on either ACCEPT or REJECT',
                exhausted='No new OFFER; PASS, unused INVESTIGATE and all legal responses remain',
                utility_penalty=0, shared_quota=False))

    def actions(self, node):
        actions = super().actions(node)
        actor = self.actor(node)
        if (actor is not None and node.pending is None and self.limit is not None
                and node.state.offer_used[actor] >= self.limit):
            return tuple(a for a in actions if not isinstance(a, OfferProposal))
        return actions

    def _apply(self, node, action):
        # Enforce the quota here as well as in enumeration: direct step calls
        # must not bypass legality by reaching the unrestricted native engine.
        if action not in self.actions(node):
            raise ValueError('Illegal action under the OFFER quota')
        child = super()._apply(node, action)
        if isinstance(action, OfferProposal):
            actor = self.actor(node)
            child.state.offer_used = tuple(n + int(p == actor)
                for p, n in enumerate(node.state.offer_used))
        return child


def assert_factorized(raw):
    """Require Cartesian support across goals, then product prior weights.

    Fixed public cells are allowed. No logical/dependent preference mechanism
    is introduced by the research parent selection.
    """
    facts = {}
    for p, rows in raw['type_catalogues'].items():
        support = [sorted({row[g] for row in rows}) for g in range(len(rows[0]))]
        expected = {tuple(r) for r in product(*support)}
        if {tuple(row) for row in rows} != expected:
            raise ValueError('Dependent preference support excluded from this diagnostic')
        facts[p] = support
    return facts


def small_parents():
    # Convenience controls, not new training examples or a generator yield
    # estimate. Within each parent, quota is the only varying physical rule.
    goals = [dict(goal_id=0, binary=True,
                  required_actions=[dict(player_id=0, action_id=0),
                                    dict(player_id=1, action_id=0)]),
             dict(goal_id=1, binary=True,
                  required_actions=[dict(player_id=0, action_id=1),
                                    dict(player_id=1, action_id=0)]),
             dict(goal_id=2, binary=True,
                  required_actions=[dict(player_id=0, action_id=0),
                                    dict(player_id=0, action_id=1),
                                    dict(player_id=1, action_id=0)])]
    for i, own in enumerate(((1, 1, -1), (1, -1, 1), (-1, 1, 1))):
        for slot in (0, 1):
            base = [1, 1, -1]
            rows = [base[:slot] + [v] + base[slot+1:] for v in (-1, 0, 1)]
            raw = dict(game=dict(n_players=2, n_actions_per_player=[2, 1],
                    goals=deepcopy(goals), round_robin=[0, 1, 0, 1],
                    max_changes=1, menu_enabled=False),
                ego=0, own_preferences=list(own),
                type_catalogues={'0': [list(own)], '1': rows},
                background_prior=profile('balanced'), history=[])
            assert_factorized(raw)
            yield f'compact_{i}_slot_{slot}', raw


def contingent_values(tree, ego, *, forbid_queries=False, masked_slot=None):
    """Full remaining vector best response against the SAME partner profile.

    Response social ties use full final payoff vectors. Proposal ties retain
    all own-optimal choices uniformly, matching the reference BR convention.
    Masking removes one query answer from all future focal information cells;
    physical query, costs, prior and partner policy remain unchanged.
    """
    reach = [None] * len(tree.entries)
    reach[0] = tree.world_weights.copy()
    for i, entry in enumerate(tree.entries):
        for a, child in enumerate(entry.children):
            reach[child] = reach[i] if entry.actor == ego else reach[i] * tree.policy[i][a]
    values = [None] * len(tree.entries)
    for i in reversed(range(len(tree.entries))):
        if i % 256 == 0:
            tree._check()
        entry = tree.entries[i]
        if entry.actor is None:
            values[i] = entry.payoff
            continue
        av = np.stack([values[ch] for ch in entry.children])
        if entry.actor != ego:
            values[i] = np.einsum('aw,awp->wp', tree.policy[i], av)
            continue
        allowed = [a for a, action in enumerate(entry.actions)
                   if not forbid_queries or not isinstance(action, Investigate)]
        if not allowed:
            raise AssertionError('PASS/response should remain legal')
        groups = tree.information_groups[i]
        if masked_slot is not None:
            slots = [s for s in observed_slots(entry.node, ego) if s != masked_slot]
            grouped = {}
            for wi, world in enumerate(tree.worlds):
                key = world[ego], tuple(world[p][g] for p, g in slots)
                grouped.setdefault(key, []).append(wi)
            groups = [np.array(ids, dtype=int) for ids in grouped.values()]
        values[i] = np.zeros((tree.w, tree.n))
        for ids in groups:
            weights = reach[i][ids]
            if weights.sum() == 0:
                weights = tree.world_weights[ids]
            means = np.einsum('awp,w->ap', av[:, ids], weights / weights.sum())
            selected = optimal_indices(means[allowed], ego,
                                       tuple(entry.actions[a] for a in allowed), TOL)
            choices = [allowed[int(a)] for a in selected]
            values[i][ids] = av[np.ix_(choices, ids)].mean(axis=0)
    return values


def measure(tree):
    reach, histories = oracle_reach(tree)
    rows = []
    for ego in range(tree.n):
        tree.deadline = time.monotonic() + 120
        first = list(tree.rules.spec.round_robin).index(ego)
        full = contingent_values(tree, ego)
        forbidden = contingent_values(tree, ego, forbid_queries=True)
        # Independent diagnostic implementation must agree with the reference
        # full-vector BR including its response tie objective.
        _, independent = tree.response(ego)
        np.testing.assert_allclose(full[0], independent, atol=1e-9, rtol=0)
        masks = {}
        for i, mass_by_world in reach.items():
            entry = tree.entries[i]
            if (entry.actor != ego or entry.node.pending is not None
                    or entry.node.state.turn_index != first):
                continue
            queries = [a for a, act in enumerate(entry.actions) if isinstance(act, Investigate)]
            ordinary = [a for a in range(len(entry.actions)) if a not in queries]
            if not queries:
                continue
            for ids in tree.information_groups[i]:
                mass = float(mass_by_world[ids].sum())
                if mass <= 1e-10:
                    continue
                weights = np.zeros(tree.w)
                weights[ids] = mass_by_world[ids] / mass
                q = np.array([weights @ full[c][:, ego] for c in entry.children])
                nq = np.array([weights @ forbidden[c][:, ego] for c in entry.children])
                query_best, other_best = float(q[queries].max()), float(q[ordinary].max())
                v, no_queries = float(q.max()), float(nq[ordinary].max())
                assert no_queries <= v + 1e-8
                frozen = float(weights @ tree.values[i][:, ego])
                assert abs(v - frozen) <= 1e-8
                details = []
                for a in queries:
                    action = entry.actions[a]
                    slot = action.player, action.goal
                    support = sorted({tree.worlds[wi][slot[0]][slot[1]]
                                      for wi in np.flatnonzero(weights > 0)})
                    item = dict(action_index=a, slot=list(slot), support=support, Q=float(q[a]))
                    # Measure every informative best query, including ties and
                    # inferior queries, rather than screening on positive gap.
                    if len(support) > 1 and q[a] >= query_best - 1e-8:
                        if slot not in masks:
                            masks[slot] = contingent_values(tree, ego, masked_slot=slot)
                        masked_q = float(weights @ masks[slot][entry.children[a]][:, ego])
                        item.update(masked_same_query_Q=masked_q,
                                    same_query_answer_value=float(q[a]) - masked_q)
                    details.append(item)
                rows.append(dict(player=ego, root_index=i, history=histories[i],
                    own=list(tree.worlds[int(ids[0])][ego]), reach_mass=mass,
                    offer_used=list(entry.node.state.offer_used),
                    actions=[a.to_dict() for a in entry.actions], Q=q.tolist(),
                    V_full=v, V_no_own_queries=no_queries, query_access_value=v-no_queries,
                    best_query_Q=query_best, best_nonquery_Q=other_best,
                    first_query_gap=query_best-other_best,
                    query_probability=float(sum(weights @ tree.policy[i][a] for a in queries)),
                    best_query_indices=[a for a in queries if q[a] >= query_best-1e-8],
                    best_nonquery_indices=[a for a in ordinary if q[a] >= other_best-1e-8],
                    query_details=details))
    return rows


def audit_quota(tree):
    """Check counts from complete histories and every timing-sensitive edge."""
    offer_edges = response_edges = query_edges = 0
    for entry in tree.entries:
        prior_offers = [0] * tree.n
        for event in entry.node.state.transcript:
            if event.to_dict()['action'] == 'OFFER':
                prior_offers[event.proposer_id] += 1
        if entry.node.pending is not None:
            prior_offers[entry.node.state.current_proposer()] += 1
        assert tuple(prior_offers) == entry.node.state.offer_used
        if tree.rules.limit is not None:
            assert max(prior_offers) <= tree.rules.limit
        for action, ci in zip(entry.actions, entry.children):
            child = tree.entries[ci].node
            expected = list(prior_offers)
            if isinstance(action, OfferProposal):
                expected[entry.actor] += 1
                assert child.pending is not None
                assert child.state.turn_index == entry.node.state.turn_index
                offer_edges += 1
            elif entry.node.pending is not None:
                assert child.pending is None
                response_edges += 1
            elif isinstance(action, Investigate):
                assert child.state.turn_index == entry.node.state.turn_index + 1
                assert child.state.snapshot_commitments() == entry.node.state.snapshot_commitments()
                query_edges += 1
            assert tuple(expected) == child.state.offer_used
    return dict(verified=True, nodes_checked=len(tree.entries),
                offer_edges=offer_edges, response_edges=response_edges, query_edges=query_edges,
                charged_before_response=True, no_accept_or_reject_refund=True,
                no_responder_charge=True, investigation_unchanged=True)


def one_round_control(raw):
    short = deepcopy(raw)
    short['game']['round_robin'] = list(raw['game']['round_robin'][:raw['game']['n_players']])
    free, quota = OfferQuotaRules(short, None), OfferQuotaRules(short, 1)
    stack = [(free.initial(), quota.initial())]
    nodes = 0
    while stack:
        a, b = stack.pop()
        assert free.actions(a) == quota.actions(b)
        assert a.pending == b.pending
        assert a.state.snapshot_commitments() == b.state.snapshot_commitments()
        assert a.state.investigation_used == b.state.investigation_used
        nodes += 1
        for action in free.actions(a):
            stack.append((free._apply(a, action), quota._apply(b, action)))
    return dict(verified=True, public_nodes=nodes,
                result='Quota 1 removes no action in one RR; same game except redundant public quota metadata')
