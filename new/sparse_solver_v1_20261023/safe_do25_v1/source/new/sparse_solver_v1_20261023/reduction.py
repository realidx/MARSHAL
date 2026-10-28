"""Research-only, belief-independent backward elimination.

Never merge histories or private information sets. A cell is fixed only when
all continuations are already resolved and one action weakly dominates in
EVERY compatible world. Response ties also require pointwise social dominance.
The reduced game is a candidate generator; the full native certificate remains
mandatory, including eliminated/off-path histories.
"""
import numpy as np

from training.b_sft.decision_policy import is_offer_response

VERSION = 'pointwise-backward-sequence-reduction-v1'
ZERO = 1e-12


class Reduction:
    def __init__(self, tree, preserve_payoff_ties=True):
        self.tree = tree
        self.preserve_payoff_ties=preserve_payoff_ties
        self.fixed = {}
        self.known = np.zeros((len(tree.entries), tree.w), dtype=bool)
        self.payoffs = np.zeros((len(tree.entries), tree.w, tree.n))
        self.cell_ids = {}
        for i, groups in tree.information_groups.items():
            ids = np.empty(tree.w, dtype=int)
            for cell, worlds in enumerate(groups):
                ids[worlds] = cell
            self.cell_ids[i] = ids
        for i in reversed(range(len(tree.entries))):
            tree._check()
            entry = tree.entries[i]
            if entry.actor is None:
                self.known[i] = True
                self.payoffs[i] = entry.payoff
                continue
            for cell, ids in enumerate(tree.information_groups[i]):
                children = np.asarray(entry.children)
                if not self.known[children[:, None], ids].all():
                    continue
                values = self.payoffs[children[:, None], ids]
                own = values[:, :, entry.actor]
                others = values.sum(axis=2) - own
                chosen = None
                for a in range(len(children)):
                    own_gap = own[a] - own
                    if np.min(own_gap) < -ZERO:
                        continue
                    if is_offer_response(entry.actions):
                        # A pointwise own tie can be the entire posterior
                        # support. Require the social rule in each such world.
                        ties = np.abs(own_gap) <= ZERO
                        if np.min((others[a] - others)[ties], initial=0.) < -ZERO:
                            continue
                    if preserve_payoff_ties:
                        # An own-value proposal tie can change someone else's
                        # payoff and hence an EARLIER response's social tie.
                        # Keep such freedom. Only exact full-payoff ties or a
                        # pointwise strict lexicographic improvement are fixed.
                        unresolved=np.abs(own_gap)<=ZERO
                        if is_offer_response(entry.actions):
                            unresolved&=np.abs(others[a]-others)<=ZERO
                        different=np.max(np.abs(values[a]-values),axis=2)>ZERO
                        if np.any(unresolved&different):continue
                    chosen = a
                    break
                if chosen is not None:
                    self.fixed[i, cell] = chosen
                    self.known[i, ids] = True
                    self.payoffs[i, ids] = values[chosen]

    def allowed(self, index, world):
        cell = self.cell_ids[index][world]
        action = self.fixed.get((index, cell))
        return range(len(self.tree.entries[index].actions)) if action is None else (action,)

    def install(self):
        for (i, cell), a in self.fixed.items():
            ids = self.tree.information_groups[i][cell]
            self.tree.policy[i][:, ids] = 0.
            self.tree.policy[i][a, ids] = 1.

    def dimensions(self):
        seen = [set() for _ in range(self.tree.n)]
        leaves = 0
        def visit(i, w):
            nonlocal leaves
            if self.known[i, w]:
                leaves += 1
                return
            entry = self.tree.entries[i]
            cell = self.cell_ids[i][w]
            actions = tuple(self.allowed(i, w))
            if len(actions) > 1:
                seen[entry.actor].add((i, cell, len(actions)))
            for a in actions:
                visit(entry.children[a], w)
        for w in range(self.tree.w):
            visit(0, w)
        return dict(information_sets=[len(s) for s in seen],
                    sequences=[1 + sum(a for _, _, a in s) for s in seen],
                    terminal_world_histories=leaves,
                    fixed_information_cells=len(self.fixed),
                    root_worlds_resolved=int(self.known[0].sum()))
