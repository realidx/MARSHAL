"""Conservative reuse for bounded private-information oracle problems.

Only an exactly identical, successfully certified problem reuses its answer.
Physical transpositions and different public histories are never merged. A
subtree snapshot exposes structure only: it carries neither a policy nor a
certificate, and is not an equilibrium result for a newly conditioned root.
"""
from collections import OrderedDict, defaultdict
from copy import copy, deepcopy
from dataclasses import dataclass
import inspect
import time

import numpy as np

from training.b_sft.shared_teacher import Entry, SearchLimit
from training.b_sft.social_b_random_window import normalized_weights
from training.b_sft.social_private_teacher import observed_slots
from .bounded import BoundedPrivateWindow, VERSION, resolve_horizon
from .equilibrium import VERSION as EQUILIBRIUM_VERSION
from .common import digest


CACHE_VERSION = 'bounded-exact-problem-cache-v1'


def _validate_settings(settings):
    if any(type(settings[key]) is not int or settings[key] <= 0
           for key in ('max_nodes', 'max_sweeps')):
        raise ValueError('Positive integer node, sweep and candidate budgets required')
    if type(settings['max_candidates']) is not int or settings['max_candidates'] < 2:
        raise ValueError('At least two candidate policies are required')
    if not np.isfinite(settings['seconds']) or settings['seconds'] <= 0:
        raise ValueError('A finite positive wall-clock budget is required')
    if not np.isfinite(settings['epsilon']) or settings['epsilon'] <= 0:
        raise ValueError('A finite positive equilibrium epsilon is required')
    if settings['solver_mode'] not in ('synchronous', 'equilibrium'):
        raise ValueError('Unknown bounded solver_mode')
    if any(type(settings.get(key, 1)) is not int or settings.get(key, 1) < 1
           for key in ('max_joint_cells', 'max_joint_evaluations')):
        raise ValueError('Positive joint solver limits required')


def root_identity(rules, root):
    """Full history and private delivery records, not a physical-state key."""
    return dict(public_state=root.state.public_state(),
                pending=None if root.pending is None else root.pending.to_dict(),
                public_world_support=root.worlds,
                root_actor=rules.actor(root),
                observed_query_slots=[observed_slots(root, p) for p in range(rules.spec.n_players)],
                private_results=root.state.private_results)


def problem_identity(rules, root, worlds, world_weights=None, raw=None,
                     solver_factory=BoundedPrivateWindow, **solver_kwargs):
    """Include every effective constructor setting and the absolute endpoint.

    ``raw`` is retained when available. The executable native specification,
    catalogue, prior and complete root are always included independently.
    Proportional weights represent the same probability distribution.
    """
    worlds = tuple(tuple(tuple(row) for row in world) for world in worlds)
    prior = normalized_weights(np.ones(len(worlds)) if world_weights is None else world_weights,
                               len(worlds))
    bound = inspect.signature(solver_factory).bind(rules, root, worlds,
                                                   world_weights=prior, **solver_kwargs)
    bound.apply_defaults()
    settings = {key: value for key, value in bound.arguments.items()
                if key not in ('rules', 'root', 'worlds', 'world_weights')}
    _validate_settings(settings)
    horizon = resolve_horizon(rules, root, settings.get('lookahead_rr', 1),
                              settings.get('horizon_mode', 'rr-plus-next-own-proposal-v1'))
    identity = dict(cache_version=CACHE_VERSION, solver_version=VERSION,
                    equilibrium_solver_version=EQUILIBRIUM_VERSION,
                    solver_factory=solver_factory.__module__ + '.' + solver_factory.__qualname__,
                    raw=raw, native_game=rules.public_game(), catalogues=rules.catalogues,
                    worlds=worlds, normalized_prior=prior.tolist(),
                    root=root_identity(rules, root), horizon=horizon, solver_settings=settings)
    return digest(identity), identity


@dataclass
class CacheResult:
    tree: object
    problem_key: str
    cache_hit: bool
    elapsed_seconds: float
    source_build_seconds: float
    source_solve_seconds: float
    build_seconds: float
    solve_seconds: float
    structure_reused: bool = False
    answer_stored: bool = True

    def evidence(self):
        return dict(cache_version=CACHE_VERSION, exact_problem_key=self.problem_key,
                    exact_problem_cache_hit=self.cache_hit,
                    cache_lookup_and_copy_seconds=self.elapsed_seconds if self.cache_hit else 0.,
                    source_build_seconds=self.source_build_seconds,
                    source_solve_seconds=self.source_solve_seconds,
                    avoided_recomputation_source_seconds=(self.source_build_seconds + self.source_solve_seconds
                                                          if self.cache_hit else 0.),
                    structure_only_reuse=self.structure_reused,
                    certified_answer_stored=self.answer_stored,
                    reuse_scope='Exactly identical full-history Bayesian problem, absolute horizon and solver settings')


class BoundedProblemCache:
    """Process-local certified-answer cache with mutation-isolated returns."""

    def __init__(self, solver_factory=BoundedPrivateWindow, max_entries=2, max_cached_nodes=300000):
        if any(type(value) is not int or value < 0 for value in (max_entries, max_cached_nodes)):
            raise ValueError('Cache limits must be nonnegative integers')
        self.solver_factory = solver_factory
        self.max_entries, self.max_cached_nodes = max_entries, max_cached_nodes
        self._answers = OrderedDict()
        self.hits = self.misses = 0
        self.evictions = self.skipped_oversized = self.cached_nodes = 0
        self.avoided_source_seconds = 0.

    def solve(self, rules, root, worlds, world_weights=None, raw=None,
              parent_tree=None, parent_root_index=None, **solver_kwargs):
        started = time.monotonic()
        key, identity = problem_identity(rules, root, worlds, world_weights, raw,
                                         self.solver_factory, **solver_kwargs)
        if key in self._answers:
            self.hits += 1
            saved, build_seconds, solve_seconds = self._answers[key]
            self._answers.move_to_end(key)
            tree = deepcopy(saved)
            # A saved wall-clock deadline is not a valid budget for later
            # metrics or independent audits. No solve is rerun on a hit.
            tree.deadline = time.monotonic() + identity['solver_settings']['seconds']
            self.avoided_source_seconds += build_seconds + solve_seconds
            return CacheResult(tree, key, True, time.monotonic() - started,
                               build_seconds, solve_seconds, 0., 0.)
        self.misses += 1
        stamp = time.monotonic()
        tree = None
        try:
            if parent_tree is not None and type(parent_tree) is self.solver_factory:
                tree = reuse_structure(parent_tree, parent_root_index, rules, root, worlds,
                                       world_weights=world_weights, **solver_kwargs)
            structure_reused = tree is not None
            if tree is None:
                tree = self.solver_factory(rules, root, worlds, world_weights=world_weights, **solver_kwargs)
        except (SearchLimit, ValueError) as exc:
            exc.bounded_cache_failure_stage = 'build'
            raise
        build_seconds = time.monotonic() - stamp
        stamp = time.monotonic()
        try:
            tree.solve()
        except (SearchLimit, ValueError) as exc:
            exc.bounded_cache_failure_stage = 'solve'
            audit = getattr(tree, 'equilibrium_audit', None)
            if audit is not None:
                local = audit.get('local_policy_audit')
                local_done = local is not None
                local = {} if local is None else local
                exc.bounded_candidate_audit = dict(
                    failed_candidate_only=True, is_oracle_label=False,
                    max_own_deviation_gain=audit.get('max_own_deviation_gain'),
                    local_policy_audit_performed=local_done,
                    max_local_supported_action_gain=local.get('max_local_supported_action_gain'),
                    own_information_cell_failures=len(local.get('own_failures', [])) if local_done else None,
                    response_social_tie_failures=len(local.get('failures', [])) if local_done else None)
            raise
        solve_seconds = time.monotonic() - stamp
        if tree.certificate is None or not tree.certificate.get('verified'):
            raise ValueError('Only a successfully verified bounded problem can enter the answer cache')
        if getattr(tree, 'structure_reuse', None) is not None:
            tree.structure_reuse['independently_certified'] = True
        eligible = self.max_entries > 0 and len(tree.entries) <= self.max_cached_nodes
        if eligible:
            while self._answers and (len(self._answers) >= self.max_entries
                                     or self.cached_nodes + len(tree.entries) > self.max_cached_nodes):
                _, (evicted, _, _) = self._answers.popitem(last=False)
                self.cached_nodes -= len(evicted.entries)
                self.evictions += 1
            self._answers[key] = (deepcopy(tree), build_seconds, solve_seconds)
            self.cached_nodes += len(tree.entries)
        else:
            self.skipped_oversized += 1
        return CacheResult(tree, key, False, time.monotonic() - started,
                           build_seconds, solve_seconds, build_seconds, solve_seconds,
                           structure_reused, eligible)

    def stats(self):
        return dict(cache_version=CACHE_VERSION, hits=self.hits, misses=self.misses,
                    stored_certified_problems=len(self._answers),
                    max_entries=self.max_entries, max_cached_nodes=self.max_cached_nodes,
                    cached_nodes=self.cached_nodes, evictions=self.evictions,
                    skipped_due_to_cache_limits=self.skipped_oversized,
                    avoided_recomputation_source_seconds=self.avoided_source_seconds,
                    timing_interpretation='Sum of measured original build/solve times for reused answers; not a prediction of future runtime')


def structural_subtree_snapshot(tree, root_index, absolute_cutoff, deadline=None):
    """Copy native descendant structure only when the absolute horizon matches.

    All original public and private histories remain on every node. Policies,
    propagated values and equilibrium certificates deliberately are absent.
    A caller using this as a new problem must construct its information sets,
    condition its prior and independently solve and certify that problem.
    A different endpoint returns None rather than silently shortening a tree.
    """
    if absolute_cutoff != tree.cutoff:
        return None
    if type(root_index) is not int or not 0 <= root_index < len(tree.entries):
        raise ValueError('A valid public-history root index is required')
    ordered = []

    def check():
        if deadline is not None and time.monotonic() > deadline:
            raise SearchLimit('Bounded structure reuse wall budget exceeded')

    def visit(index):
        check()
        ordered.append(index)
        for child in tree.entries[index].children:
            visit(child)

    visit(root_index)
    remap = {old: new for new, old in enumerate(ordered)}
    entries = []
    # Preserve shared native specs, immutable events and action objects within
    # the isolated snapshot; copying each history independently duplicates the
    # same game specification once per node and defeats structural reuse.
    memo = {}
    for old in ordered:
        check()
        entries.append(Entry(deepcopy(tree.entries[old].node, memo), tree.entries[old].actor,
                             deepcopy(tree.entries[old].actions, memo),
                             tuple(remap[child] for child in tree.entries[old].children),
                             deepcopy(tree.entries[old].payoff, memo)))
    check()
    entries = tuple(entries)
    return dict(entries=entries, worlds=deepcopy(tree.worlds), absolute_cutoff=absolute_cutoff,
                original_root_index=root_index, original_indices=tuple(ordered),
                root_identity=root_identity(tree.rules, entries[0].node),
                policy=None, values=None, certificate=None, automatically_certified=False,
                reuse_scope='Native full-history structure only; independent root-conditioned solving required')


def reuse_structure(parent_tree, root_index, rules, root, worlds, world_weights=None,
                    **solver_kwargs):
    """Rebuild a new problem from a semantically identical native subtree.

    A changed standard horizon, world support, game, root history or private
    deliveries returns None, so callers perform ordinary fresh enumeration.
    A changed prior is supported by rebuilding information groups and solving
    from the standard uniform policy; the parent's certificate is discarded.
    """
    bound = inspect.signature(BoundedPrivateWindow).bind(rules, root, worlds,
                                                       world_weights=world_weights, **solver_kwargs)
    bound.apply_defaults()
    settings = {key: value for key, value in bound.arguments.items()
                if key not in ('rules', 'root', 'worlds', 'world_weights')}
    _validate_settings(settings)
    deadline = time.monotonic() + settings['seconds']
    if type(parent_tree) is not BoundedPrivateWindow:
        return None
    horizon = resolve_horizon(rules, root, settings['lookahead_rr'], settings['horizon_mode'])
    if (horizon['cutoff'] != parent_tree.cutoff or tuple(worlds) != tuple(parent_tree.worlds)
            or digest(rules.public_game()) != digest(parent_tree.rules.public_game())):
        return None
    if type(root_index) is not int or not 0 <= root_index < len(parent_tree.entries):
        raise ValueError('A valid parent public-history root index is required')
    if root_identity(rules, root) != root_identity(parent_tree.rules, parent_tree.entries[root_index].node):
        return None
    if rules.actor(root) is None:
        raise ValueError('No decision after terminal')
    snapshot = structural_subtree_snapshot(parent_tree, root_index, horizon['cutoff'], deadline)
    if len(snapshot['entries']) > settings['max_nodes']:
        raise SearchLimit('Reused bounded structure exceeds the configured node budget')
    tree = copy(parent_tree)
    tree.equilibrium_audit = None
    tree.rules = rules
    tree.entries = list(snapshot['entries'])
    tree.types = parent_tree.types.copy()
    tree.horizon = horizon
    for key, value in horizon.items():
        setattr(tree, key, value)
    tree.end = horizon['cutoff']
    for key, value in settings.items():
        if key != 'seconds':
            setattr(tree, key, value)
    tree.deadline = deadline
    tree.world_weights = normalized_weights(np.ones(tree.w) if world_weights is None else world_weights,
                                            tree.w)
    if np.any(tree.world_weights <= 0):
        raise ValueError('Remove zero-support worlds before constructing the private teacher')
    tree.certificate = tree.values = None
    tree.initialization = 'uniform'
    tree.audit_update_order = None
    tree.chance, tree.leaves = {}, {}
    tree.cutoff_leaves = {i for i, entry in enumerate(tree.entries)
                          if entry.actor is None and not entry.node.state.is_terminal}
    tree.possible_masks = [np.array([world in entry.node.worlds for world in tree.worlds])
                           for entry in tree.entries]
    tree.policy = [None if entry.actor is None else np.full((len(entry.actions), tree.w), 1 / len(entry.actions))
                   for entry in tree.entries]
    tree.information_groups = {}
    for index, entry in enumerate(tree.entries):
        if index % 256 == 0:
            tree._check()
        if entry.actor is None:
            continue
        slots = observed_slots(entry.node, entry.actor)
        groups = defaultdict(list)
        for wi, world in enumerate(tree.worlds):
            groups[(world[entry.actor], tuple(world[p][g] for p, g in slots))].append(wi)
        tree.information_groups[index] = [np.array(ids) for ids in groups.values()]
    tree.groups = {}
    for player in range(tree.n):
        slots = observed_slots(root, player)
        groups = defaultdict(list)
        for wi, world in enumerate(tree.worlds):
            groups[(world[player], tuple(world[p][g] for p, g in slots))].append(wi)
        tree.groups[player] = [np.array(ids) for ids in groups.values()]
    tree.structure_reuse = dict(parent_root_index=root_index, absolute_cutoff=tree.cutoff,
                               original_nodes=len(parent_tree.entries), reused_nodes=len(tree.entries),
                               initialization='uniform', independently_certified=False)
    tree._check()
    return tree
