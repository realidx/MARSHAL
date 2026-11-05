"""Discussion-only bounded oracle, reusing the native information-set solver.

No LM protocol or training entry point. Values are exact for the selected
finite-window reference policy, not an unrestricted optimal game value.
"""
from copy import deepcopy
import json

import numpy as np

from training.social_mixed.frozen.training.b_sft.shared_teacher import TOL, native, SearchLimit
from training.social_mixed.frozen.training.b_sft.social_b_random_window import RandomTieWindow, normalized_weights
VERSION = 'social-b-bounded-oracle-v4'
NAMES = {1: 'want', 0: 'neutral', -1: 'avoid'}
FAVORED_RULE = ('Retain every preference with positive support. Favor the uniquely most supported '
                'marginal preference under the declared history-likelihood model, even when other '
                'preferences remain possible. If the highest supports tie, use undetermined. '
                'Favored is a current inclination, not certainty. Do not output probabilities or counts.')


def canonical(action):
    return json.dumps(action, sort_keys=True, allow_nan=False)


class BeliefOracle:
    """Replan at each observed action; inverse filtering uses that same root.

    A uniform initial joint reference is updated by the probability of each
    autonomous action AFTER own-value and other-value maximization. Replanning
    retains these weights. This posterior is conditional on the declared oracle
    mechanism, not a calibrated model of arbitrary LM or human behavior.
    """

    def __init__(self, raw, prefix=(), *, turns=2, max_nodes=10000,
                 seconds=5, reverse_actions=False):
        self.raw = deepcopy(raw)
        if self.raw.get('history'):
            raise ValueError('Use explicit setup prefix, not untyped history')
        self.rules, self.worlds, _ = native(raw)
        self.initial_worlds = self.worlds
        self.weights = tuple(normalized_weights(np.ones(len(self.worlds)), len(self.worlds)))
        self.node = self.rules.initial()
        self.history = []
        self.events = []
        self.turns, self.max_nodes, self.seconds = turns, max_nodes, seconds
        if turns < 1:
            raise ValueError('Positive proposal-turn horizon required')
        if reverse_actions:
            original = self.rules.actions
            self.rules.actions = lambda node: tuple(reversed(original(node)))
        self._tree = None
        for action in prefix:
            self.observe(action, kind='setup')

    def solve(self):
        if self.node.state.is_terminal:
            raise ValueError('No decision after terminal')
        if self._tree is None:
            # No fallback on cycle, resource exhaustion, or solver failure.
            self._tree = RandomTieWindow(
                self.rules, self.node, self.worlds, turns=self.turns,
                max_nodes=self.max_nodes, seconds=self.seconds,
                world_weights=self.weights).solve()
        return self._tree

    @classmethod
    def replay(cls, raw, events, **budgets):
        """Infer chronologically from explicitly typed public events.

        Never condition an earlier actor on the observer's private row,
        a later support set, or eventual utility. Observer-private conditioning
        belongs in belief(), after public inverse filtering.
        """
        oracle = cls(raw, **budgets)
        for event in events:
            oracle.observe(event['action'], kind=event['kind'])
        return oracle

    def mechanism(self):
        return dict(version=VERSION, window_proposal_turns=self.turns,
                    information='Each player knows its own preferences and the public history and catalogues, not the realized private preferences of others',
                    objective='Maximize expected own window-end utility; among ties maximize expected sum of other players utilities',
                    decision_weights='Initially equal weight to each distinct joint catalogue world. Multiply by the likelihood of each observed autonomous action and normalize. Retain these cumulative weights across replanning; each actor additionally conditions on its own preferences. This is a posterior under the declared mechanism, not arbitrary-player calibration',
                    replanning='Fresh full window at every actual action',
                    continuation='Finite-window information-set policy with uniform mixing over residual ties at every node; average over all such continuations, never one random rollout. Future actual replanning may differ',
                    cutoff='Satisfied-goal utility at window end, not guaranteed terminal utility',
                    inverse='Use the historical actor own type and then-public weighted joint belief. Setup and external interventions leave weights unchanged. Impossible autonomous observations fail; excluded worlds never return. Never use a realized random seed or another player private truth',
                    ties='First maximize expected own utility, then expected sum of others utilities among own-value ties, then execute uniformly among residual ties. Observed-action likelihood is zero outside this final set and reciprocal of its size inside it',
                    favored=FAVORED_RULE)

    def choices(self, own):
        """Only the actor's private row is accepted, never a realized world."""
        tree = self.solve()
        actor = tree.entries[0].actor
        ids = [i for i, w in enumerate(self.worlds) if w[actor] == tuple(own)]
        if not ids:
            raise ValueError('Own type outside current public support')
        entry = tree.entries[0]
        weights = np.array(self.weights)[ids]
        values = [np.average(tree.values[c][ids], axis=0, weights=weights) for c in entry.children]
        primary = [float(v[actor]) for v in values]
        social = [float(sum(v) - v[actor]) for v in values]
        best = [i for i, v in enumerate(primary) if v >= max(primary) - TOL]
        final = [i for i in best if social[i] >= max(social[j] for j in best) - TOL]
        # Likelihoods used for historical inference must match the certified
        # policy whose continuation values produced this root decision.
        expected = np.zeros(len(entry.actions)); expected[final] = 1 / len(final)
        if not np.allclose(tree.policy[0][:, ids], expected[:, None], atol=TOL, rtol=0):
            raise SearchLimit('Root action set differs from certified reference policy; no label')
        return dict(actor=actor, own_type=list(own),
                    values=[dict(action=a.to_dict(), own=primary[i], others=social[i])
                            for i, a in enumerate(entry.actions)],
                    admissible_actions=[entry.actions[i].to_dict() for i in final],
                    action_probabilities=[dict(action=a.to_dict(), probability=float(expected[i]))
                                          for i, a in enumerate(entry.actions)],
                    own_optimal_actions=[entry.actions[i].to_dict() for i in best],
                    terminal_value=tree.end == len(self.rules.spec.round_robin),
                    decision_turn=self.node.state.turn_index,
                    cutoff_turn=tree.end)

    def sample_action(self, own, rng):
        """Randomness chooses execution, never the support used for inference."""
        actions = sorted(self.choices(own)['admissible_actions'], key=canonical)
        return deepcopy(rng.choice(actions))

    def observe(self, action, *, kind='partner'):
        """Atomic update; illegal/incompatible actions never erase support.

        `partner` denotes an autonomous oracle action, even for raw['ego'].
        `intervention` and initial `setup` affect state, not support or weights.
        """
        if kind not in ('partner', 'intervention', 'setup'):
            raise ValueError('Explicit event provenance required')
        if kind == 'setup' and any(e['kind'] != 'setup' for e in self.events):
            raise ValueError('Setup must be an initial contiguous prefix')
        legal = {canonical(a.to_dict()): a for a in self.rules.actions(self.node)}
        key = canonical(action)
        if key not in legal:
            raise ValueError('Illegal native action')
        actor = self.rules.actor(self.node)
        before = self.worlds
        remaining = before
        weights_before = self.weights
        weights_after = weights_before
        comparisons = []
        # Capture information BEFORE the action; later updates must not rewrite it.
        information_before = dict(
            turn=self.node.state.turn_index,
            public_state=deepcopy(self.node.state.public_state()),
            pending_offer=None if self.node.pending is None else deepcopy(self.node.pending.to_dict()),
            public_worlds=deepcopy(before), public_world_weights=list(weights_before))
        if kind == 'partner':
            allowed = {}
            likelihoods = {}
            for own in dict.fromkeys(w[actor] for w in before):
                row = self.choices(own)
                allowed[own] = key in {canonical(a) for a in row['admissible_actions']}
                likelihoods[own] = 1 / len(row['admissible_actions']) if allowed[own] else 0.0
                own_optimal = key in {canonical(a) for a in row['own_optimal_actions']}
                row['observed_action_compatible'] = allowed[own]
                row['observed_action_likelihood'] = likelihoods[own]
                row['evidence_reason'] = ('compatible' if allowed[own] else
                                          'prosocial_tie_rule' if own_optimal else
                                          'strict_self_value')
                comparisons.append(row)
            remaining = tuple(w for w in before if allowed[w[actor]])
            if not remaining:
                raise ValueError('Action incompatible with every candidate; no reset')
            unnormalized = [weight * likelihoods[w[actor]] for w, weight in zip(before, weights_before)
                            if allowed[w[actor]]]
            weights_after = tuple(normalized_weights(unnormalized, len(remaining)))
        child = self.rules._apply(self.node, legal[key])
        self.node, self.worlds, self.weights, self._tree = child, remaining, weights_after, None
        self.history.append(deepcopy(action))
        self.events.append(dict(kind=kind, actor=actor, action=deepcopy(action),
                                worlds_before=len(before), worlds_after=len(remaining),
                                information_before=information_before,
                                public_worlds_after=deepcopy(remaining),
                                public_world_weights_after=list(weights_after),
                                comparisons=comparisons))

    def joint_belief(self, *, observer=None, own=None):
        """Teacher/information handoff, never reconstructed from marginals.

        A private query does not mutate the public posterior or inform earlier
        actors. Model-facing B questions do not include these answer weights.
        """
        indices = list(range(len(self.worlds)))
        if observer is not None:
            if own is None:
                raise ValueError('Observer private row required')
            indices = [i for i in indices if self.worlds[i][observer] == tuple(own)]
        if not indices:
            raise ValueError('Observer information incompatible')
        weights = normalized_weights([self.weights[i] for i in indices], len(indices))
        return [dict(preferences=[list(row) for row in self.worlds[i]], weight=float(weight))
                for i, weight in zip(indices, weights)]

    def belief(self, player, goal, *, observer=None, own=None):
        joint = self.joint_belief(observer=observer, own=own)
        support = [NAMES[v] for v in (1, 0, -1)
                   if any(w['preferences'][player][goal] == v for w in joint)]
        marginal = {NAMES[v]: float(sum(w['weight'] for w in joint if w['preferences'][player][goal] == v))
                    for v in (1, 0, -1)}
        leaders = [name for name in support if marginal[name] >= max(marginal.values()) - TOL]
        return dict(possible_preferences=support,
                    favored=leaders[0] if len(leaders) == 1 else 'undetermined',
                    preference_weights=marginal,
                    favored_basis='Unique highest marginal posterior support; numerical ties within 1e-9 are undetermined',
                    scope='Support under the declared rolling reference mechanism')

    def verify_leaf_values(self):
        """Independent ALL_OF arithmetic, including nonterminal cutoffs."""
        tree = self.solve()
        checks = 0
        for entry in tree.entries:
            if entry.actor is not None:
                continue
            c = entry.node.state.snapshot_commitments()
            flags = [all(c[a['player_id']][a['action_id']] == 1
                         for a in g['required_actions']) for g in self.raw['game']['goals']]
            expected = [[sum(v * flag for v, flag in zip(row, flags))
                         for row in world] for world in self.worlds]
            if not np.array_equal(expected, entry.payoff):
                raise AssertionError('Leaf arithmetic mismatch')
            checks += len(self.worlds)
        return checks


def forward_fixture(*, rounds=1, deadline=False):
    reqs = [[(0, 0), (1, 0)], [(1, 1), (2, 0)],
            [(0, 0), (1, 1), (2, 0)], [(1, 0), (2, 0)],
            [(1, 0), (1, 1), (2, 0)]]
    types = {'0': [[1, 0, 1, 0, 0]],
             '1': [[1, 1, x, 0, 0] for x in (1, 0, -1)],
             '2': [[0, 1, 0, -1, -1]]}
    raw = dict(id='bounded-forward-refusal', ego=0, history=[],
               own_preferences=types['0'][0], type_catalogues=types,
               game=dict(n_players=3, n_actions_per_player=[1, 2, 1],
                         goals=[dict(goal_id=i, binary=True, required_actions=[
                             dict(player_id=p, action_id=a) for p, a in req])
                                for i, req in enumerate(reqs)],
                         round_robin=([0, 1, 2] if deadline else [0, 2, 1]) * rounds,
                         max_changes=1, menu_enabled=False))
    prefix = [dict(action='OFFER', partner_id=1, proposer_action=[1], partner_action=[0, 0]),
              dict(response='ACCEPT')]
    if deadline:
        prefix.append(dict(action='PASS'))
    prefix.append(dict(action='OFFER', partner_id=1, proposer_action=[0], partner_action=[1, 0]))
    return raw, prefix
