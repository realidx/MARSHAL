"""Fail-closed mixed behavioral candidates for small enumerated Bayesian games.

The numerical search is not a general convergence guarantee.  Every accepted
profile is checked by the original complete-tree unilateral best responses,
conditioned separately on each player's root private information.  No payoff,
information set, native branch, or cutoff changes here.
"""
from collections import deque
import hashlib
import time

import numpy as np

from training.b_sft.decision_policy import is_offer_response
from training.b_sft.shared_teacher import SearchLimit, TOL


VERSION = 'private-behavioral-joint-epsilon-v5'


def _copy(policy):
    return [None if p is None else p.copy() for p in policy]


def _identity(policy):
    digest = hashlib.sha256()
    for p in policy:
        if p is not None:
            digest.update(p.tobytes())
    return digest.digest()


def _validate(tree):
    for i, entry in enumerate(tree.entries):
        if i % 256 == 0:
            tree._check()
        if entry.actor is None:
            continue
        p = tree.policy[i]
        if (p.shape != (len(entry.actions), tree.w) or not np.isfinite(p).all()
                or np.min(p) < -TOL or not np.allclose(p.sum(axis=0), 1., atol=TOL, rtol=0)):
            raise SearchLimit('Mixed candidate is not a valid behavioral probability profile')
        for ids in tree.information_groups[i]:
            if not np.allclose(p[:, ids], p[:, ids[:1]], atol=TOL, rtol=0):
                raise SearchLimit('Mixed candidate leaks private information')


def _reach(tree, player):
    reach = [None] * len(tree.entries)
    reach[0] = tree.world_weights.copy()
    for i, entry in enumerate(tree.entries):
        if i % 256 == 0:
            tree._check()
        for a, child in enumerate(entry.children):
            reach[child] = reach[i] if entry.actor == player else reach[i] * tree.policy[i][a]
    return reach


def _means(tree, values, reach, index, ids):
    weights = reach[index][ids]
    if weights.sum() == 0:
        weights = tree.world_weights[ids]
    child_values = np.stack([values[c][ids] for c in tree.entries[index].children])
    result = np.einsum('awp,w->ap', child_values, weights / weights.sum())
    if not np.isfinite(result).all():
        raise SearchLimit('Equilibrium audit encountered a nonfinite conditional action value')
    return result


def local_policy_audit(tree, values=None, epsilon=1e-8):
    """Check local own-optimal support and response ties, including off path.

    Zero counterfactual reach uses the existing prior conditioned on own type
    and actual private answers. This is a declared off-path convention, not a
    claim of tremble-consistent beliefs or a formal sequential equilibrium.
    """
    values = tree.evaluate() if values is None else values
    failures, own_failures = [], []
    checks = 0
    own_checks = 0
    max_local_gain = 0.
    for player in range(tree.n):
        reach = _reach(tree, player)
        for i, entry in enumerate(tree.entries):
            if i % 256 == 0:
                tree._check()
            if entry.actor != player:
                continue
            for cell, ids in enumerate(tree.information_groups[i]):
                means = _means(tree, values, reach, i, ids)
                own = means[:, player]
                probabilities = tree.policy[i][:, ids[0]]
                support = np.flatnonzero(probabilities > TOL)
                local_gain = float(own.max() - np.dot(probabilities, own))
                support_gain = float(own.max() - own[support].min())
                own_checks += 1
                max_local_gain = max(max_local_gain, support_gain)
                if support_gain > epsilon:
                    own_failures.append(dict(index=i, cell=cell, player=player,
                                             own_gain=local_gain,
                                             max_supported_action_gain=support_gain))
                if not is_offer_response(entry.actions):
                    continue
                tied = np.flatnonzero(own >= own.max() - TOL)
                others = means.sum(axis=1) - own
                rejected = tied[others[tied] < others[tied].max() - TOL]
                mass = float(tree.policy[i][rejected, ids[0]].sum())
                checks += 1
                if mass > TOL:
                    failures.append(dict(index=i, cell=cell, player=player,
                                         disallowed_probability=mass))
    return dict(verified=not failures, information_cell_checks=checks,
                failures=failures, tie_tolerance=TOL,
                local_own_support_verified=not own_failures,
                own_information_cell_checks=own_checks,
                own_failures=own_failures,
                max_local_supported_action_gain=max_local_gain,
                local_own_support_epsilon=epsilon,
                off_path='Initial prior conditioned on own type and own private answers when counterfactual reach is zero; no formal sequential-equilibrium claim',
                convention='Among own-optimal offer responses, support only responses maximizing other-player utility; remaining admissible action ties may mix nonuniformly at every decision')


def social_tie_audit(tree, values=None):
    """Compatibility wrapper; returned audit includes local own support."""
    return local_policy_audit(tree, values)


def certify_policy(tree, epsilon=1e-8, require_social_ties=True,
                   _response_updates=None):
    """Return a certificate only after independent, complete-tree BR checks.

    A failed candidate returns ``None`` and supplies no training labels.  This
    function does not treat convergence of the numerical residual as proof.
    """
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError('epsilon must be finite and positive')
    _validate(tree)
    values = tree.evaluate()
    for i, value in enumerate(values):
        if i % 256 == 0:
            tree._check()
        if not np.isfinite(value).all():
            raise SearchLimit('Equilibrium audit encountered nonfinite propagated values')
    checks = []
    for player in range(tree.n):
        updates, alternative = tree.response(player)
        if not np.isfinite(alternative).all():
            raise SearchLimit('Equilibrium audit encountered a nonfinite best response')
        if _response_updates is not None:
            _response_updates[player] = updates
        for cell, ids in enumerate(tree.groups[player]):
            base = np.average(values[0][ids], axis=0, weights=tree.world_weights[ids])
            best = np.average(alternative[ids], axis=0, weights=tree.world_weights[ids])
            gain = float(best[player] - base[player])
            if not np.isfinite(gain):
                raise SearchLimit('Equilibrium audit encountered a nonfinite deviation gain')
            checks.append(dict(player=player, root_private_cell=cell,
                               own_type=list(tree.worlds[int(ids[0])][player]),
                               own_gain=gain))
    max_gain = max((r['own_gain'] for r in checks), default=0.)
    tree.equilibrium_audit = dict(max_own_deviation_gain=max_gain,
                                  root_private_information_deviation_checks=checks)
    if max_gain > epsilon:
        return None
    ties = local_policy_audit(tree, values, epsilon)
    tree.equilibrium_audit.update(local_policy_audit=ties)
    if not ties['local_own_support_verified'] or (require_social_ties and not ties['verified']):
        return None
    certificate = dict(version=VERSION, verified=True, numerical_epsilon=epsilon,
                       own_utility_epsilon_nash_verified=True,
                       exact_equilibrium_claim=False, uniqueness_proven=False,
                       uniqueness_required=False, full_game_equilibrium_verified=False,
                       all_player_same_solver=True, max_own_deviation_gain=max_gain,
                       root_private_information_deviation_checks=checks,
                       response_only_social_ties_verified=ties['verified'],
                       social_tie_audit=ties, exact_enumeration=True,
                       local_own_support_verified=True,
                       max_local_supported_action_gain=ties['max_local_supported_action_gain'],
                       off_path=ties['off_path'],
                       information='Public action history + own preferences + own private query answers; perfect recall',
                       selection_contract='Deterministic complete contingent BR candidates retain the response-only social tie rule; final joint behavioral mixing may be nonuniform among remaining admissible actions; complete-tree private-information-conditioned BR checks and local own-optimal support audits accept only epsilon-Nash profiles under the declared off-path convention',
                       scope='Numerically certified own-utility epsilon-Nash profile of this explicitly enumerated cutoff game; no unique or original-game terminal equilibrium claim')
    tree._check()
    return dict(policy=_copy(tree.policy), values=values, certificate=certificate)


def _screen_root(tree):
    """Search-only root regret; acceptance still calls certify_policy afresh.

    Self-generated complete BR candidates retain information-cell-constant
    probabilities. Repeating all-cell privacy/local checks on every candidate
    is expensive and unnecessary for search; final certification retains them.
    """
    values = tree.evaluate()
    for i, value in enumerate(values):
        if i % 256 == 0:
            tree._check()
        if not np.isfinite(value).all():
            raise SearchLimit('Equilibrium screening encountered nonfinite propagated values')
    checks, responses = [], {}
    for player in range(tree.n):
        responses[player], alternative = getattr(tree, '_candidate_response', tree.response)(player)
        if not np.isfinite(alternative).all():
            raise SearchLimit('Equilibrium screening encountered a nonfinite best response')
        for cell, ids in enumerate(tree.groups[player]):
            base = np.average(values[0][ids], axis=0, weights=tree.world_weights[ids])
            best = np.average(alternative[ids], axis=0, weights=tree.world_weights[ids])
            gain = float(best[player]-base[player])
            if not np.isfinite(gain):
                raise SearchLimit('Equilibrium screening encountered a nonfinite deviation gain')
            checks.append(dict(player=player, root_private_cell=cell,
                               own_type=list(tree.worlds[int(ids[0])][player]), own_gain=gain))
    maximum = max((check['own_gain'] for check in checks), default=0.)
    tree.equilibrium_audit = dict(max_own_deviation_gain=maximum,
                                  root_private_information_deviation_checks=checks)
    return maximum, responses


def _certify_candidate(tree, epsilon, require_social_ties):
    """Reject clearly invalid local support cheaply; never certify by screening."""
    screen = getattr(tree, '_candidate_local_screen', None)
    if screen is not None and not screen(epsilon, require_social_ties):
        return None
    return certify_policy(tree, epsilon, require_social_ties)


class _JointResidual:
    """Exact policy-sensitive ancestor compression of the original history tree.

    Constant subtrees are evaluated once; their original payoff vectors are
    retained.  Histories, private-information cells and parent edges are never
    merged by physical state or by a putative common posterior.
    """
    def __init__(self, tree, cells, action_supports=None):
        self.tree = tree
        self.cells = sorted(cells)
        self.base = _copy(tree.policy)
        self.parent = {}
        for i, entry in enumerate(tree.entries):
            if i % 256 == 0:
                tree._check()
            for a, child in enumerate(entry.children):
                self.parent[child] = (i, a)
        sensitive = {i for i, _ in self.cells}
        for i in list(sensitive):
            while i in self.parent:
                i, _ = self.parent[i]
                sensitive.add(i)
        self.sensitive = sorted(sensitive, reverse=True)
        self.constant = tree.evaluate()
        self.paths = {}
        self.offsets = []
        self.action_supports = {}
        self.offset_supports = {}
        self.x0 = []
        for i, cell in self.cells:
            entry = tree.entries[i]
            ids = tree.information_groups[i][cell]
            support = tuple(sorted(set((action_supports or {}).get(
                (i, cell), range(len(entry.actions))))))
            if not support or any(type(a) is not int or a < 0 or a >= len(entry.actions)
                                  for a in support):
                raise ValueError('Joint action support must contain valid native action indices')
            self.action_supports[i, cell] = support
            means = self.constant[i][ids].mean(axis=0)
            start = len(self.x0)
            initial = self.base[i][list(support), ids[0]].copy()
            initial = initial / initial.sum() if initial.sum() > 0 else np.full(len(support), 1 / len(support))
            self.x0.extend(initial)
            self.x0.append(float(means[entry.actor]))
            self.offsets.append((i, ids, start, len(support)))
            self.offset_supports[start] = np.asarray(support, dtype=int)
            path = []
            child = i
            while child in self.parent:
                parent, action = self.parent[child]
                if tree.entries[parent].actor != entry.actor:
                    path.append((parent, action))
                child = parent
            self.paths[i] = path
        self.x0 = np.asarray(self.x0, dtype=float)

    def unpack(self, x):
        policy = list(self.base)
        changed = {}
        for i, ids, start, actions in self.offsets:
            if i not in changed:
                changed[i] = self.base[i].copy()
                policy[i] = changed[i]
            policy[i][:, ids] = 0.
            policy[i][np.ix_(self.offset_supports[start], ids)] = x[start:start + actions, None]
        return policy

    def _compile(self):
        """Batch independent histories by depth; preserve every world and edge."""
        nodes = sorted(set(self.sensitive) | {
            c for i in self.sensitive for c in self.tree.entries[i].children})
        self._slots = {i: j for j, i in enumerate(nodes)}
        self._constant_array = np.stack([self.constant[i] for i in nodes])
        max_actions = max(len(self.tree.entries[i].actions) for i in self.sensitive)
        self._base_array = np.zeros((len(nodes), max_actions, self.tree.w))
        depths = {0: 0}
        layers = {}
        for i, entry in enumerate(self.tree.entries):
            for c in entry.children:
                depths[c] = depths[i] + 1
        for i in self.sensitive:
            self._base_array[self._slots[i], :len(self.base[i])] = self.base[i]
            layers.setdefault((depths[i], len(self.tree.entries[i].actions)), []).append(i)
        self._layers = []
        for key in sorted(layers, reverse=True):
            entries = layers[key]
            self._layers.append((np.array([self._slots[i] for i in entries]),
                np.array([[self._slots[c] for c in self.tree.entries[i].children] for i in entries])))
        rows, actions, worlds, variables = [], [], [], []
        batches = {}
        for i, ids, start, count in self.offsets:
            slot = self._slots[i]
            self._base_array[slot, :, ids] = 0.
            for a, native_action in enumerate(self.offset_supports[start]):
                rows.extend([slot] * len(ids)); actions.extend([native_action] * len(ids))
                worlds.extend(ids); variables.extend([start + a] * len(ids))
            batches.setdefault((count, len(ids), len(self.paths[i])), []).append((i, ids, start, count))
        self._assignment = tuple(np.asarray(v, dtype=int) for v in (rows, actions, worlds, variables))
        self._batches = []
        for (count, _, length), offsets in batches.items():
            starts = np.array([o[2] for o in offsets])
            ids = np.stack([o[1] for o in offsets])
            children = np.array([[self._slots[self.tree.entries[i].children[a]]
                for a in self.offset_supports[start]] for i, _, start, _ in offsets])
            parents = np.array([[self._slots[j] for j, _ in self.paths[i]]
                for i, _, _, _ in offsets], dtype=int)
            path_actions = np.array([[a for _, a in self.paths[i]]
                for i, _, _, _ in offsets], dtype=int)
            actors = np.array([self.tree.entries[i].actor for i, _, _, _ in offsets])
            self._batches.append((starts, ids, children, parents, path_actions, actors, count, length))

    def residual(self, x):
        self.tree._check()
        if not hasattr(self, '_batches'):
            self._compile()
        policy = self._base_array.copy()
        rows, actions, worlds, variables = self._assignment
        policy[rows, actions, worlds] = x[variables]
        values = self._constant_array.copy()
        for slots, children in self._layers:
            values[slots] = np.einsum('baw,bawp->bwp',
                policy[slots, :children.shape[1]], values[children])
        result = np.empty(len(x))
        for starts, ids, children, parents, path_actions, actors, count, length in self._batches:
            reach = self.tree.world_weights[ids].copy()
            if length:
                reach *= policy[parents[:, :, None], path_actions[:, :, None], ids[:, None, :]].prod(axis=1)
            mass = reach.sum(axis=1)
            zero = mass == 0
            reach[zero] = self.tree.world_weights[ids[zero]]
            reach /= reach.sum(axis=1)[:, None]
            own = np.einsum('baw,bw->ba',
                values[children[:, :, None], ids[:, None, :], actors[:, None, None]], reach)
            positions = starts[:, None] + np.arange(count)
            probabilities = x[positions]
            gap = x[starts + count, None] - own
            result[positions] = np.hypot(probabilities, gap) - probabilities - gap
            result[starts + count] = probabilities.sum(axis=1) - 1.
        return result

    def bounds(self):
        lower = np.zeros(len(self.x0))
        upper = np.ones(len(self.x0))
        for _, _, start, actions in self.offsets:
            lower[start + actions] = -np.inf
            upper[start + actions] = np.inf
        return lower, upper

    def sparsity(self):
        """Exact structural dependence for sparse numerical differentiation."""
        from scipy.sparse import lil_matrix
        size = len(self.x0)
        pattern = lil_matrix((size, size), dtype=int)
        ancestors = {}
        for i, _ in self.cells:
            self.tree._check()
            path, child = set(), i
            while child in self.parent:
                child, _ = self.parent[child]
                path.add(child)
            ancestors[i] = path
        by_node = {}
        for offset in self.offsets:
            by_node.setdefault(offset[0], []).append(offset)
        descendants = {i: set() for i in by_node}
        for j in by_node:
            for i in ancestors[j]:
                if i in descendants:
                    descendants[i].add(j)
        for i, ids, start, actions in self.offsets:
            actor = self.tree.entries[i].actor
            self.tree._check()
            relevant = descendants[i] | {i} | {
                j for j in ancestors[i] if j in by_node and self.tree.entries[j].actor != actor}
            for j, jids, other, jactions in (o for j in relevant for o in by_node[j]):
                if not np.intersect1d(ids, jids).size:
                    continue
                own_variables = (i == j and np.array_equal(ids, jids))
                descendant = i in ancestors[j]
                other_ancestor = j in ancestors[i] and self.tree.entries[j].actor != actor
                if own_variables or descendant or other_ancestor:
                    pattern[start:start+actions, other:other+jactions] = 1
                    if own_variables:
                        pattern[start:start+actions, other+jactions] = 1
            pattern[start+actions, start:start+actions] = 1
        return pattern.tocsr()

    def normalized_policy(self, x):
        if not np.isfinite(x).all():
            raise SearchLimit('Joint equilibrium candidate contains nonfinite probabilities')
        policy = self.unpack(x)
        for i, ids, _, _ in self.offsets:
            p = np.clip(policy[i][:, ids[0]], 0., 1.)
            if p.sum() <= 0:
                raise SearchLimit('Joint equilibrium candidate has zero probability mass')
            p /= p.sum()
            policy[i][:, ids] = p[:, None]
        return policy


def _varying_cells(tree, profiles):
    cells = set()
    for i, groups in tree.information_groups.items():
        if i % 256 == 0:
            tree._check()
        for cell, ids in enumerate(groups):
            reference = profiles[0][i][:, ids[0]]
            if any(not np.allclose(p[i][:, ids[0]], reference, atol=TOL, rtol=0)
                   for p in profiles[1:]):
                cells.add((i, cell))
    return cells


def _violating_cells(tree, epsilon):
    values = tree.evaluate()
    cells = set()
    for player in range(tree.n):
        reach = _reach(tree, player)
        for i, groups in tree.information_groups.items():
            if i % 256 == 0:
                tree._check()
            if tree.entries[i].actor != player:
                continue
            for cell, ids in enumerate(groups):
                own = _means(tree, values, reach, i, ids)[:, player]
                p = tree.policy[i][:, ids[0]]
                support = np.flatnonzero(p > TOL)
                if float(own.max() - own[support].min()) > epsilon:
                    cells.add((i, cell))
    return cells


def _profile_supports(tree, cells, profiles):
    """Native action unions seed candidates, without pruning game branches."""
    supports = {}
    for i, cell in cells:
        tree._check()
        ids = tree.information_groups[i][cell]
        actions = set()
        for profile in profiles:
            actions.update(int(a) for a in np.flatnonzero(profile[i][:, ids[0]] > TOL))
        if not actions:
            actions.update(range(len(tree.entries[i].actions)))
        supports[i, cell] = tuple(sorted(actions))
    return supports


def _expand_profitable_supports(tree, cells, supports, epsilon):
    """Look outside every candidate support using all native action values."""
    values = tree.evaluate()
    additions = set()
    expanded = 0
    for player in range(tree.n):
        reach = _reach(tree, player)
        for i, groups in tree.information_groups.items():
            if i % 256 == 0:
                tree._check()
            if tree.entries[i].actor != player:
                continue
            for cell, ids in enumerate(groups):
                own = _means(tree, values, reach, i, ids)[:, player]
                active = np.flatnonzero(tree.policy[i][:, ids[0]] > TOL)
                if float(own.max() - own[active].min()) <= epsilon:
                    continue
                key = (i, cell)
                additions.add(key)
                # Including all legal actions at a violating cell also lets
                # the next joint search escape a too-narrow local minimum.
                previous = set(supports.get(key, tuple(int(a) for a in active)))
                complete = tuple(range(len(own)))
                expanded += len(set(complete) - previous)
                supports[key] = complete
    return additions, expanded


def solve_equilibrium(tree, max_sweeps=128, epsilon=1e-8, max_candidates=6,
                      require_social_ties=True, max_joint_cells=4096,
                      max_joint_evaluations=160, max_ordered_sweeps=8,
                      large_tree_ordered_sweeps=2):
    """Find and independently certify a bounded-game behavioral mixed profile.

    The tree's existing wall-clock budget is honored in every stage.  On any
    unsuccessful search, ``SearchLimit`` is raised and no usable certificate
    or values remain.  Numerical optimization is a candidate generator only.
    """
    if max_sweeps < 1 or max_candidates < 2 or large_tree_ordered_sweeps < 1:
        raise ValueError('positive sweeps and at least two candidates required')
    tree.certificate = None
    tree.values = None
    tree.equilibrium_audit = None
    original = _copy(tree.policy)
    history = deque(maxlen=max_candidates)
    seen = set()
    count = 0
    try:
        _validate(tree)
        search_started = time.monotonic()
        available = max(0., getattr(tree, 'deadline', np.inf)-search_started)
        sync_deadline = search_started + .2 * available
        ordered_deadline = search_started + .4 * available
        large_tree = len(tree.entries) >= 30000
        if large_tree:
            from .batched_response import BatchedResponse
            batch = BatchedResponse(tree)
            tree._candidate_response = batch.response
            tree._candidate_local_screen = batch.locally_admissible
        sync_sweeps = min(max_sweeps, 8) if large_tree else max_sweeps
        ordered_sweeps = min(max_ordered_sweeps, large_tree_ordered_sweeps) if large_tree else max_ordered_sweeps
        schedule = dict(frontend_synchronous_budget_fraction=.2,
                        frontend_ordered_budget_fraction=.2,
                        joint_and_final_audit_target_fraction=.6,
                        phase_limits_checked_between_complete_candidates=True,
                        large_tree_candidate_caps=large_tree,
                        synchronous_sweep_cap=sync_sweeps,
                        ordered_sweep_cap_per_start=ordered_sweeps)
        schedule['candidate_local_screen'] = 'batched-rejection-only-v1' if large_tree else None
        screened_root_pass = False
        # Preserve the historical deterministic initialization and BR/tie
        # convention; test Nash gains, not equality of two entire policy tables.
        for sweep in range(sync_sweeps):
            if sweep and time.monotonic() >= sync_deadline:
                break
            tree._check()
            history.append(_copy(tree.policy))
            maximum, responses = _screen_root(tree)
            new = list(tree.policy)
            for player in range(tree.n):
                updates = responses[player]
                for i, p in updates.items():
                    new[i] = p
            stable = _identity(new) == _identity(tree.policy)
            if maximum <= epsilon and (stable or not screened_root_pass):
                screened_root_pass = True
                candidate = _certify_candidate(tree, epsilon, require_social_ties)
                if candidate is not None:
                    candidate['certificate'].update(candidate_method='complete-contingent-best-response',
                                                    sweeps=sweep, joint_solves=0,
                                                    candidate_budget_schedule=schedule,
                                                    independent_final_certification=True)
                    return candidate
            signature = _identity(new)
            tree.policy = new
            count = sweep + 1
            if signature in seen:
                history.append(_copy(new))
                break
            seen.add(signature)
        history.append(_copy(tree.policy))
        profiles = list(history)
        alternatives = [(profiles, float(tree.equilibrium_audit['max_own_deviation_gain']))]
        # Initialization and player ordering change the deterministic search,
        # never the game, objective, private information or acceptance test.
        # First/last are native-action-order candidates, not fixed opponents.
        candidate_starts = [(initialization, order)
                            for initialization in ('uniform', 'first', 'last')
                            for order in (tuple(range(tree.n)), tuple(reversed(range(tree.n))))]
        for initialization, order in candidate_starts:
            if time.monotonic() >= ordered_deadline:
                break
            tree._check()
            tree.policy = []
            for i, entry in enumerate(tree.entries):
                if i % 256 == 0:
                    tree._check()
                if entry.actor is None:
                    tree.policy.append(None)
                    continue
                probabilities = np.full((len(entry.actions), tree.w), 1 / len(entry.actions))
                if initialization != 'uniform':
                    probabilities[:] = 0.
                    probabilities[0 if initialization == 'first' else -1] = 1.
                tree.policy.append(probabilities)
            ordered_history = deque(maxlen=max_candidates)
            ordered_seen = set()
            for ordered_sweep in range(min(max_sweeps, ordered_sweeps)):
                if ordered_sweep and time.monotonic() >= ordered_deadline:
                    break
                tree._check()
                before = _identity(tree.policy)
                ordered_history.append(_copy(tree.policy))
                for player in order:
                    updates, _ = getattr(tree, '_candidate_response', tree.response)(player)
                    for i, probabilities in updates.items():
                        tree.policy[i] = probabilities
                signature = _identity(tree.policy)
                count += 1
                if signature == before or signature in ordered_seen:
                    break
                ordered_seen.add(signature)
            ordered_history.append(_copy(tree.policy))
            maximum, _ = _screen_root(tree)
            candidate = (_certify_candidate(tree, epsilon, require_social_ties)
                         if maximum <= epsilon else None)
            if candidate is not None:
                candidate['certificate'].update(
                    candidate_method='ordered-complete-contingent-best-response',
                    initialization=initialization, update_order=list(order),
                    sweeps=ordered_sweep + 1, joint_solves=0,
                    candidate_budget_schedule=schedule,
                    independent_final_certification=True)
                return candidate
            alternatives.append((list(ordered_history),
                                 float(tree.equilibrium_audit['max_own_deviation_gain'])))
        alternatives.sort(key=lambda item: item[1])
        # Transient initial uniform/first/last policies do not belong to the
        # recurring disagreement. Start with the final pair, then expand by
        # exhaustive profitable-deviation checks. No native action is removed.
        profiles = alternatives[0][0][-2:]
        active_start = None
        if large_tree:
            # Start with actual current violations, rather than averaging
            # thousands of already optimal off-path cells that varied earlier.
            # Subsequent full-native audits grow this working set as needed.
            tree.policy = _copy(profiles[-1])
            violations = _violating_cells(tree, epsilon / 100)
            tie_check = local_policy_audit(tree, epsilon=epsilon)
            violations.update((f['index'], f['cell']) for f in tie_check['failures'])
            if violations:
                active_start = violations
        cells = _varying_cells(tree, profiles)
        if active_start is not None:
            cells = active_start
        if not cells:
            profiles = alternatives[0][0]
            cells = _varying_cells(tree, profiles)
        if not cells:
            # A stationary approximate profile can accumulate small local
            # errors into a failed complete contingent deviation check.
            cells = _violating_cells(tree, epsilon / max(100, len(tree.entries)))
        supports = (_profile_supports(tree, cells, profiles) if active_start is None else
                    {key: tuple(range(len(tree.entries[key[0]].actions))) for key in cells})
        support_expansions = 0
        if not cells:
            raise SearchLimit('Equilibrium candidate did not pass complete deviation/tie checks')
        # Averaging here initializes behavioral variables; it is explicitly
        # not an asserted mixture of normal-form contingent plans.
        for i, entry in enumerate(tree.entries):
            if i % 256 == 0:
                tree._check()
            if entry.actor is not None:
                tree.policy[i] = (np.mean([p[i] for p in profiles], axis=0)
                                  if active_start is None else profiles[-1][i].copy())
        from scipy.optimize import least_squares, root
        for attempt in range(8):
            tree._check()
            if len(cells) > max_joint_cells:
                raise SearchLimit(f'Joint equilibrium candidate information-cell budget exceeded: {len(cells)} > {max_joint_cells}')
            residual = _JointResidual(tree, cells, action_supports=supports)
            # A root row depends on most descendant variables: sparse finite
            # difference coloring can still require one evaluation per column.
            # Matrix-free Newton-Krylov avoids materializing that Jacobian.
            if len(residual.x0) > 256:
                solution = root(residual.residual, residual.x0, method='krylov',
                    options=dict(fatol=1e-11, maxiter=max_joint_evaluations, line_search='armijo'))
            else:
                solution = least_squares(residual.residual, residual.x0,
                                         bounds=residual.bounds(), ftol=1e-11,
                                         xtol=1e-11, gtol=1e-11,
                                         jac_sparsity=residual.sparsity(),
                                         tr_solver='lsmr',
                                         max_nfev=max_joint_evaluations)
            # Bound-constrained least squares approaches zero probabilities
            # asymptotically.  Polish its local complementarity root without
            # bounds, then enforce/verify actual simplex probabilities.  The
            # complete BR check remains the only acceptance criterion.
            method = 'hybr' if len(solution.x) <= 256 else 'krylov'
            options = (dict(xtol=1e-11, maxfev=max_joint_evaluations * max(1, len(solution.x)))
                       if method == 'hybr' else dict(fatol=1e-11, maxiter=max_joint_evaluations))
            polished = (root(residual.residual, solution.x, method=method, options=options)
                        if len(solution.x) <= 256 else solution)
            chosen = (polished.x if np.max(np.abs(residual.residual(polished.x)))
                      < np.max(np.abs(residual.residual(solution.x))) else solution.x)
            tree.policy = residual.normalized_policy(chosen)
            candidate = _certify_candidate(tree, epsilon, require_social_ties)
            # A boundary solution may leave tiny positive probabilities on
            # strictly suboptimal actions. Snapping is candidate generation
            # only; every snapped profile receives the same complete audit.
            if candidate is None:
                unsnapped = _copy(tree.policy)
                for threshold in (1e-10, 1e-8, 1e-6):
                    for i, ids, _, _ in residual.offsets:
                        p = unsnapped[i][:, ids[0]].copy()
                        p[p < threshold] = 0.
                        p /= p.sum()
                        tree.policy[i][:, ids] = p[:, None]
                    candidate = _certify_candidate(tree, epsilon, require_social_ties)
                    if candidate is not None:
                        candidate['certificate']['candidate_probability_snap'] = threshold
                        break
                if candidate is None:
                    tree.policy = unsnapped
            if candidate is not None:
                candidate['certificate'].update(
                    candidate_method='joint-behavioral-complementarity', sweeps=count,
                    joint_solves=attempt + 1, joint_information_cells=len(cells),
                    joint_probability_variables=len(solution.x),
                    joint_sensitive_history_nodes=len(residual.sensitive),
                    candidate_action_supports_restricted=True,
                    supported_native_actions=sum(len(s) for s in residual.action_supports.values()),
                    complete_native_actions_at_joint_cells=sum(len(tree.entries[i].actions)
                                                               for i, _ in cells),
                    support_expansion_added_actions=support_expansions,
                    final_full_native_best_response_audit=True,
                    candidate_budget_schedule=schedule,
                    independent_final_certification=True,
                    numerical_residual_max=float(np.max(np.abs(residual.residual(chosen)))),
                    scipy_solver=('matrix-free Newton-Krylov/Fischer-Burmeister' if len(solution.x) > 256 else
                                  'least_squares/trf/lsmr/sparse-jacobian + root/hybr/Fischer-Burmeister'),
                    max_joint_cells=max_joint_cells,
                    constant_subtree_reuse=True, strategy_histories_merged=False)
                return candidate
            additions, expanded = _expand_profitable_supports(tree, cells, supports, epsilon / 4)
            support_expansions += expanded
            ties = local_policy_audit(tree, epsilon=epsilon)
            # Preserve response tie convention during candidate refinement.
            # Replacing these local tied responses can alter earlier choices;
            # the next joint solve and complete BR checks must certify again.
            tie_updates = {player: getattr(tree, '_candidate_response', tree.response)(player)[0]
                           for player in {failure['player'] for failure in ties['failures']}}
            for failure in ties['failures']:
                i, cell, player = failure['index'], failure['cell'], failure['player']
                updates = tie_updates[player]
                ids = tree.information_groups[i][cell]
                tree.policy[i][:, ids] = updates[i][:, ids]
                additions.add((i, cell))
                previous = set(supports.get((i, cell), ()))
                complete = tuple(range(len(tree.entries[i].actions)))
                support_expansions += len(set(complete) - previous)
                supports[i, cell] = complete
            if not (additions - cells) and not expanded and ties['verified']:
                if attempt == 0 and len(alternatives) > 1:
                    # One deterministic second start prevents every residual
                    # refinement from staying in a single local minimum.
                    profiles = alternatives[1][0][-2:]
                    next_cells = _varying_cells(tree, profiles)
                    next_supports = _profile_supports(tree, next_cells, profiles)
                    for key, actions in next_supports.items():
                        previous = set(supports.get(key, ()))
                        combined = previous | set(actions)
                        support_expansions += len(combined - previous)
                        supports[key] = tuple(sorted(combined))
                    cells.update(next_cells)
                    for i, entry in enumerate(tree.entries):
                        if i % 256 == 0:
                            tree._check()
                        if entry.actor is not None:
                            tree.policy[i] = np.mean([p[i] for p in profiles], axis=0)
                    continue
                break
            cells.update(additions)
        raise SearchLimit('Joint mixed equilibrium search did not pass complete deviation/tie checks')
    except Exception:
        tree.policy = original
        tree.certificate = None
        tree.values = None
        raise
    finally:
        if hasattr(tree, '_candidate_response'):
            del tree._candidate_response
        if hasattr(tree, '_candidate_local_screen'):
            del tree._candidate_local_screen
