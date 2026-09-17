"""Native BENAC-P endgame search and evidence accounting.

No stage catalogue, fixed interaction route, or coupled preference types. A
partner kernel is an explicit dependency, not an implicit omniscient solver.
This module makes no rationality claim about an injected kernel.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
import json
from typing import Callable

import numpy as np

from benac_p.schema import GameSpec, OfferProposal, PassProposal, ResponseAction, response_actions
from benac_p.state import GameState

VERSION = 'native-endgame-v1'
Action = OfferProposal | PassProposal | ResponseAction
World = tuple[tuple[int, ...], ...]


def fingerprint(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class PartnerDecision:
    """The ONLY inputs exposed to a partner: public state and its own row."""
    player_id: int
    public_state: dict
    own_preferences: tuple[int, ...]
    legal_actions: tuple[Action, ...]
    pending_offer: dict | None


@dataclass
class Node:
    state: GameState
    worlds: tuple[World, ...]
    pending: object = None


@dataclass
class Branch:
    weight: float
    node: Node
    evidence: tuple[dict, ...]


class SearchLimit(RuntimeError):
    pass


class Endgame:
    """Exact best response through the actual remaining round-robin schedule.

    Uniform independent finite type catalogues are expanded before any history
    conditioning. Partner actions are deterministic given their public input
    and own type. Belief changes only on observed partner actions. Ego can be
    both proposer and responder; neither decision is automatically skipped.
    """

    def __init__(self, spec: GameSpec, ego: int, own_preferences,
                 partner_types: dict[int, tuple[tuple[int, ...], ...]],
                 partner: Callable[[PartnerDecision], Action], *, max_nodes=50_000,
                 max_remaining_turns=6, markov_partner=False):
        if not 0 <= ego < spec.n_players:
            raise ValueError('Invalid ego player.')
        if len(spec.round_robin) % spec.n_players or any(
            set(spec.round_robin[i:i+spec.n_players]) != set(range(spec.n_players))
            for i in range(0, len(spec.round_robin), spec.n_players)
        ):
            raise ValueError('Each original round must give every player one proposal turn.')
        if set(partner_types) != set(range(spec.n_players)) - {ego}:
            raise ValueError('Specify an independent type catalogue for every partner.')
        own = tuple(own_preferences)
        catalogues = {p: tuple(tuple(row) for row in rows) for p, rows in partner_types.items()}
        for rows in [(own,), *catalogues.values()]:
            if not rows or len(set(rows)) != len(rows):
                raise ValueError('Type catalogues must be nonempty and unique.')
            if any(len(row) != len(spec.goals) or any(v not in (-1, 0, 1) for v in row) for row in rows):
                raise ValueError('Preference rows must match goals and use want/neutral/avoid.')
        # Do not retain the realized matrix, seed or private metadata in search.
        self.spec = replace(spec, private_preferences=np.zeros_like(spec.private_preferences),
                            seed=0, metadata={})
        self.ego, self.own, self.partner = ego, own, partner
        self.max_nodes, self.max_remaining_turns = max_nodes, max_remaining_turns
        self.markov_partner = markov_partner
        if max_nodes < 1 or max_remaining_turns < 1:
            raise ValueError('Search budgets must be positive.')
        self.worlds = tuple(product(*( (own,) if p == ego else catalogues[p]
                                     for p in range(spec.n_players))))
        self._cache = {}
        self._q_cache = {}
        self._kernel_cache = {}
        self._actions_cache = {}

    def initial(self):
        return Node(GameState(self.spec), self.worlds)

    def actor(self, node):
        if node.state.is_terminal:
            return None
        return node.pending.partner_id if node.pending is not None else node.state.current_proposer()

    def actions(self, node):
        key=(node.state.turn_index,node.state.snapshot_commitments(),node.pending)
        if key not in self._actions_cache:
            self._actions_cache[key]=response_actions(node.pending) if node.pending is not None else node.state.legal_proposals()
        return self._actions_cache[key]

    def _partner_action(self, node, world):
        player = self.actor(node)
        if player is None or player == self.ego:
            raise ValueError('Partner kernel cannot choose an ego or terminal action.')
        public = node.state.public_state()
        pending = None if node.pending is None else node.pending.to_dict()
        key_public = dict(public)
        if self.markov_partner:key_public.pop('transcript')
        key = (player, world[player], fingerprint(key_public), fingerprint(pending))
        if key not in self._kernel_cache:
            legal = self.actions(node)
            decision = PartnerDecision(player, public, world[player], legal, pending)
            action = self.partner(decision)
            if action not in legal:
                raise ValueError('Partner kernel returned an illegal native action.')
            self._kernel_cache[key] = action
        return self._kernel_cache[key]

    def _apply(self, node, action):
        if action not in self.actions(node):
            raise ValueError('Illegal action at this original-game decision.')
        state = node.state.clone()
        if node.pending is not None:
            state.resolve_offer(node.pending, action)
            pending = None
        elif isinstance(action, PassProposal):
            state.apply_pass()
            pending = None
        else:
            state.validate_offer(action.offer)
            pending = action.offer
        return Node(state, node.worlds, pending)

    def advance(self, node):
        """Enumerate public evidence until the next ego decision or termination."""
        if self.actor(node) in (None, self.ego):
            return (Branch(1., node, ()),)
        groups = {}
        for world in node.worlds:
            action = self._partner_action(node, world)
            groups.setdefault(action, []).append(world)
        result = []
        for action, worlds in groups.items():
            conditional = Node(node.state, tuple(worlds), node.pending)
            event = dict(turn_index=node.state.turn_index, player_id=self.actor(node),
                         action=action.to_dict())
            child = self._apply(conditional, action)
            for branch in self.advance(child):
                result.append(Branch(len(worlds)/len(node.worlds)*branch.weight,
                                     branch.node, (event,)+branch.evidence))
        return tuple(result)

    def step(self, node, action):
        if self.actor(node) != self.ego:
            raise ValueError('An intervention requires an ego decision.')
        # The chosen ego action is do(a), never evidence about hidden types.
        return self.advance(self._apply(node, action))

    def utility(self, node):
        if not node.state.is_terminal:
            raise ValueError('Only actual terminal utility is scored.')
        return float(np.dot(self.own, node.state.goal_satisfaction()))

    def _key(self, node):
        return (node.state.turn_index,node.state.snapshot_commitments(),node.pending,node.worlds,
                None if self.markov_partner else fingerprint([e.to_dict() for e in node.state.transcript]))

    def value(self, node):
        if not node.worlds:
            raise ValueError('Empty belief support.')
        if len(self.spec.round_robin)-node.state.turn_index > self.max_remaining_turns:
            raise SearchLimit('Not an endgame within the exact remaining-turn budget.')
        if node.state.is_terminal:
            return self.utility(node)
        key = self._key(node)
        if key not in self._cache:
            if len(self._cache) >= self.max_nodes:
                raise SearchLimit('Exact node budget exceeded; no approximate label returned.')
            self._cache[key] = None
            try:
                if self.actor(node) == self.ego:
                    value = max(v for _, v in self.q_values(node))
                else:
                    value = sum(b.weight*self.value(b.node) for b in self.advance(node))
                self._cache[key] = value
            except Exception:
                del self._cache[key]
                raise
        return self._cache[key]

    def q_values(self, node):
        if self.actor(node) != self.ego:
            raise ValueError('Action labels require an ego decision.')
        if len(self.spec.round_robin)-node.state.turn_index > self.max_remaining_turns:
            raise SearchLimit('Too many original proposal turns remain.')
        key = self._key(node)
        if key in self._q_cache:
            return self._q_cache[key]
        values = tuple((a, sum(b.weight*self.value(b.node) for b in self.step(node, a)))
                       for a in self.actions(node))
        if len(self._q_cache) < self.max_nodes:
            self._q_cache[key] = values
        return values

    def replay(self, actions):
        """Replay an explicit full public prefix from zero commitments.

        Each proposal and response is a separate action. Ego choices are legal
        interventions; every partner choice must match the declared kernel in
        at least one remaining world. No posterior-inconsistent prefix passes.
        """
        node = self.initial()
        for action in actions:
            actor = self.actor(node)
            if actor is None:
                raise ValueError('History continues after termination.')
            if actor != self.ego:
                worlds = tuple(w for w in node.worlds if self._partner_action(node, w) == action)
                if not worlds:
                    raise ValueError('History is inconsistent with the partner mechanism and prior.')
                node = Node(node.state, worlds, node.pending)
            node = self._apply(node, action)
        return node

    @staticmethod
    def possible_preferences(node, player, goal):
        labels = {1: 'want', 0: 'neutral', -1: 'avoid'}
        return [labels[v] for v in (1, 0, -1) if any(w[player][goal] == v for w in node.worlds)]
