"""Finite-window reference with uniform mixing over all residual best-response ties.

Reuses SharedWindow's native public tree and private-information grouping. No
single random rollout supplies inverse evidence: continuation values integrate
all actions in the reference policy. As before, non-convergence gives no label.
"""
import numpy as np

from training.social_mixed.frozen.training.b_sft.shared_teacher import SharedWindow, SearchLimit, TOL


def normalized_weights(weights, size):
    """Positive mass for every supported world; never silently drop a type."""
    result = np.array(weights, dtype=float, copy=True)
    if result.shape != (size,) or not np.all(np.isfinite(result)) or np.any(result <= 0):
        raise ValueError('Every supported world requires a finite positive weight')
    result /= result.max()
    result /= result.sum()
    if np.any(result <= 0):
        raise ValueError('World-weight underflow; no posterior or label')
    return result


class RandomTieWindow(SharedWindow):
    def __init__(self, *args, world_weights=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.world_weights = normalized_weights(
            np.ones(self.w) if world_weights is None else world_weights, self.w)
        # Order-independent initial reference; this is not an executable policy
        # until solve() certifies a stable best response for every private type.
        self.policy = [None if e.actor is None else
                       np.full((len(e.actions), self.w), 1 / len(e.actions))
                       for e in self.entries]

    def evaluate(self, policy=None):
        policy = self.policy if policy is None else policy
        values = [None] * len(self.entries)
        for i in reversed(range(len(self.entries))):
            if i % 256 == 0: self._check()
            e = self.entries[i]
            values[i] = e.payoff if e.actor is None else np.einsum(
                'aw,awp->wp', policy[i], np.stack([values[c] for c in e.children]))
        return values

    def response(self, player):
        reach = [None] * len(self.entries)
        reach[0] = self.world_weights.copy()
        for i, e in enumerate(self.entries):
            if i % 256 == 0: self._check()
            for a, child in enumerate(e.children):
                reach[child] = reach[i] if e.actor == player else reach[i] * self.policy[i][a]
        values = [None] * len(self.entries)
        updates = {}
        for i in reversed(range(len(self.entries))):
            if i % 256 == 0: self._check()
            e = self.entries[i]
            if e.actor is None:
                values[i] = e.payoff
                continue
            av = np.stack([values[c] for c in e.children])
            if e.actor != player:
                values[i] = np.einsum('aw,awp->wp', self.policy[i], av)
                continue
            probs = np.zeros((len(e.actions), self.w))
            for ids in self.groups[player]:
                weights = reach[i][ids]
                # Off-path reference only. Actual zero-likelihood observations
                # are rejected by BeliefOracle; they never reset its posterior.
                if weights.sum() == 0: weights = self.world_weights[ids]
                means = np.einsum('awp,w->ap', av[:, ids, :], weights / weights.sum())
                own = means[:, player]
                others = means.sum(axis=1) - own
                first = np.flatnonzero(own >= own.max() - TOL)
                final = first[others[first] >= others[first].max() - TOL]
                probs[np.ix_(final, ids)] = 1 / len(final)
            updates[i] = probs
            values[i] = np.einsum('aw,awp->wp', probs, av)
        return updates, values[0]

    def solve(self):
        seen = set()
        for sweep in range(self.max_sweeps):
            self._check()
            changed = False
            for p in range(self.n):
                updates, _ = self.response(p)
                for i, new in updates.items():
                    changed |= not np.array_equal(self.policy[i], new)
                    self.policy[i] = new
            values = self.evaluate()
            checks = []
            valid = True
            for p in range(self.n):
                _, br = self.response(p)
                for ids in self.groups[p]:
                    weights = self.world_weights[ids]
                    base = np.average(values[0][ids], axis=0, weights=weights)
                    alternative = np.average(br[ids], axis=0, weights=weights)
                    own = float(alternative[p] - base[p])
                    social = float((alternative.sum()-alternative[p]) - (base.sum()-base[p]))
                    if own > TOL or abs(own) <= TOL and social > TOL: valid = False
                    checks.append(dict(player=p, own_type=list(self.worlds[int(ids[0])][p]),
                                       own_gain=own, others_gain=social))
            if valid and not changed:
                self.values = values
                self.certificate = dict(verified=True, sweeps=sweep+1, nodes=len(self.entries),
                    root_world_weights=self.world_weights.tolist(),
                    type_checks=checks,
                    scope='Stable finite-window uniform-tie policy; no profitable conditional unilateral deviation. Not full-game optimality or equilibrium uniqueness.')
                return self
            key = b''.join(x.tobytes() for x in self.policy if x is not None)
            if key in seen:
                raise SearchLimit('Uniform-tie reference iteration cycled; no label')
            seen.add(key)
        raise SearchLimit('Uniform-tie reference did not converge within sweep budget')

    def action(self, index, own):
        raise ValueError('A random-tie policy has no single canonical action; sample via BeliefOracle.sample_action')
