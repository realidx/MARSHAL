"""Cache-only acceleration of the frozen UCT policy for larger B catalogues.

No change to action ordering, random draws, budgets, utility, or tie-breaking.
The reference policy repeatedly computes the same public-domain acceptance
fraction for different own types; share those calculations across own types.
"""
from functools import lru_cache

from benac_p.mcts_oracle import PrivateUCT


class CachedPrivateUCT(PrivateUCT):
    @lru_cache(maxsize=65536)
    def action_groups(self, node):
        actions = self.actions(node)
        if node[2] is not None:
            return (actions,)
        groups = (tuple(a for a in actions if a[0] == -1),
                  tuple(a for a in actions if a[0] != -1 and not a[2]),
                  tuple(a for a in actions if a[2]))
        return tuple(g for g in groups if g)

    @lru_cache(maxsize=262144)
    def acceptance(self, mask, child, partner, types):
        utility = self.utilities[partner]
        return sum(utility[t, child] > utility[t, mask] for t in types) / len(types)

    @lru_cache(maxsize=131072)
    def reference(self, node, own_type, domains):
        actor = self.actor(node)
        mask, _, pending = node
        actions = self.actions(node)
        own_u = self.utilities[actor][own_type]
        if pending is not None:
            return max(actions, key=lambda a: int(own_u[self.step(node, a)[0]]))
        best, best_delta = actions[0], 0.0
        groups = self.action_groups(node)
        ordinary = groups[1] if len(groups) > 1 else ()
        for action in ordinary:
            partner, delta, _ = action
            child = mask | delta
            gain = int(own_u[child]) - int(own_u[mask])
            if gain <= best_delta:
                continue
            score = gain * self.acceptance(mask, child, partner, domains[partner])
            if score > best_delta:
                best, best_delta = action, score
        return best

    def rollout_action(self, node, own_type, domains, rng):
        if rng.random() >= self.budget.rollout_exploration:
            return self.reference(node, own_type, domains)
        if node[2] is not None:
            return rng.choice(self.actions(node))
        return rng.choice(rng.choice(self.action_groups(node)))

    def clear_caches(self):
        super().clear_caches()
        self.acceptance.cache_clear()
        self.action_groups.cache_clear()
