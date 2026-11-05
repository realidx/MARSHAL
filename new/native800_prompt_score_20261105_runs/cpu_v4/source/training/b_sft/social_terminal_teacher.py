"""Versioned small-game audit teacher; no training entry point.

Ordinary actions use native BENAC-P transitions. The only new rule is one
public INVESTIGATE per game, consuming a proposal turn and revealing one slot.
All players share one objective and one full-terminal contingent policy.
The teacher is the policy selected by a fixed, versioned solving procedure.
Synchronous improvement removes player-sweep ordering. Uniqueness among all
possible solutions is neither claimed nor required for this reference model.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import hashlib

import numpy as np
from training.b_sft.decision_policy import optimal_indices, VERSION as OBJECTIVE_VERSION

from training.b_sft.shared_teacher import native, Entry, SharedWindow, SearchLimit, TOL
from training.b_sft.social_b_random_window import normalized_weights
from training.b_sft.social_b_oracle import NAMES, canonical
from benac_p.endgame import Node
from benac_p.state import GameState
from benac_p.endgame_diagnose import decode_action

VERSION = 'social-terminal-selected-policy-response-only-v3'
GAME_VERSION = 'social-public-investigate-v1'


@dataclass(frozen=True)
class Investigate:
    player: int
    goal: int

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in (self.player,self.goal)):
            raise ValueError('Investigation player and goal must be nonnegative integer IDs')

    def to_dict(self):
        return dict(action='INVESTIGATE', player=self.player, goal=self.goal)


@dataclass(frozen=True)
class Revelation:
    value: int

    def to_dict(self):
        return dict(revealed_preference=NAMES[self.value])


@dataclass(frozen=True)
class InvestigationEvent:
    turn_index: int
    proposer_id: int
    player: int
    goal: int
    value: int
    commitments_after: tuple

    def to_dict(self):
        return dict(turn_index=self.turn_index, proposer_id=self.proposer_id,
                    action='INVESTIGATE', player=self.player, goal=self.goal,
                    revealed_preference=NAMES[self.value],
                    commitments_after=[list(r) for r in self.commitments_after])


class InvestigationState(GameState):
    investigation_used = False
    investigation_enabled = True

    def public_state(self):
        return dict(super().public_state(), investigation_remaining=int(self.investigation_enabled and not self.investigation_used),
                    investigation_budget_scope='one shared use in the entire game')


class InvestigationRules:
    """Explicit audit variant, retaining native goals, offers and round rotation.

    Unknown means not settled by the public catalogue or a direct revelation.
    Inferring a slot from behavior does not change physical action legality.
    Querying one's own already-known preferences is never legal.
    """
    def __init__(self, raw, *, enabled=True):
        if raw['game'].get('menu_enabled', False):
            raise ValueError('The new game variant excludes MENU')
        self.base, self.worlds, self.catalogues = native(raw)
        self.spec = self.base.spec
        self.enabled = enabled

    def initial(self):
        state = InvestigationState(self.spec)
        state.investigation_enabled = self.enabled
        return Node(state, self.worlds)

    def public_game(self):
        return dict(self.spec.to_dict(), variant=GAME_VERSION, menu_enabled=False,
                    investigate=dict(enabled=self.enabled, budget=1, budget_scope='entire game, shared by all players',
                        cost='Consumes the current proposal turn without changing commitments',
                        result='Environment publicly reveals one selected preference',
                        targets='Another player, a slot varying in the public catalogue and not already directly revealed'))

    def actor(self, node):
        return self.base.actor(node)

    def actions(self, node):
        ordinary = self.base.actions(node)
        if not self.enabled or node.pending is not None or node.state.is_terminal or node.state.investigation_used:
            return ordinary
        actor = self.actor(node)
        extra = tuple(Investigate(p, g) for p in range(self.spec.n_players) if p != actor
                      for g in range(len(self.spec.goals))
                      if len({w[p][g] for w in node.worlds}) > 1)
        return ordinary + extra

    def _apply(self, node, action):
        if isinstance(action, Investigate):
            raise ValueError('INVESTIGATE requires an explicit environment revelation')
        return self.base._apply(node, action)

    def reveal(self, node, action, value):
        if action not in self.actions(node) or not isinstance(action, Investigate):
            raise ValueError('Illegal investigation')
        remaining = tuple(w for w in node.worlds if w[action.player][action.goal] == value)
        if not remaining:
            raise ValueError('Revelation outside the public catalogue support')
        state = node.state.clone()
        state.transcript.append(InvestigationEvent(state.turn_index, self.actor(node),
            action.player, action.goal, value, state.snapshot_commitments()))
        state.investigation_used = True
        state.turn_index += 1
        return Node(state, remaining)

    def step(self, node, action, *, realized_world=None):
        """Execution bridge: only the environment supplies the private world.

        Agents submit the investigation target, never the answer. Ordinary
        actions keep native offer/response semantics. No solver is required.
        """
        if isinstance(action,Investigate):
            if realized_world is None:
                raise ValueError('Environment private world required for investigation')
            world=tuple(tuple(row) for row in realized_world)
            if world not in node.worlds:
                raise ValueError('Environment world incompatible with public catalogue or revelations')
            if action not in self.actions(node):
                raise ValueError('Illegal investigation')
            return self.reveal(node,action,world[action.player][action.goal])
        return self._apply(node,action)

    def terminal_payoffs(self, node, realized_world):
        """Actual outcome reward inputs; independent of teacher policy and belief."""
        world=tuple(tuple(row) for row in realized_world)
        if not node.state.is_terminal or world not in node.worlds:
            raise ValueError('A terminal state and compatible environment world are required')
        return tuple(float(np.dot(row,node.state.goal_satisfaction())) for row in world)


class TerminalWindow(SharedWindow):
    """Full remaining game, chance branches conditioned on the fixed world.

    Actor -1 is environment revelation, not a strategic player. World-indexed
    chance masks reveal exactly the true slot; no private matrix is read.
    """
    def __init__(self, rules, root, worlds, *, world_weights=None,
                 max_nodes=30000, seconds=20, max_sweeps=64, initialization='uniform', audit_update_order=None):
        if root.state.is_terminal:
            raise ValueError('No decision after terminal')
        self.chance = {}
        self.initialization = initialization
        self.audit_update_order = audit_update_order
        super().__init__(rules, root, worlds, turns=len(rules.spec.round_robin)-root.state.turn_index,
                         max_nodes=max_nodes, seconds=seconds, max_sweeps=max_sweeps)
        self.world_weights = normalized_weights(
            np.ones(self.w) if world_weights is None else world_weights, self.w)
        if audit_update_order is not None and sorted(audit_update_order) != list(range(self.n)):
            raise ValueError('Diagnostic order must be a player permutation')
        self.possible_masks = [np.array([w in e.node.worlds for w in self.worlds]) for e in self.entries]
        self.policy = []
        for i, e in enumerate(self.entries):
            if e.actor is None:
                self.policy.append(None)
            elif e.actor == -1:
                self.policy.append(self.chance[i])
            else:
                probs = np.full((len(e.actions), self.w), 1 / len(e.actions))
                if initialization in ('first', 'last'):
                    probs[:] = 0
                    probs[0 if initialization == 'first' else -1] = 1
                elif initialization != 'uniform':
                    raise ValueError('Unknown initialization')
                self.policy.append(probs)

    def _grow(self, node):
        self._check()
        if len(self.entries) >= self.max_nodes:
            raise SearchLimit('Terminal teacher public-tree node budget exceeded')
        i = len(self.entries)
        self.entries.append(None)
        if node.state.is_terminal:
            payoff = np.einsum('wpg,g->wp', self.types, node.state.goal_satisfaction())
            self.entries[i] = Entry(node, None, (), (), payoff)
            return i
        actions = self.rules.actions(node)
        children = []
        for a in actions:
            if isinstance(a, Investigate):
                if len(self.entries) >= self.max_nodes:
                    raise SearchLimit('Terminal teacher public-tree node budget exceeded')
                ci = len(self.entries)
                self.entries.append(None)
                outcomes = tuple(Revelation(v) for v in (1, 0, -1)
                                 if any(w[a.player][a.goal] == v for w in node.worlds))
                descendants = tuple(self._grow(self.rules.reveal(node, a, o.value)) for o in outcomes)
                self.entries[ci] = Entry(node, -1, outcomes, descendants)
                self.chance[ci] = np.array([[float(w[a.player][a.goal] == o.value)
                                            for w in self.worlds] for o in outcomes])
                children.append(ci)
            else:
                children.append(self._grow(self.rules._apply(node, a)))
        self.entries[i] = Entry(node, self.rules.actor(node), actions, tuple(children))
        return i

    def evaluate(self, policy=None):
        policy = self.policy if policy is None else policy
        values = [None] * len(self.entries)
        for i in reversed(range(len(self.entries))):
            if i % 256 == 0:
                self._check()
            e = self.entries[i]
            values[i] = e.payoff if e.actor is None else np.einsum(
                'aw,awp->wp', policy[i], np.stack([values[c] for c in e.children]))
        return values

    def reference_identity(self):
        """Fingerprint the context and full selected policy, not one sampled path."""
        root = self.entries[0].node
        digest = hashlib.sha256()
        digest.update(canonical(dict(version=VERSION, game=self.rules.public_game(),
            root=root.state.public_state(), pending=None if root.pending is None else root.pending.to_dict(),
            worlds=self.worlds, weights=self.world_weights.tolist(), initialization=self.initialization,
            update_order=self.audit_update_order)).encode())
        checks = 0
        for i, entry in enumerate(self.entries):
            if entry.actor is None:
                continue
            if entry.actor >= 0:
                for group in self.groups[entry.actor]:
                    ids = group[self.possible_masks[i][group]]
                    if len(ids):
                        if not np.allclose(self.policy[i][:,ids],self.policy[i][:,ids[:1]],atol=TOL,rtol=0):
                            raise SearchLimit('Selected policy leaks another player private information')
                        checks += 1
            digest.update(canonical(dict(index=i,actor=entry.actor,children=entry.children,
                actions=[a.to_dict() for a in entry.actions],probabilities=self.policy[i].tolist())).encode())
        return digest.hexdigest(), checks

    def response(self, player):
        reach = [None] * len(self.entries)
        reach[0] = self.world_weights.copy()
        for i, e in enumerate(self.entries):
            if i % 256 == 0:
                self._check()
            for ai, child in enumerate(e.children):
                reach[child] = reach[i] if e.actor == player else reach[i] * self.policy[i][ai]
        values = [None] * len(self.entries)
        updates = {}
        for i in reversed(range(len(self.entries))):
            if i % 256 == 0:
                self._check()
            e = self.entries[i]
            if e.actor is None:
                values[i] = e.payoff
                continue
            av = np.stack([values[c] for c in e.children])
            if e.actor != player:
                values[i] = np.einsum('aw,awp->wp', self.policy[i], av)
                continue
            probs = np.full((len(e.actions), self.w), 1 / len(e.actions))
            for group in self.groups[player]:
                ids = group[self.possible_masks[i][group]]
                if not len(ids):
                    continue
                weights = reach[i][ids]
                if weights.sum() == 0:
                    weights = self.world_weights[ids]
                means = np.einsum('awp,w->ap', av[:, ids], weights / weights.sum())
                final = optimal_indices(means, player, e.actions, TOL)
                probs[:, ids] = 0
                probs[np.ix_(final, ids)] = 1 / len(final)
            updates[i] = probs
            values[i] = np.einsum('aw,awp->wp', probs, av)
        return updates, values[0]

    def solve(self):
        seen = set()
        for sweep in range(self.max_sweeps):
            self._check()
            # Default: all responses read the same old profile. An explicit
            # order is for diagnosing cycles/multiplicity, never a fallback.
            new = list(self.policy)
            old_policy = list(self.policy)
            order = range(self.n) if self.audit_update_order is None else self.audit_update_order
            for p in order:
                updates, _ = self.response(p)
                for i, probs in updates.items():
                    new[i] = probs
                if self.audit_update_order is not None:
                    self.policy = list(new)
            changed = any(not np.array_equal(old, nxt) for old, nxt in zip(old_policy, new))
            self.policy = new
            if not changed:
                self.values = self.evaluate()
                checks = []
                for p in range(self.n):
                    _, br = self.response(p)
                    for ids in self.groups[p]:
                        base = np.average(self.values[0][ids], axis=0, weights=self.world_weights[ids])
                        best = np.average(br[ids], axis=0, weights=self.world_weights[ids])
                        own = float(best[p]-base[p])
                        social = float(best.sum()-best[p]-base.sum()+base[p])
                        if own > TOL:
                            raise SearchLimit('Stable profile failed independent deviation check')
                        checks.append(dict(player=p, own_gain=own, others_gain=social))
                policy_hash, information_checks = self.reference_identity()
                self.certificate = dict(version=VERSION, objective_version=OBJECTIVE_VERSION, verified=True, uniqueness_proven=False,
                    uniqueness_required=False, label_reference='selected_contingent_policy',
                    policy_sha256=policy_hash, information_set_checks=information_checks,
                    diagnostic_policy=self.initialization!='uniform' or self.audit_update_order is not None,
                    terminal=True, nodes=len(self.entries), sweeps=sweep+1,
                    initialization=self.initialization, type_checks=checks,
                    audit_update_order=self.audit_update_order,
                    selection=('Synchronous best-response iteration' if self.audit_update_order is None else 'Diagnostic ordered best-response iteration')+'; uniform residual optimal ties',
                    selection_contract='Default model initializes all legal choices uniformly and updates every player synchronously until the full policy is stable. Execute this selected policy throughout the episode. No alternative initialization or order is a silent fallback.',
                    scope='Labels are conditional on this reproducibly selected full-terminal teacher, not universal consequences of rationality or a unique solution of the game')
                return self
            key = b''.join(p.tobytes() for p in self.policy if p is not None)
            if key in seen:
                raise SearchLimit('Synchronous terminal policy iteration cycled; no label')
            seen.add(key)
        raise SearchLimit('Synchronous terminal policy did not converge; no label')


class TerminalEpisode:
    """Execute the same certified contingent policy; never replan each event."""
    def __init__(self, raw, prefix=(), *, investigate=True, **budgets):
        if raw.get('history'):
            raise ValueError('Use an explicit setup prefix')
        self.raw = deepcopy(raw)
        self.rules = InvestigationRules(raw, enabled=investigate)
        root = self.rules.initial()
        self.setup = deepcopy(list(prefix))
        for a in prefix:
            if a.get('action') == 'INVESTIGATE':
                # Explicit public environment intervention, not a choice whose
                # likelihood is evaluated under the newly selected policy.
                if set(a) != {'action', 'player', 'goal', 'revealed_preference'}:
                    raise ValueError('Investigation setup requires one public revealed preference')
                values = {name: value for value, name in NAMES.items()}
                if a['revealed_preference'] not in values:
                    raise ValueError('Invalid setup revelation')
                root = self.rules.reveal(root, Investigate(a['player'], a['goal']), values[a['revealed_preference']])
            else:
                root = self.rules._apply(root, decode_action(a))
        # Public setup revelations already eliminate incompatible worlds. They
        # cannot re-enter the prior when this remaining-game teacher is selected.
        self.tree = TerminalWindow(self.rules, root, root.worlds, **budgets).solve()
        self.index = 0
        self.weights = self.tree.world_weights.copy()
        self.events = []

    def choices(self, own):
        e = self.tree.entries[self.index]
        if e.actor in (None, -1):
            raise ValueError('Not a player decision')
        ids = np.array([i for i, w in enumerate(self.tree.worlds)
                        if w[e.actor] == tuple(own) and self.weights[i] > 0])
        if not len(ids):
            raise ValueError('Own type outside current support')
        policy = self.tree.policy[self.index][:, ids]
        if not np.allclose(policy, policy[:, :1], atol=TOL, rtol=0):
            raise AssertionError('Policy reads another player private preference')
        av = np.array([np.average(self.tree.values[c][ids], axis=0,
                                 weights=self.weights[ids]) for c in e.children])
        return dict(actor=e.actor, actions=[a.to_dict() for a in e.actions],
                    probabilities=policy[:, 0].tolist(), values=av.tolist(),
                    admissible_actions=[a.to_dict() for a, p in zip(e.actions, policy[:, 0]) if p > 0])

    def observe(self, action, *, revelation=None):
        e = self.tree.entries[self.index]
        lookup = {canonical(a.to_dict()): i for i, a in enumerate(e.actions)}
        if canonical(action) not in lookup or e.actor in (None, -1):
            raise ValueError('Illegal player action')
        ai = lookup[canonical(action)]
        weights = self.weights * self.tree.policy[self.index][ai]
        if not weights.sum():
            raise ValueError('Action incompatible with the declared teacher; no reset')
        child = e.children[ai]
        chance = self.tree.entries[child]
        if chance.actor == -1:
            matches = [i for i, o in enumerate(chance.actions) if o.value == revelation]
            if len(matches) != 1:
                raise ValueError('An investigation requires a valid explicit revelation')
            oi = matches[0]
            weights = weights * self.tree.policy[child][oi]
            child = chance.children[oi]
        elif revelation is not None:
            raise ValueError('Ordinary actions cannot include a revelation')
        if not weights.sum():
            raise ValueError('Revelation incompatible with current evidence')
        weights /= weights.sum()
        # Commit only after validating both the action and the revelation.
        self.weights, self.index = weights, child
        self.events.append(dict(action=deepcopy(action), revelation=revelation))

    def belief(self, player, goal, *, observer=None, own=None):
        weights = self.weights.copy()
        if observer is not None:
            if own is None:
                raise ValueError('Observer own preferences required')
            weights *= np.array([w[observer] == tuple(own) for w in self.tree.worlds])
        if not weights.sum():
            raise ValueError('Incompatible observer information')
        weights /= weights.sum()
        marginal = {NAMES[v]: float(sum(p for p, w in zip(weights, self.tree.worlds)
                                      if w[player][goal] == v)) for v in (1, 0, -1)}
        possible = [name for name, p in marginal.items() if p > 0]
        leaders = [name for name in possible if marginal[name] >= max(marginal.values())-TOL]
        return dict(possible_preferences=possible, favored=leaders[0] if len(leaders) == 1 else 'undetermined',
                    preference_weights=marginal)
