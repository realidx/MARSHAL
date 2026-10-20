"""Complete private-information solving with an explicit RR cutoff objective.

Every player uses the same jointly certified contingent-policy solver. Leaves score
the commitments already made at the cutoff, without a continuation policy,
rollout, learned value function or claim about the original game's equilibrium.
The selected profile is certified only for this truncated Bayesian game.
"""
import hashlib

import numpy as np

from training.b_sft.shared_teacher import Entry, SearchLimit, TOL
from training.b_sft.social_b_oracle import canonical
from training.b_sft.social_private_teacher import PrivateWindow, observed_slots


VERSION = 'rr-next-own-mixed-private-v5'
DEFAULT_HORIZON_MODE = 'rr-plus-next-own-proposal-v1'
DEFAULT_SOLVER_MODE = 'equilibrium'
LEAF_OBJECTIVE = 'Own native goal utility from commitments already made at cutoff; no continuation value'


def resolve_horizon(rules, root, lookahead_rr=1,
                    horizon_mode=DEFAULT_HORIZON_MODE):
    """Use one branch-independent endpoint, including the focal return action.

    The next focal *proposal opportunity* is strictly after the root cursor.
    It is completed, including any resulting response, rather than merely
    reaching its decision point. If native termination arrives sooner, no
    additional opportunity is invented. ``rr`` reproduces the older cutoff.
    """
    if type(lookahead_rr) is not int or lookahead_rr < 1:
        raise ValueError('lookahead_rr must be a positive integer')
    if horizon_mode not in ('rr', DEFAULT_HORIZON_MODE):
        raise ValueError('Unknown bounded horizon_mode')
    schedule = rules.spec.round_robin
    root_turn_index = root.state.turn_index
    root_actor = rules.actor(root)
    proposal_turns = rules.spec.n_players * lookahead_rr
    requested_base = root_turn_index + proposal_turns
    base_cutoff = min(requested_base, len(schedule))
    next_own = next((j for j in range(root_turn_index + 1, len(schedule))
                     if schedule[j] == root_actor), None)
    requested_cutoff = requested_base
    if horizon_mode == DEFAULT_HORIZON_MODE and next_own is not None:
        requested_cutoff = max(requested_cutoff, next_own + 1)
    cutoff = min(requested_cutoff, len(schedule))
    return dict(horizon_mode=horizon_mode, lookahead_rr=lookahead_rr,
                proposal_turns=proposal_turns,
                root_turn_index=root_turn_index, root_actor=root_actor,
                base_cutoff=base_cutoff, cutoff=cutoff,
                next_own_proposal_index=next_own,
                next_own_proposal_included=next_own is not None and next_own < cutoff,
                actual_proposal_turns=cutoff - root_turn_index,
                terminal_truncated_horizon=requested_cutoff > len(schedule))


def current_payoffs(rules, node, world):
    """Score the current physical commitments, including a nonterminal state.

    The world is a hypothetical supported payoff scenario, not information
    exposed to the decision maker. A pending offer has no commitment value.
    """
    world = tuple(tuple(row) for row in world)
    if world not in rules.worlds:
        raise ValueError('A compatible native preference world is required')
    return tuple(float(np.dot(row, node.state.goal_satisfaction())) for row in world)


class BoundedPrivateWindow(PrivateWindow):
    """Enumerate an RR span and complete the focal player's next proposal.

    A turn is one completed proposal opportunity: OFFER and its response count
    together; PASS and INVESTIGATE each consume one. A window starting during
    an offer includes its outstanding response in the first completed turn.
    Every branch uses the same absolute ``cutoff``, capped at game end.
    ``horizon_mode='rr'`` retains the historical RR-only endpoint.
    """

    def __init__(self, rules, root, worlds, world_weights=None, lookahead_rr=1,
                 max_nodes=400000, seconds=60, max_sweeps=128,
                 horizon_mode=DEFAULT_HORIZON_MODE,
                 solver_mode=DEFAULT_SOLVER_MODE, epsilon=1e-8,
                 max_candidates=6, max_joint_cells=4096, max_joint_evaluations=160,
                 large_tree_ordered_sweeps=2):
        if any(type(value) is not int or value < 1 for value in (max_nodes, max_sweeps)):
            raise ValueError('Node and sweep budgets must be positive integers')
        if not np.isfinite(seconds) or seconds <= 0:
            raise ValueError('seconds must be finite and positive')
        if solver_mode not in ('equilibrium', 'synchronous'):
            raise ValueError('Unknown bounded solver_mode')
        if not np.isfinite(epsilon) or epsilon <= 0:
            raise ValueError('epsilon must be finite and positive')
        if type(max_candidates) is not int or max_candidates < 2:
            raise ValueError('max_candidates must be an integer of at least two')
        self.solver_mode, self.epsilon = solver_mode, float(epsilon)
        self.max_candidates = max_candidates
        if type(large_tree_ordered_sweeps) is not int or large_tree_ordered_sweeps < 1:
            raise ValueError('Large tree ordered sweep budget must be a positive integer')
        self.large_tree_ordered_sweeps = large_tree_ordered_sweeps
        if any(type(v) is not int or v < 1 for v in (max_joint_cells, max_joint_evaluations)):
            raise ValueError('Joint solver limits must be positive integers')
        self.max_joint_cells, self.max_joint_evaluations = max_joint_cells, max_joint_evaluations
        self.horizon = resolve_horizon(rules, root, lookahead_rr, horizon_mode)
        for key, value in self.horizon.items():
            setattr(self, key, value)
        self.cutoff_leaves = set()
        super().__init__(rules, root, worlds, world_weights=world_weights,
                         max_nodes=max_nodes, seconds=seconds,
                         max_sweeps=max_sweeps)
        # TerminalWindow sets end to full game length. Public consumers must
        # see the actual bounded endpoint instead.
        self.end = self.cutoff

    def _grow(self, node):
        self._check()
        if len(self.entries) >= self.max_nodes:
            raise SearchLimit('RR cutoff teacher public-tree node budget exceeded')
        index = len(self.entries)
        self.entries.append(None)
        cut = node.state.turn_index >= self.cutoff and node.pending is None
        if node.state.is_terminal or cut:
            payoff = np.einsum('wpg,g->wp', self.types,
                               node.state.goal_satisfaction())
            self.entries[index] = Entry(node, None, (), (), payoff)
            if not node.state.is_terminal:
                self.cutoff_leaves.add(index)
            return index
        actions = self.rules.actions(node)
        children = tuple(self._grow(self.rules._apply(node, action))
                         for action in actions)
        self.entries[index] = Entry(node, self.rules.actor(node), actions, children)
        return index

    def reference_identity(self):
        # The inherited check verifies identical policies for worlds that the
        # acting player cannot distinguish, including its own query answers.
        private_hash, checks = super().reference_identity()
        if self.solver_mode == 'equilibrium':
            from .equilibrium import VERSION as solver_version
        else:
            solver_version = 'legacy-synchronous-private-best-response'
        contract = dict(version=VERSION, private_policy_sha256=private_hash,
                        **self.horizon, leaf_objective=LEAF_OBJECTIVE,
                        solver_mode=self.solver_mode, epsilon=self.epsilon,
                        solver_version=solver_version,
                        max_candidates=self.max_candidates,
                        max_joint_cells=self.max_joint_cells,
                        max_joint_evaluations=self.max_joint_evaluations,
                        step='Completed native proposal opportunity; finish pending OFFER response',
                        all_player_same_solver=True)
        return hashlib.sha256(canonical(contract).encode()).hexdigest(), checks

    def solve(self):
        # Numerical search is a candidate generator; a failed independent
        # deviation check or resource limit leaves no usable certificate.
        self.certificate = None
        self.values = None
        self.equilibrium_audit = None
        try:
            return self._solve_and_certify()
        except SearchLimit:
            self.certificate = None
            self.values = None
            raise

    def _solve_and_certify(self):
        if self.solver_mode == 'synchronous':
            super().solve()
        else:
            from .equilibrium import solve_equilibrium
            result = solve_equilibrium(self, max_sweeps=self.max_sweeps,
                                       epsilon=self.epsilon,
                                       max_candidates=self.max_candidates,
                                       max_joint_cells=self.max_joint_cells,
                                       max_joint_evaluations=self.max_joint_evaluations,
                                       large_tree_ordered_sweeps=self.large_tree_ordered_sweeps)
            self.policy, self.values = result['policy'], result['values']
            self.certificate = result['certificate']
            # Independent identity/privacy check after accepting a candidate.
            policy_hash, information_checks = self.reference_identity()
            self.certificate.update(policy_sha256=policy_hash,
                                    information_set_checks=information_checks)
        threshold = TOL if self.solver_mode == 'synchronous' else self.epsilon
        root_checks = []
        for player in range(self.n):
            _, best_response = self.response(player)
            for ids in self.groups[player]:
                base = np.average(self.values[0][ids], axis=0,
                                  weights=self.world_weights[ids])
                alternative = np.average(best_response[ids], axis=0,
                                         weights=self.world_weights[ids])
                gain = float(alternative[player] - base[player])
                if not np.isfinite(gain) or gain > threshold:
                    self.certificate = None
                    raise SearchLimit('RR cutoff profile failed final private-information deviation check')
                world = self.worlds[int(ids[0])]
                facts = [(p, g, world[p][g])
                         for p, g in observed_slots(self.entries[0].node, player)]
                root_checks.append(dict(player=player,
                                        own_type=list(world[player]),
                                        own_private_results=[list(f) for f in facts],
                                        own_gain=gain))
        self.certificate.update(
            version=VERSION, reference_backend=VERSION,
            terminal=not self.cutoff_leaves,
            truncated_profile_verified=True,
            remaining_game_terminal_scope=not self.cutoff_leaves,
            full_game_equilibrium_verified=False,
            all_player_same_solver=True, exact_enumeration=True,
            **self.horizon,
            solver_mode=self.solver_mode,
            max_candidates=self.max_candidates,
            max_joint_cells=self.max_joint_cells,
            max_joint_evaluations=self.max_joint_evaluations,
            large_tree_ordered_sweeps=self.large_tree_ordered_sweeps,
            numerical_epsilon=threshold,
            solver_version=(self.certificate.get('version') if self.solver_mode == 'equilibrium'
                            else 'legacy-synchronous-private-best-response'),
            cutoff_leaves=len(self.cutoff_leaves),
            leaf_objective=LEAF_OBJECTIVE, continuation_policy=None,
            root_private_information_deviation_checks=root_checks,
            max_own_deviation_gain=max(check['own_gain'] for check in root_checks),
            selection_contract=self.certificate['selection_contract'],
            scope=('Selected complete contingent profile with independent own-information-conditioned '
                   'unilateral deviation gain bounded by the declared numerical tolerance in this '
                   'explicitly truncated game. Cutoff payoff is current commitment utility; no '
                   'approximation to original-game terminal value or claim of a unique equilibrium.'))
        return self

    def audit_native(self):
        """Independently verify every branch, cutoff score and propagated value."""
        values = [None] * len(self.entries)
        edges = terminal_leaves = cutoff_leaves = 0
        for index in reversed(range(len(self.entries))):
            entry = self.entries[index]
            if entry.actor is None:
                if entry.node.pending is not None:
                    raise AssertionError('A bounded leaf discarded an outstanding OFFER response')
                if entry.node.state.is_terminal:
                    terminal_leaves += 1
                else:
                    if (entry.node.state.turn_index != self.cutoff or
                            index not in self.cutoff_leaves):
                        raise AssertionError('Nonterminal leaf is not at the declared cutoff')
                    cutoff_leaves += 1
                commitments = entry.node.state.snapshot_commitments()
                satisfied = np.zeros(len(self.rules.spec.goals), dtype=float)
                for goal in self.rules.spec.goals:
                    met = sum(commitments[a.player_id][a.action_id] == 1
                              for a in goal.required_actions)
                    satisfied[goal.goal_id] = (float(met == len(goal.required_actions))
                                              if goal.binary else met / len(goal.required_actions))
                values[index] = np.asarray([
                    [sum(preference * score for preference, score in zip(row, satisfied))
                     for row in world] for world in self.worlds], dtype=float)
                np.testing.assert_allclose(entry.payoff, values[index], atol=TOL, rtol=0)
            else:
                if entry.actions != self.rules.actions(entry.node):
                    raise AssertionError('Bounded enumeration omitted a native legal action')
                if len(entry.children) != len(entry.actions):
                    raise AssertionError('A native action branch is missing')
                for action, child in zip(entry.actions, entry.children):
                    expected = self.rules._apply(entry.node, action)
                    actual = self.entries[child].node
                    if (expected.state.public_state() != actual.state.public_state() or
                            expected.pending != actual.pending or
                            expected.worlds != actual.worlds or
                            expected.state.private_results != actual.state.private_results):
                        raise AssertionError('Bounded transition diverged from native rules')
                    edges += 1
                values[index] = np.einsum('aw,awp->wp', self.policy[index],
                                         np.stack([values[c] for c in entry.children]))
            if self.values is not None:
                np.testing.assert_allclose(self.values[index], values[index], atol=TOL, rtol=0)
        if cutoff_leaves != len(self.cutoff_leaves):
            raise AssertionError('Cutoff leaf accounting changed')
        return dict(nodes=len(self.entries), edges=edges,
                    terminal_leaves=terminal_leaves, cutoff_leaves=cutoff_leaves,
                    **self.horizon, native_transitions_match=True,
                    native_action_set_complete=True, leaf_payoffs_match=True,
                    all_values_match=self.values is not None,
                    leaf_objective=LEAF_OBJECTIVE)
