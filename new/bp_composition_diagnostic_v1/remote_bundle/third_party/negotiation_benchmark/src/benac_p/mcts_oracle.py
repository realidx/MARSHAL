"""Reproducible, information-limited UCT candidate for B/P data audits.

Finite independent public type catalogues, not the native preference prior.
Search optimizes own terminal utility against a declared cheap continuation;
it is neither exact best response nor an equilibrium solver. No realized
private preferences are accepted by this module's policy interface.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations
import hashlib
import json
import math
import random
import time

import numpy as np

from benac_p.schema import MenuOffer, Offer, OfferProposal, PassProposal, ResponseAction


VERSION = 'finite-private-uct-v1'
LABELS = {-1: 'avoid', 0: 'neutral', 1: 'want'}


def stable_seed(value):
    return int.from_bytes(hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()[:8], 'big')


@dataclass(frozen=True)
class Budget:
    simulations: int = 512
    tree_ego_depth: int = 3
    tree_phase_depth: int = 12
    exploration: float = 1.4
    rollout_exploration: float = 0.25
    salt: int = 0

    def __post_init__(self):
        if min(self.simulations, self.tree_ego_depth, self.tree_phase_depth) < 1:
            raise ValueError('Search budgets must be positive.')
        if self.exploration < 0 or not 0 <= self.rollout_exploration <= 1:
            raise ValueError('Invalid exploration settings.')


def make_catalogues(n_players, n_goals, seed, profiles=6):
    """Public prior generated BEFORE independently drawing realized types.

Each triplet is a cyclic ternary rotation: every goal has all three values.
This deliberately restricted within-player prior is explicit in every sample.
"""
    if profiles < 3 or profiles % 3:
        raise ValueError('profiles must be a positive multiple of three')
    rng = random.Random(stable_seed((VERSION, 'catalogues', seed)))
    result = []
    for _ in range(n_players):
        rows = []
        while len(rows) < profiles:
            base = [rng.randrange(3) for _ in range(n_goals)]
            additions = [tuple((x + shift) % 3 - 1 for x in base) for shift in range(3)]
            if any(row in rows or 1 not in row for row in additions):
                continue
            rows.extend(additions)
        result.append(tuple(rows))
    return tuple(result)


class PrivateUCT:
    """Compact native transitions, root-player information-history UCT.

Other simulated players use only their sampled OWN type and public domains.
Their continuation is immediate expected improvement, with a declared random
exploration mixture. The root player's later tree nodes share statistics over
hidden worlds with the same observed action history (no per-world maximization).
Actual partners run this UCT afresh, so search-continuation mismatch is explicit.
"""
    def __init__(self, spec, catalogues, budget=Budget()):
        if spec.max_changes != 1 or spec.forbidden_actions is not None:
            raise ValueError('This audit adapter supports max_changes=1 and no forbidden actions.')
        self.spec = replace(spec, private_preferences=np.zeros_like(spec.private_preferences), seed=0, metadata={})
        self.catalogues = tuple(tuple(tuple(map(int, row)) for row in rows) for rows in catalogues)
        if len(self.catalogues) != spec.n_players or any(
            not rows or len(set(rows)) != len(rows) or any(len(row) != spec.n_goals for row in rows)
            for rows in self.catalogues
        ):
            raise ValueError('Invalid public catalogues')
        self.budget = budget
        self.offsets = tuple(sum(spec.n_actions_per_player[:p]) for p in range(spec.n_players))
        self.bits = sum(spec.n_actions_per_player)
        if self.bits > 16:
            raise ValueError('Compact utility table limited to 16 commitment bits for this audit.')
        self.full_mask = (1 << self.bits) - 1
        goal_masks = np.array([sum(1 << (self.offsets[a.player_id] + a.action_id)
                                   for a in goal.required_actions) for goal in spec.goals])
        masks = np.arange(1 << self.bits)
        satisfaction = ((masks[:, None] & goal_masks) == goal_masks).astype(np.int16)
        # Integer-scaled rewards preserve exact comparisons for partial goals.
        # ALL_OF-only games retain the original scale/table/behavior.
        self.utility_scale = math.lcm(*(len(g.required_actions) for g in spec.goals if not g.binary))
        if self.utility_scale > 1:
            satisfaction = satisfaction.astype(np.int64) * self.utility_scale
            for g in spec.goals:
                if not g.binary:
                    met = sum(((masks >> (self.offsets[a.player_id] + a.action_id)) & 1)
                              for a in g.required_actions)
                    satisfaction[:, g.goal_id] = met * (self.utility_scale // len(g.required_actions))
        self.policy_version = 'finite-private-uct-linear-v2' if any(not g.binary for g in spec.goals) else VERSION
        self.utilities = tuple(np.asarray(rows, dtype=np.int16) @ satisfaction.T for rows in self.catalogues)
        self.search_cache = {}
        self.search_calls = 0
        self.search_seconds = 0.0

    @property
    def prior(self):
        return tuple(tuple(range(len(rows))) for rows in self.catalogues)

    def actor(self, node):
        _, turn, pending = node
        return self.spec.round_robin[turn] if pending is None else pending[0]

    def terminal(self, node):
        return node[1] >= len(self.spec.round_robin)

    @lru_cache(maxsize=32768)
    def actions(self, node):
        mask, turn, pending = node
        if self.terminal(node):
            return ()
        if pending is not None:
            return (0, 1, 2) if pending[2] else (0, 1)
        proposer = self.spec.round_robin[turn]
        own = [0] + [1 << (self.offsets[proposer] + a) for a in range(self.spec.n_actions_per_player[proposer])
                     if not mask & (1 << (self.offsets[proposer] + a))]
        result = [(-1, 0, 0)]
        for partner in range(self.spec.n_players):
            if partner == proposer:
                continue
            other = [0] + [1 << (self.offsets[partner] + a) for a in range(self.spec.n_actions_per_player[partner])
                           if not mask & (1 << (self.offsets[partner] + a))]
            offers = [a | b for a in own for b in other if a | b]
            result.extend((partner, offer, 0) for offer in offers)
            if self.spec.menu_enabled:
                result.extend((partner, first, second) for first, second in combinations(offers, 2))
        return tuple(result)

    def step(self, node, action):
        mask, turn, pending = node
        if pending is not None:
            return mask | (pending[action] if action else 0), turn + 1, None
        if action[0] == -1:
            return mask, turn + 1, None
        return mask, turn, action

    def native_action(self, node, action):
        mask, turn, pending = node
        if pending is not None:
            return ResponseAction(('REJECT', 'CHOOSE_1', 'CHOOSE_2')[action] if pending[2]
                                  else ('REJECT', 'ACCEPT')[action])
        if action[0] == -1:
            return PassProposal()
        proposer, partner = self.spec.round_robin[turn], action[0]
        def offer(delta):
            target = mask | delta
            row = lambda p: tuple(int(bool(target & (1 << (self.offsets[p] + a))))
                                  for a in range(self.spec.n_actions_per_player[p]))
            return Offer(partner, row(proposer), row(partner))
        return OfferProposal(MenuOffer((offer(action[1]), offer(action[2]))) if action[2]
                             else offer(action[1]))

    @lru_cache(maxsize=65536)
    def reference(self, node, own_type, domains):
        """Public-domain expected immediate utility; REJECT/PASS win ties.

The greedy proposal component considers ordinary offers. The random mixture
has full native action support, including menus, and can unlock delayed goals.
No other player's realized type is an input to this reference action.
"""
        actor = self.actor(node)
        mask, _, pending = node
        actions = self.actions(node)
        own_u = self.utilities[actor][own_type]
        if pending is not None:
            return max(actions, key=lambda a: int(own_u[self.step(node, a)[0]]))
        best, best_delta = actions[0], 0.0
        for action in actions[1:]:
            partner, delta, second = action
            if second:
                continue
            child = mask | delta
            gain = int(own_u[child]) - int(own_u[mask])
            if gain <= best_delta:
                continue
            partner_u = self.utilities[partner]
            acceptance = sum(partner_u[t, child] > partner_u[t, mask] for t in domains[partner]) / len(domains[partner])
            score = gain * acceptance
            if score > best_delta:
                best, best_delta = action, score
        return best

    def rollout_action(self, node, own_type, domains, rng):
        if rng.random() >= self.budget.rollout_exploration:
            return self.reference(node, own_type, domains)
        actions = self.actions(node)
        if node[2] is not None:
            return rng.choice(actions)
        # Sample categories first so quadratic menu enumeration does not dominate.
        groups = [[a for a in actions if a[0] == -1],
                  [a for a in actions if a[0] != -1 and not a[2]],
                  [a for a in actions if a[2]]]
        return rng.choice(rng.choice([g for g in groups if g]))

    def rollout_return(self, node, world, domains, ego, rng):
        while not self.terminal(node) and node[0] != self.full_mask:
            actor = self.actor(node)
            action = self.rollout_action(node, world[actor], domains, rng)
            node = self.step(node, action)
        return float(self.utilities[ego][world[ego], node[0]]) / self.utility_scale

    def search(self, node, ego, own_type, domains, *, budget=None):
        budget = budget or self.budget
        if self.actor(node) != ego or any(not d for d in domains):
            raise ValueError('Invalid root actor or empty domains')
        key = (node, ego, own_type, domains, budget)
        if key in self.search_cache:
            return self.search_cache[key]
        start = time.perf_counter()
        # Same random stream across private types: no arbitrary type-dependent seed.
        rng = random.Random(stable_seed((VERSION, node, ego, domains, budget.salt)))
        root_actions = self.actions(node)
        tree = {}
        value_scale = max(1, self.spec.n_goals) * self.utility_scale
        for _ in range(budget.simulations):
            world = [rng.choice(d) for d in domains]
            world[ego] = own_type
            current, path, visited, ego_depth, phases = node, (), [], 0, 0
            while not self.terminal(current) and current[0] != self.full_mask:
                actor = self.actor(current)
                if actor == ego and ego_depth < budget.tree_ego_depth and phases < budget.tree_phase_depth:
                    if path not in tree:
                        acts = self.actions(current)
                        order = list(range(len(acts)))
                        rng.shuffle(order)
                        tree[path] = [acts, [0] * len(acts), [0.0] * len(acts), order]
                    acts, counts, totals, order = tree[path]
                    if order:
                        index = order.pop()
                    else:
                        log_n = math.log(sum(counts) + 1)
                        index = max(range(len(acts)), key=lambda j: totals[j] / counts[j] / value_scale
                                    + budget.exploration * math.sqrt(log_n / counts[j]))
                    action = acts[index]
                    visited.append((counts, totals, index))
                    ego_depth += 1
                else:
                    action = self.rollout_action(current, world[actor], domains, rng)
                path += ((actor, action),)
                current = self.step(current, action)
                phases += 1
            value = float(self.utilities[ego][own_type, current[0]])
            for counts, totals, index in visited:
                counts[index] += 1
                totals[index] += value
        if () in tree:
            _, counts, totals, _ = tree[()]
        else:
            # All commitments already bound; every remaining legal action is PASS.
            counts, totals = [budget.simulations], [budget.simulations * float(self.utilities[ego][own_type, node[0]])]
        chosen = max(range(len(root_actions)), key=lambda j: (counts[j], totals[j] / max(1, counts[j]), -j))
        result = dict(action=root_actions[chosen], actions=root_actions, counts=tuple(counts),
                      means=tuple(t / c / self.utility_scale if c else None for t, c in zip(totals, counts)),
                      root_action_coverage=sum(c > 0 for c in counts) / len(counts),
                      tree_nodes=len(tree), seconds=time.perf_counter() - start)
        self.search_cache[key] = result
        self.search_calls += 1
        self.search_seconds += result['seconds']
        return result

    def update(self, node, observed_action, domains, learner):
        """Exact likelihood support for THIS deterministic finite-type policy.

At any fixed public prefix each actor's policy depends only on own type and
the public domains. Thus likelihood factors by player; exhaustive per-row
checks preserve the exact Cartesian support without joint-world enumeration.
Learner actions remain interventions. This proves support, not optimality.
"""
        actor = self.actor(node)
        if actor == learner:
            return domains
        kept = tuple(t for t in domains[actor]
                     if self.search(node, actor, t, domains)['action'] == observed_action)
        if not kept:
            raise ValueError('Observed action impossible under declared candidate oracle')
        return tuple(kept if p == actor else d for p, d in enumerate(domains))

    def semantic_support(self, domains, player, goal):
        return [LABELS[v] for v in (1, 0, -1)
                if any(self.catalogues[player][t][goal] == v for t in domains[player])]

    def clear_caches(self):
        self.actions.cache_clear()
        self.reference.cache_clear()
        self.search_cache.clear()
