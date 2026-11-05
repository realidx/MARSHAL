"""Public deterministic continuation, independent of equilibrium solving.

This policy maximizes immediate commitment utility, rather than terminal
utility. Its prior is conditioned on the actor's own type and own query
answers only. Public behavior is intentionally not used as Bayesian evidence.
An exact slice best response against this policy remains a different object.
"""
from copy import deepcopy
import hashlib
import json

import numpy as np

from training.b_sft.preference_contract import profile, world_weights
from training.b_sft.social_private_teacher import observed_slots


VERSION = 'fixed-myopic-v1'
TOL = 1e-9


def _stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class FixedReference:
    """A reproducible information-limited kernel over every native action.

    ``world`` is used only to deliver the current actor's own preference row
    and answers to queries that actor actually made. Predictions about a
    responder integrate hypothetical catalogue worlds under the proposer's
    information; they never use the actual responder's unobserved preference.
    """

    def __init__(self, rules, background_prior=None):
        self.rules = rules
        self.worlds = rules.worlds
        self.n, self.w = rules.spec.n_players, len(self.worlds)
        self.prior = deepcopy(background_prior if background_prior is not None else
                              getattr(rules, 'background_prior', profile('balanced')))
        self.world_weights = world_weights(self.worlds, self.prior)
        if np.any(self.world_weights <= 0):
            raise ValueError('The fixed reference requires positive catalogue support')
        self.types = np.asarray(self.worlds, dtype=float)
        self._belief_cache, self._policy_cache = {}, {}
        contract = dict(
            version=VERSION, game=rules.public_game(),
            type_catalogues={str(p): [list(row) for row in rows]
                             for p, rows in rules.catalogues.items()},
            background_prior=self.prior,
            information='Current public commitments, turn, pending offer and query targets; own preferences and own private query answers.',
            belief='Condition the frozen public prior on own preferences and own query answers. Do not condition on public behavioral choices.',
            response='Maximize own immediate commitment utility; among own-score ties maximize expected total immediate utility of other players under the responder information; then lowest native legal action index.',
            proposal='Predict the partner response using this same response rule, integrated over the proposer-information-conditioned public prior. Maximize expected own immediate commitment utility; then lowest native legal action index.',
            investigate='Investigation has the same immediate commitment utility as PASS. It stays legal and is never assigned an artificial information bonus.',
            scoring='Native binary ALL_OF or linear completion-fraction goals; all legal native offers, passes, queries and responses remain available.',
            tolerance=TOL, equilibrium=False, terminal_optimal=False)
        self.contract = contract
        self.contract_sha256 = hashlib.sha256(_stable(contract).encode()).hexdigest()
        self.certificate = dict(
            version=VERSION, reference_kind='fixed_public_policy',
            contract_sha256=self.contract_sha256, policy_sha256=self.contract_sha256,
            verified=True, equilibrium=False, terminal_optimal=False,
            verification_scope='Versioned deterministic policy contract; legality and own-information privacy by construction. No equilibrium or terminal-best-response certificate.',
            information=contract['information'], belief=contract['belief'],
            native_action_set='Unmodified native action enumeration',
            deterministic=True)

    def state_key(self, node):
        """Public physical state, including knowledge of who queried which slot.

        Query targets must be retained: prediction of a partner's response can
        depend on what that partner privately learned, even though its answer
        is unknown to the current actor. Other behavioral history is excluded.
        """
        return (node.state.turn_index, node.state.snapshot_commitments(),
                None if node.pending is None else _stable(node.pending.to_dict()),
                tuple(node.state.investigation_used),
                tuple(observed_slots(node, p) for p in range(self.n)))

    def _information(self, node, world):
        actor = self.rules.actor(node)
        if actor is None:
            raise ValueError('A terminal node has no reference action')
        own = tuple(world[actor])
        if own not in self.rules.catalogues[actor]:
            raise ValueError('Actor own preferences are outside the public catalogue')
        facts = tuple((p, g, world[p][g]) for p, g in observed_slots(node, actor))
        return actor, own, facts

    def _belief(self, actor, own, facts):
        key = actor, own, facts
        if key not in self._belief_cache:
            mask = np.asarray([w[actor] == own and all(w[p][g] == value for p, g, value in facts)
                               for w in self.worlds], dtype=bool)
            masses = self.world_weights * mask
            if masses.sum() <= 0:
                raise ValueError('Actor query facts have zero probability under the public support')
            masses /= masses.sum()
            self._belief_cache[key] = (masses, np.einsum('w,wpg->pg', masses, self.types))
        return self._belief_cache[key]

    @staticmethod
    def _first_best(scores):
        scores = np.asarray(scores, dtype=float)
        return int(np.flatnonzero(scores >= scores.max() - TOL)[0])

    def _response(self, node, actor, own, facts):
        actions = self.rules.actions(node)
        _, expected_preferences = self._belief(actor, own, facts)
        satisfaction = np.stack([self.rules._apply(node, action).state.goal_satisfaction()
                                 for action in actions])
        own_scores = satisfaction @ np.asarray(own, dtype=float)
        best = np.flatnonzero(own_scores >= own_scores.max() - TOL)
        others = expected_preferences.sum(axis=0) - expected_preferences[actor]
        social_scores = satisfaction @ others
        best = best[social_scores[best] >= social_scores[best].max() - TOL]
        return int(best[0])

    def action_index(self, node, world):
        actor, own, facts = self._information(node, world)
        key = self.state_key(node), actor, own, facts
        if key in self._policy_cache:
            return self._policy_cache[key]
        if node.pending is not None:
            chosen = self._response(node, actor, own, facts)
        else:
            actions = self.rules.actions(node)
            baseline = float(np.dot(own, node.state.goal_satisfaction()))
            masses, _ = self._belief(actor, own, facts)
            scores = []
            for action in actions:
                # PASS and INVESTIGATE leave immediate commitments unchanged.
                if action.to_dict().get('action') != 'OFFER':
                    scores.append(baseline)
                    continue
                pending = self.rules._apply(node, action)
                responses = self.rules.actions(pending)
                outcomes = [float(np.dot(own, self.rules._apply(pending, response).state.goal_satisfaction()))
                            for response in responses]
                expected = 0.0
                for wi in np.flatnonzero(masses > 0):
                    # These are hypothetical catalogue worlds, not actual
                    # unobserved preferences from the input world.
                    response = self.action_index(pending, self.worlds[wi])
                    expected += masses[wi] * outcomes[response]
                scores.append(expected)
            chosen = self._first_best(scores)
        self._policy_cache[key] = chosen
        return chosen

    def probabilities(self, node):
        actions = self.rules.actions(node)
        if self.rules.actor(node) is None:
            raise ValueError('A terminal node has no reference policy')
        result = np.zeros((len(actions), self.w), dtype=float)
        for wi, world in enumerate(self.worlds):
            result[self.action_index(node, world), wi] = 1.0
        return result
