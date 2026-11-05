"""Small-game private-investigation environment and selected-policy teacher.

Public action trees retain ALL worlds. A query changes the investigator's
world partition, never the public world support. This avoids separate public
nodes for an answer that other players cannot observe. Teaching catalogues
are explicit assumptions; this module is not the outcome self-play runner.
"""
from collections import defaultdict
from dataclasses import dataclass
from copy import deepcopy
import hashlib

import numpy as np
from training.b_sft.decision_policy import optimal_indices

from training.b_sft.shared_teacher import native, Entry, TOL, SearchLimit
from training.b_sft.social_terminal_teacher import TerminalWindow, Investigate
from training.b_sft.social_b_oracle import canonical, NAMES
from benac_p.state import GameState
from benac_p.endgame import Node
from benac_p.endgame_diagnose import decode_action

VERSION = 'social-private-selected-policy-response-only-v2'
GAME_VERSION = 'social-private-investigate-per-player-v1'


@dataclass(frozen=True)
class PrivateQueryEvent:
    turn_index: int
    proposer_id: int
    player: int
    goal: int
    commitments_after: tuple

    def to_dict(self):
        return dict(turn_index=self.turn_index, proposer_id=self.proposer_id,
                    action='INVESTIGATE', player=self.player, goal=self.goal,
                    commitments_after=[list(r) for r in self.commitments_after])


class PrivateState(GameState):
    def __init__(self, spec):
        super().__init__(spec)
        self.investigation_used = (False,) * spec.n_players
        # Immutable records permit native shallow state cloning without aliases.
        self.private_results = ((),) * spec.n_players

    def public_state(self):
        return dict(super().public_state(),
                    investigation_remaining_by_player=[int(not v) for v in self.investigation_used],
                    investigation_budget_scope='one use per player per game')


class PrivateInvestigationRules:
    def __init__(self, raw):
        if raw['game'].get('menu_enabled', False):
            raise ValueError('Private investigation variant excludes MENU')
        self.base, self.worlds, self.catalogues = native(raw, allow_linear=True)
        self.spec = self.base.spec

    def initial(self):
        return Node(PrivateState(self.spec), self.worlds)

    def public_game(self):
        return dict(self.spec.to_dict(), variant=GAME_VERSION, menu_enabled=False,
            investigate=dict(budget=1, budget_scope='per player per game',
                cost='Consumes the current proposal turn; commitments do not change',
                action_visibility='Query actor and target are public',
                result_visibility='Only the investigator receives the true preference',
                targets='Any goal preference of another player, including already known or irrelevant preferences'))

    def actor(self, node):
        return self.base.actor(node)

    def actions(self, node):
        ordinary = self.base.actions(node)
        actor = self.actor(node)
        if actor is None or node.pending is not None or node.state.investigation_used[actor]:
            return ordinary
        return ordinary + tuple(Investigate(p, g) for p in range(self.spec.n_players) if p != actor
                                for g in range(len(self.spec.goals)))

    def _apply(self, node, action):
        """Public tree transition. Actual private delivery is handled by step."""
        if not isinstance(action, Investigate):
            return self.base._apply(node, action)
        if action not in self.actions(node):
            raise ValueError('Illegal investigation')
        actor = self.actor(node)
        state = node.state.clone()
        state.transcript.append(PrivateQueryEvent(state.turn_index, actor, action.player,
                                                 action.goal, state.snapshot_commitments()))
        state.investigation_used = tuple(v or p == actor for p, v in enumerate(state.investigation_used))
        state.turn_index += 1
        return Node(state, node.worlds)

    def step(self, node, action, *, realized_world=None):
        if not isinstance(action, Investigate):
            return self._apply(node, action)
        if realized_world is None:
            raise ValueError('Environment must supply the true world')
        world = tuple(tuple(r) for r in realized_world)
        if world not in self.worlds:
            raise ValueError('World outside this teaching game')
        actor = self.actor(node)
        child = self._apply(node, action)
        result = (action.player, action.goal, world[action.player][action.goal])
        child.state.private_results = tuple(r + (result,) if p == actor else r
                                            for p, r in enumerate(child.state.private_results))
        return child

    def observation(self, node, player, own):
        if str(player) not in self.catalogues and player not in self.catalogues:
            raise ValueError('Unknown observer')
        if tuple(own) not in self.catalogues[player]:
            raise ValueError('Own preferences outside catalogue')
        return dict(player=player, own_preferences=[NAMES[v] for v in own],
            public_state=node.state.public_state(),
            private_results=[dict(player=p, goal=g, preference=NAMES[v])
                             for p, g, v in node.state.private_results[player]],
            pending_offer=None if node.pending is None else node.pending.to_dict())

    def terminal_payoffs(self, node, realized_world):
        world = tuple(tuple(r) for r in realized_world)
        if not node.state.is_terminal or world not in self.worlds:
            raise ValueError('Compatible terminal world required')
        return tuple(float(np.dot(row, node.state.goal_satisfaction())) for row in world)


def observed_slots(node, player):
    return tuple((ev.player, ev.goal) for ev in node.state.transcript
                 if isinstance(ev, PrivateQueryEvent) and ev.proposer_id == player)


class PrivateWindow(TerminalWindow):
    def __init__(self, rules, root, worlds, **budgets):
        super().__init__(rules, root, worlds, **budgets)
        if np.any(self.world_weights <= 0):
            raise ValueError('Remove zero-support worlds before constructing the private teacher')
        self.information_groups = {}
        for i, entry in enumerate(self.entries):
            if entry.actor is None:
                continue
            p = entry.actor
            slots = observed_slots(entry.node, p)
            groups = defaultdict(list)
            for wi, world in enumerate(self.worlds):
                groups[(world[p], tuple(world[q][g] for q, g in slots))].append(wi)
            self.information_groups[i] = [np.array(ids) for ids in groups.values()]
        # Root deviation checks also condition on private information from setup.
        self.groups = {}
        for p in range(self.n):
            groups = defaultdict(list)
            for wi, world in enumerate(self.worlds):
                groups[(world[p], tuple(world[q][g] for q, g in observed_slots(root, p)))].append(wi)
            self.groups[p] = [np.array(ids) for ids in groups.values()]

    def _grow(self, node):
        self._check()
        if len(self.entries) >= self.max_nodes:
            raise SearchLimit('Private teacher public-tree node budget exceeded')
        i = len(self.entries)
        self.entries.append(None)
        if node.state.is_terminal:
            payoff = np.einsum('wpg,g->wp', self.types, node.state.goal_satisfaction())
            self.entries[i] = Entry(node, None, (), (), payoff)
        else:
            actions = self.rules.actions(node)
            children = tuple(self._grow(self.rules._apply(node, a)) for a in actions)
            self.entries[i] = Entry(node, self.rules.actor(node), actions, children)
        return i

    def response(self, player):
        # Counterfactual reach excludes this player's own past choices. Its
        # private results enter information sets, not a global posterior mask.
        reach = [None] * len(self.entries)
        reach[0] = self.world_weights.copy()
        for i, entry in enumerate(self.entries):
            if i % 256 == 0:
                self._check()
            for ai, child in enumerate(entry.children):
                reach[child] = reach[i] if entry.actor == player else reach[i] * self.policy[i][ai]
        values = [None] * len(self.entries)
        updates = {}
        for i in reversed(range(len(self.entries))):
            if i % 256 == 0:
                self._check()
            entry = self.entries[i]
            if entry.actor is None:
                values[i] = entry.payoff
                continue
            av = np.stack([values[c] for c in entry.children])
            if entry.actor != player:
                values[i] = np.einsum('aw,awp->wp', self.policy[i], av)
                continue
            probs = np.zeros((len(entry.actions), self.w))
            for ids in self.information_groups[i]:
                weights = reach[i][ids]
                if weights.sum() == 0:
                    # Explicit off-path convention: initial prior conditioned
                    # on own type AND the private facts actually received.
                    weights = self.world_weights[ids]
                means = np.einsum('awp,w->ap', av[:, ids], weights / weights.sum())
                final = optimal_indices(means, player, entry.actions, TOL)
                probs[np.ix_(final, ids)] = 1/len(final)
            updates[i] = probs
            values[i] = np.einsum('aw,awp->wp', probs, av)
        return updates, values[0]

    def reference_identity(self):
        checks = 0
        for i, groups in self.information_groups.items():
            for ids in groups:
                if not np.allclose(self.policy[i][:, ids], self.policy[i][:, ids[:1]], atol=TOL, rtol=0):
                    raise SearchLimit('Policy leaks a private result or another player type')
                checks += 1
        header = dict(version=VERSION, game=self.rules.public_game(),
            root=self.entries[0].node.state.public_state(),
            pending=None if self.entries[0].node.pending is None else self.entries[0].node.pending.to_dict(),
            worlds=self.worlds, prior=self.world_weights.tolist(), initialization=self.initialization,
            update_order=self.audit_update_order)
        digest = hashlib.sha256(canonical(header).encode())
        for i, e in enumerate(self.entries):
            if e.actor is not None:
                digest.update(canonical(dict(actor=e.actor, actions=[a.to_dict() for a in e.actions],
                                             probabilities=self.policy[i].tolist())).encode())
        return digest.hexdigest(), checks

    def solve(self):
        super().solve()
        self.certificate.update(version=VERSION, game_version=GAME_VERSION,
            information='Public action history + own preferences + own private query answers; perfect recall',
            off_path='Initial prior conditioned on own preferences and own private answers; no actual-world fallback')
        return self


class PrivateEpisode:
    def __init__(self, raw, prefix=(), **budgets):
        if raw.get('history'):
            raise ValueError('Use explicit legal setup')
        self.raw = deepcopy(raw)
        self.rules = PrivateInvestigationRules(raw)
        root = self.rules.initial()
        for action in prefix:
            if 'revealed_preference' in action:
                raise ValueError('Private setup query has no public answer')
            a = Investigate(action['player'], action['goal']) if action.get('action') == 'INVESTIGATE' else decode_action(action)
            root = self.rules._apply(root, a)
        if raw.get('background_prior'):
            from training.b_sft.preference_contract import world_weights
            if 'world_weights' in budgets:raise ValueError('Two prior definitions')
            budgets['world_weights']=world_weights(root.worlds,raw['background_prior'])
        self.tree = PrivateWindow(self.rules, root, root.worlds, **budgets).solve()
        self.index = 0
        self.weights = self.tree.world_weights.copy()  # Public evidence only.

    def _weights(self, player, own, private_results):
        node = self.tree.entries[self.index].node
        facts = tuple(tuple(r) for r in private_results)
        if tuple((p, g) for p, g, v in facts) != observed_slots(node, player):
            raise ValueError('Supply exactly this observer private query records')
        weights = self.weights * np.array([w[player] == tuple(own) and
            all(w[p][g] == v for p, g, v in facts) for w in self.tree.worlds])
        if weights.sum() <= 0:
            raise ValueError('Observer facts incompatible with history')
        return weights/weights.sum()

    def belief(self, player, goal, *, observer, own, private_results=()):
        weights = self._weights(observer, own, private_results)
        marginal = {NAMES[v]: float(sum(p for p, w in zip(weights, self.tree.worlds) if w[player][goal] == v))
                    for v in (1, 0, -1)}
        possible = [name for name, p in marginal.items() if p > 0]
        leaders = [name for name in possible if marginal[name] >= max(marginal.values())-TOL]
        return dict(possible_preferences=possible, favored=leaders[0] if len(leaders) == 1 else 'undetermined',
                    preference_weights=marginal)

    def choices(self, own, private_results=()):
        entry = self.tree.entries[self.index]
        if entry.actor is None:
            raise ValueError('No action after terminal')
        weights = self._weights(entry.actor, own, private_results)
        ids = np.flatnonzero(weights > 0)
        policy = self.tree.policy[self.index][:, ids]
        np.testing.assert_allclose(policy, np.repeat(policy[:, :1], len(ids), axis=1), atol=TOL, rtol=0)
        av = [np.average(self.tree.values[c], axis=0, weights=weights).tolist() for c in entry.children]
        return dict(actor=entry.actor, actions=[a.to_dict() for a in entry.actions],
                    values=av, probabilities=policy[:, 0].tolist(),
                    admissible_actions=[a.to_dict() for a, p in zip(entry.actions, policy[:, 0]) if p > 0])

    def observe(self, action):
        entry = self.tree.entries[self.index]
        lookup = {canonical(a.to_dict()): i for i, a in enumerate(entry.actions)}
        if canonical(action) not in lookup:
            raise ValueError('Illegal public action')
        ai = lookup[canonical(action)]
        weights = self.weights * self.tree.policy[self.index][ai]
        if weights.sum() <= 0:
            raise ValueError('Action incompatible with selected teacher; no reset')
        self.weights = weights/weights.sum()
        self.index = entry.children[ai]


def audit_native(tree):
    """Recompute every transition, goal conjunction and continuation value."""
    values = [None]*len(tree.entries)
    edges = leaves = 0
    for i in reversed(range(len(tree.entries))):
        e = tree.entries[i]
        if e.actor is None:
            assert e.node.state.is_terminal
            c = e.node.state.snapshot_commitments()
            satisfied = [float(all(c[a.player_id][a.action_id] for a in g.required_actions)) if g.binary else sum(c[a.player_id][a.action_id] for a in g.required_actions)/len(g.required_actions) for g in tree.rules.spec.goals]
            values[i] = np.array([[sum(v*s for v, s in zip(row, satisfied)) for row in w] for w in tree.worlds])
            leaves += 1
        else:
            for a, child in zip(e.actions, e.children):
                actual = tree.entries[child].node
                expected = tree.rules._apply(e.node, a)
                assert expected.state.public_state() == actual.state.public_state()
                assert expected.pending == actual.pending and expected.worlds == actual.worlds
                edges += 1
            values[i] = sum(tree.policy[i][ai, :, None]*values[c] for ai, c in enumerate(e.children))
        np.testing.assert_allclose(values[i], tree.values[i], atol=TOL, rtol=0)
    return dict(edges=edges, leaves=leaves, all_values_match=True)
