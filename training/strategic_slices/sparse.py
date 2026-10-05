"""Exact focal windows against an explicitly fixed, information-limited policy.

Only focal choices are expanded freely. Reference choices with zero probability
on every compatible world are omitted, and after max_k the same reference is
executed to the actual native terminal. This preserves the complete contingent
focal strategy class; it is not a depth-limited payoff approximation.
"""
import time

import numpy as np
from training.b_sft.shared_teacher import Entry, SearchLimit
from training.b_sft.social_private_teacher import observed_slots


class SparseWindow:
    def __init__(self, reference, root, ego, weights, max_k, max_nodes=30000, seconds=30):
        self.reference, self.rules = reference, reference.rules
        self.worlds = self.rules.worlds
        self.n, self.w, self.ego = self.rules.spec.n_players, len(self.worlds), ego
        self.world_weights = np.asarray(weights, dtype=float)
        if (max_k < 1 or max_nodes < 1 or seconds <= 0 or
                self.world_weights.shape != (self.w,) or
                not np.isfinite(self.world_weights).all() or
                np.any(self.world_weights < 0) or self.world_weights.sum() <= 0):
            raise ValueError('Positive budgets and compatible finite world masses required')
        if self.rules.actor(root) != ego:
            raise ValueError('Window must start at a focal decision')
        self.world_weights = self.world_weights / self.world_weights.sum()
        self.max_k, self.max_nodes = max_k, max_nodes
        self.deadline = time.monotonic() + seconds
        self.entries, self.policy, self.tail_indices = [], [], set()
        self.tail_cache = {}
        self._grow(root, 0, self.world_weights)
        # Metrics only need this attribute as a native private-tree marker;
        # partitions are recomputed from retained public histories by _groups.
        self.information_groups = {}
        self.certificate = dict(verified=True, equilibrium_verified=False,
            reference_backend='fixed-myopic-v1', terminal=True, exact_window=True,
            max_k=max_k, nodes=len(self.entries), tail_states=len(self.tail_cache),
            contract_sha256=reference.certificate['contract_sha256'],
            scope='Exact finite focal best/worst responses relative to the fixed reference, not an equilibrium certificate.')

    def _check(self):
        if time.monotonic() > self.deadline:
            raise SearchLimit('Sparse focal-window wall budget exceeded')

    def _tail(self, node, wi):
        """Memoize only a declared memoryless reference, never the focal policy."""
        self._check()
        key = (node.state.turn_index, node.state.snapshot_commitments(), node.pending,
               node.state.investigation_used,
               tuple(observed_slots(node, p) for p in range(self.n)), wi)
        if key not in self.tail_cache:
            if node.state.is_terminal:
                value = self.rules.terminal_payoffs(node, self.worlds[wi])
            else:
                ai = self.reference.action_index(node, self.worlds[wi])
                child = self.rules._apply(node, self.rules.actions(node)[ai])
                value = self._tail(child, wi)
            self.tail_cache[key] = value
        return self.tail_cache[key]

    def _grow(self, node, focal_count, masses):
        self._check()
        if len(self.entries) >= self.max_nodes:
            raise SearchLimit('Sparse focal-window node budget exceeded')
        index = len(self.entries)
        self.entries.append(None); self.policy.append(None)
        if node.state.is_terminal or focal_count >= self.max_k:
            payoff = np.asarray([self._tail(node, wi) for wi in range(self.w)])
            self.entries[index] = Entry(node, None, (), (), payoff)
            if not node.state.is_terminal:
                self.tail_indices.add(index)
            return index
        actor = self.rules.actor(node)
        legal = self.rules.actions(node)
        probs = self.reference.probabilities(node)
        if actor == self.ego:
            indices = list(range(len(legal)))
        else:
            indices = [ai for ai in range(len(legal)) if float(masses @ probs[ai]) > 0]
        actions = tuple(legal[ai] for ai in indices)
        trimmed = probs[indices].copy()
        # Impossible worlds do not affect any value. Supply a normalized
        # convention there so ordinary metric code can still integrate them.
        empty = trimmed.sum(axis=0) == 0
        trimmed[0, empty] = 1
        children = tuple(self._grow(self.rules._apply(node, legal[ai]),
            focal_count + int(actor == self.ego),
            masses if actor == self.ego else masses * probs[ai]) for ai in indices)
        self.entries[index] = Entry(node, actor, actions, children, None)
        self.policy[index] = trimmed
        return index

    def audit_native(self):
        edges = 0
        for entry in self.entries:
            for action, child in zip(entry.actions, entry.children):
                expected = self.rules._apply(entry.node, action)
                actual = self.entries[child].node
                if expected.state.public_state() != actual.state.public_state() or expected.pending != actual.pending:
                    raise AssertionError('Sparse window transition diverged from native rules')
                edges += 1
        return dict(edges=edges, nodes=len(self.entries), collapsed_reference_tails=len(self.tail_indices),
                    cached_tail_states=len(self.tail_cache), native_transitions_match=True,
                    terminal_tail='Exact fixed-reference execution; no heuristic endpoint payoff')
