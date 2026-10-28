"""Vectorized candidate search on an unmerged history tree.

The original scalar best-response and local-information audits still certify
all accepted profiles independently. These batches group array operations,
not histories, beliefs, or strategies.
"""
import numpy as np
from training.b_sft.decision_policy import is_offer_response
from training.b_sft.shared_teacher import TOL


class BatchedResponse:
    def __init__(self, tree):
        self.tree = tree
        depth = {0: 0}; groups = {}
        self.leaves = []
        for i, entry in enumerate(tree.entries):
            if i % 256 == 0:
                tree._check()
            for child in entry.children:
                depth[child] = depth[i] + 1
            if entry.actor is None:
                self.leaves.append(i)
                continue
            partition = tuple(tuple(ids) for ids in tree.information_groups[i])
            key = (depth[i], entry.actor, len(entry.actions), is_offer_response(entry.actions), partition)
            groups.setdefault(key, []).append(i)
        self.layers = []
        for key in sorted(groups, key=lambda k: k[:4]):
            ids = np.array(groups[key])
            children = np.array([tree.entries[i].children for i in ids])
            self.layers.append((ids, children, key[1], key[3], [np.array(g) for g in key[4]]))
        self.leaves = np.array(self.leaves)
        self.payoffs = np.stack([tree.entries[i].payoff for i in self.leaves])

    def locally_admissible(self, epsilon=1e-8, require_social_ties=True):
        """Cheap rejection only; acceptance always uses independent scalar audits.

        No histories or information cells are merged. A numerical guard makes
        this screen conservative near the scalar test's tolerance boundaries.
        """
        tree = self.tree
        policies = [np.stack([tree.policy[i] for i in ids])
                    for ids, _, _, _, _ in self.layers]
        values = np.empty((len(tree.entries), tree.w, tree.n))
        values[self.leaves] = self.payoffs
        for (ids, children, _, _, _), probabilities in reversed(list(zip(self.layers, policies))):
            tree._check()
            values[ids] = np.einsum('baw,bawp->bwp', probabilities, values[children])
        guard = 1e-10
        for player in range(tree.n):
            reach = np.zeros((len(tree.entries), tree.w)); reach[0] = tree.world_weights
            for (ids, children, actor, _, _), probabilities in zip(self.layers, policies):
                tree._check()
                reach[children] = reach[ids, None, :] * (1. if actor == player else probabilities)
            for (ids, children, actor, response, groups), probabilities in zip(self.layers, policies):
                if actor != player:
                    continue
                tree._check()
                av = values[children]
                for worlds in groups:
                    masses = reach[np.ix_(ids, worlds)].copy()
                    zero = masses.sum(axis=1) == 0
                    masses[zero] = tree.world_weights[worlds]
                    masses /= masses.sum(axis=1)[:, None]
                    means = np.einsum('bawp,bw->bap', av[:, :, worlds], masses)
                    if not np.isfinite(means).all():
                        return False
                    own = means[:, :, player]
                    support = probabilities[:, :, worlds[0]] > TOL
                    best = own.max(axis=1)
                    worst_supported = np.where(support, own, np.inf).min(axis=1)
                    if np.any(best - worst_supported > epsilon + guard):
                        return False
                    if response and require_social_ties:
                        # Exclude rows close to the own-value tie boundary;
                        # the independent scalar audit decides these cases.
                        gaps = best[:, None] - own
                        ambiguous = np.any((gaps > TOL-guard) & (gaps < TOL+guard), axis=1)
                        tied = gaps <= TOL
                        others = means.sum(axis=2) - own
                        other_best = np.where(tied, others, -np.inf).max(axis=1)
                        rejected = tied & (other_best[:, None] - others > TOL+guard)
                        bad_mass = np.sum(np.where(rejected, probabilities[:, :, worlds[0]], 0.), axis=1)
                        if np.any((bad_mass > TOL+guard) & ~ambiguous):
                            return False
        return True

    def response(self, player):
        tree = self.tree
        reach = np.zeros((len(tree.entries), tree.w)); reach[0] = tree.world_weights
        policies = []
        for ids, children, actor, _, _ in self.layers:
            tree._check()
            p = np.stack([tree.policy[i] for i in ids]); policies.append(p)
            reach[children] = reach[ids, None, :] * (1. if actor == player else p)
        values = np.empty((len(tree.entries), tree.w, tree.n))
        values[self.leaves] = self.payoffs
        updates = {}
        for (ids, children, actor, response, groups), p in reversed(list(zip(self.layers, policies))):
            tree._check()
            av = values[children]
            if actor == player:
                p = np.zeros_like(p)
                for worlds in groups:
                    masses = reach[np.ix_(ids, worlds)].copy()
                    zero = masses.sum(axis=1) == 0
                    masses[zero] = tree.world_weights[worlds]
                    masses /= masses.sum(axis=1)[:, None]
                    means = np.einsum('bawp,bw->bap', av[:, :, worlds], masses)
                    own = means[:, :, player]
                    best = own >= own.max(axis=1)[:, None] - TOL
                    if response:
                        others = means.sum(axis=2) - own
                        best &= others >= np.where(best, others, -np.inf).max(axis=1)[:, None] - TOL
                    probs = best / best.sum(axis=1)[:, None]
                    p[:, :, worlds] = probs[:, :, None]
                updates.update((int(i), probabilities) for i, probabilities in zip(ids, p))
            values[ids] = np.einsum('baw,bawp->bwp', p, av)
        return updates, values[0]
