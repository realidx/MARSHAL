"""Enumerative Bayesian filtering for a small BENAC-P diagnostic game.

Exact means enumeration of the specified finite prior and known SoftProgress
kernels, up to floating-point arithmetic. No true partner preferences, game
seed, solver values or future events are inputs to the filter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
import math
from typing import Mapping

import numpy as np

from benac_p.controlled import SoftProgressPolicy
from benac_p.observations import PlayerObservation, build_player_observation
from benac_p.schema import (
    GameSpec, MenuOffer, Offer, OfferProposal, PassProposal, Preference, ResponseAction,
)
from benac_p.state import GameState


LABELS = (Preference.WANT, Preference.NEUTRAL, Preference.AVOID)


class BeliefLimitError(ValueError):
    """Requested enumeration exceeds the explicit candidate budget."""


@dataclass(frozen=True)
class BeliefState:
    """Joint preference hypotheses, indexed by partner_ids; log weights canonical."""

    partner_ids: tuple[int, ...]
    hypotheses: tuple[tuple[tuple[Preference, ...], ...], ...]
    log_probabilities: tuple[float, ...]

    def __post_init__(self):
        object.__setattr__(self, "partner_ids", tuple(self.partner_ids))
        object.__setattr__(self, "hypotheses", tuple(
            tuple(tuple(Preference(v) for v in row) for row in h) for h in self.hypotheses
        ))
        object.__setattr__(self, "log_probabilities", tuple(float(v) for v in self.log_probabilities))
        if not self.hypotheses or len(self.hypotheses) != len(self.log_probabilities):
            raise ValueError("A belief requires aligned, non-empty support and log weights.")
        if not self.partner_ids or len(set(self.partner_ids)) != len(self.partner_ids):
            raise ValueError("partner_ids must be non-empty and unique.")
        if not self.hypotheses[0]:
            raise ValueError("A hypothesis requires partner preference rows.")
        n_goals = len(self.hypotheses[0][0])
        if not n_goals or any(
            len(h) != len(self.partner_ids)
            or any(len(row) != n_goals or any(v not in LABELS for v in row) for row in h)
            for h in self.hypotheses
        ):
            raise ValueError("Hypotheses must contain aligned partner preference rows.")
        logs = np.asarray(self.log_probabilities)
        if np.any(np.isnan(logs)) or not np.isclose(np.logaddexp.reduce(logs), 0, atol=1e-10):
            raise ValueError("Log probabilities must be normalized.")

    @property
    def probabilities(self) -> tuple[float, ...]:
        return tuple(math.exp(value) for value in self.log_probabilities)

    @property
    def entropy(self) -> float:
        return -math.fsum(
            p * logp for p, logp in zip(self.probabilities, self.log_probabilities) if p > 0
        )

    def marginals(self) -> dict:
        n_goals = len(self.hypotheses[0][0])
        result = {
            f"P{player}": {f"G{g}": {label.value: 0.0 for label in LABELS} for g in range(n_goals)}
            for player in self.partner_ids
        }
        for hypothesis, probability in zip(self.hypotheses, self.probabilities):
            for player, row in zip(self.partner_ids, hypothesis):
                for goal, label in enumerate(row):
                    result[f"P{player}"][f"G{goal}"][label.value] += probability
        return result

    def to_dict(self, *, include_joint: bool = True) -> dict:
        result = {
            "representation": "joint-preferences-v1",
            "partner_ids": list(self.partner_ids),
            "support_size": len(self.hypotheses),
            "entropy_nats": self.entropy,
            "marginals": self.marginals(),
        }
        if include_joint:
            result["joint"] = [
                {"preferences": [[label.value for label in row] for row in h], "log_probability": logp}
                for h, logp in zip(self.hypotheses, self.log_probabilities)
            ]
        return result


@dataclass(frozen=True)
class ConditionalPreferencePrior:
    """v0 IID preference sampling, conditioned on ego and both rejection rules.

    Public goals/schedule are assumed independent of the preference draw.
    Additional hidden-state/solver-based dataset filtering is not modeled.
    """

    preference_probs: tuple[float, float, float] = (0.4, 0.2, 0.4)
    max_candidates: int = 100_000

    def __post_init__(self):
        probs = tuple(float(p) for p in self.preference_probs)
        if len(probs) != 3 or any(not math.isfinite(p) or p < 0 for p in probs):
            raise ValueError("preference_probs must be three finite nonnegative values.")
        if not math.isclose(sum(probs), 1.0, abs_tol=1e-12):
            raise ValueError("preference_probs must sum to one.")
        if not isinstance(self.max_candidates, int) or self.max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer.")
        object.__setattr__(self, "preference_probs", probs)

    def specification(self) -> dict:
        return {
            "version": "benac-p-v0-conditional-prior-v1",
            "probability_order": [label.value for label in LABELS],
            "preference_probs": list(self.preference_probs),
            "constraints": ["each player has a WANT", "each goal has a non-NEUTRAL player"],
            "conditioning": "ego preferences; independent public goals and schedule",
            "max_candidates": self.max_candidates,
        }

    def initialize(self, obs: PlayerObservation) -> BeliefState:
        own = obs.own_preferences
        if own is None or len(own) != len(obs.goals):
            raise ValueError("Prior requires the ego's complete own preferences.")
        weights = dict(zip(LABELS, self.preference_probs))
        if Preference.WANT not in own or any(weights.get(v, 0) == 0 for v in own):
            raise ValueError("Ego information has zero probability under the specified generator.")
        partners = tuple(i for i in range(obs.n_players) if i != obs.player_id)
        candidates = 3 ** (len(partners) * len(own))
        if candidates > self.max_candidates:
            raise BeliefLimitError(
                f"Prior needs up to {candidates} candidates, above max_candidates={self.max_candidates}; "
                "reduce goals/players for exact diagnostics. No approximation was substituted."
            )
        rows = [
            row for row in product(LABELS, repeat=len(own))
            if Preference.WANT in row and all(weights[v] > 0 for v in row)
        ]
        row_logs = {row: math.fsum(math.log(weights[v]) for v in row) for row in rows}
        hypotheses, logs = [], []
        for hypothesis in product(rows, repeat=len(partners)):
            if any(
                own[g] == Preference.NEUTRAL and all(row[g] == Preference.NEUTRAL for row in hypothesis)
                for g in range(len(own))
            ):
                continue
            hypotheses.append(hypothesis)
            logs.append(math.fsum(row_logs[row] for row in hypothesis))
        if not logs:
            raise ValueError("No partner hypotheses satisfy the conditional prior.")
        normalizer = float(np.logaddexp.reduce(logs))
        return BeliefState(partners, tuple(hypotheses), tuple(value - normalizer for value in logs))


def condition_belief(belief: BeliefState, likelihoods) -> tuple[BeliefState, float]:
    """Bayes update shared by the online filter and planning observation branches.

    Returns the normalized belief and log predictive probability of the event.
    The caller must not apply this to an ego intervention.
    """
    likelihoods = np.asarray(likelihoods, dtype=float)
    if likelihoods.shape != (len(belief.hypotheses),) or np.any(
        ~np.isfinite(likelihoods) | (likelihoods < 0) | (likelihoods > 1)
    ):
        raise ValueError("Likelihoods must align with support and lie in [0,1].")
    with np.errstate(divide="ignore"):
        logs = np.array(belief.log_probabilities) + np.log(likelihoods)
    log_predictive = float(np.logaddexp.reduce(logs))
    if not math.isfinite(log_predictive):
        raise ValueError("Observed action has zero probability under the belief and kernel.")
    return replace(belief, log_probabilities=tuple(logs - log_predictive)), log_predictive


class ExactBayesFilter:
    """Streaming proposal/response updates plus idempotent observation replay.

    Only SoftProgressPolicy is supported in this version. Its fixed, own-row
    kernel permits caching likelihoods per distinct candidate preference row.
    """

    def __init__(
        self, observation: PlayerObservation, *,
        prior: ConditionalPreferencePrior | FinitePreferencePrior | None = None,
        partner_policies: Mapping[int, SoftProgressPolicy] | None = None,
    ):
        self.ego_id = observation.player_id
        self.prior_model = prior or ConditionalPreferencePrior()
        self.prior = self.prior_model.initialize(observation)
        self.belief = self.prior
        self._identity = self._observation_identity(observation)
        # Build a public-only shadow engine. Dummy private values are never evidence.
        self._state = GameState(GameSpec(
            n_players=observation.n_players,
            n_actions_per_player=observation.n_actions_per_player,
            goals=observation.goals,
            private_preferences=np.zeros((observation.n_players, len(observation.goals)), dtype=np.int8),
            round_robin=observation.round_robin, max_changes=observation.max_changes,
            forbidden_actions=observation.forbidden_actions, seed=0, menu_enabled=observation.menu_enabled,
        ))
        policies = partner_policies if partner_policies is not None else {
            i: SoftProgressPolicy() for i in self.prior.partner_ids
        }
        if set(policies) != set(self.prior.partner_ids):
            raise ValueError("Specify one controlled policy for each non-ego partner.")
        self._policies = {}
        for player, policy in policies.items():
            if type(policy) is not SoftProgressPolicy:
                raise TypeError("ExactBayesFilter v1 supports SoftProgressPolicy kernels only.")
            # Freeze the experiment's kernel parameters; never use policy sampling seeds.
            self._policies[player] = SoftProgressPolicy(
                seed=0, temperature=policy.temperature,
                progress_weight=policy.progress_weight, uniform_mix=policy.uniform_mix,
            )
        self._pending: Offer | MenuOffer | None = None
        self.updates: list[dict] = []
        self.log_evidence = 0.0
        self.synchronize(observation)

    @staticmethod
    def _observation_identity(obs):
        return (
            obs.player_id, obs.n_players, obs.n_actions_per_player, obs.goals,
            obs.max_changes, obs.forbidden_actions, obs.round_robin, obs.own_preferences, obs.menu_enabled,
        )

    @property
    def turn_index(self):
        return self._state.turn_index

    @property
    def pending_offer(self):
        return self._pending

    def specification(self) -> dict:
        return {
            "filter_version": "exact-bayes-v1", "ego_id": self.ego_id,
            "prior": self.prior_model.specification(),
            "partner_policies": {str(i): p.specification() for i, p in self._policies.items()},
            "own_actions": "interventions, not likelihood evidence",
        }

    def _condition(self, actor: int, action, *, response: bool = False):
        log_predictive = None
        if actor != self.ego_id:
            obs = build_player_observation(
                self._state, actor, mode="public",
                pending_proposer_id=self._state.current_proposer() if response else None,
                pending_offer=self._pending if response else None,
            )
            column = self.belief.partner_ids.index(actor)
            row_likelihood = {}
            for row in {h[column] for h in self.belief.hypotheses}:
                candidate = replace(obs, own_preferences=row)
                policy = self._policies[actor]
                row_likelihood[row] = (
                    policy.response_probability(candidate, self._pending, action) if response
                    else policy.proposal_probability(candidate, action)
                )
            likelihoods = np.array([row_likelihood[h[column]] for h in self.belief.hypotheses])
            self.belief, log_predictive = condition_belief(self.belief, likelihoods)
            self.log_evidence += log_predictive
        self.updates.append({
            "turn_index": self.turn_index, "phase": "response" if response else "proposal",
            "actor_id": actor, "action": action.to_dict(),
            "is_evidence": actor != self.ego_id, "log_predictive_probability": log_predictive,
            "entropy_nats": self.belief.entropy,
        })

    def observe_proposal(self, proposal: PassProposal | OfferProposal) -> BeliefState:
        actor = self._state.current_proposer()
        if actor is None or self._pending is not None:
            raise ValueError("Expected a new proposal at an active turn, not a duplicate/pending action.")
        if isinstance(proposal, OfferProposal):
            self._state.validate_offer(proposal.offer)
        elif not isinstance(proposal, PassProposal):
            raise TypeError("Proposal must be PassProposal or OfferProposal.")
        self._condition(actor, proposal)
        if isinstance(proposal, OfferProposal):
            self._pending = proposal.offer
        else:
            self._state.apply_pass()
        return self.belief

    def observe_response(self, response: ResponseAction | str) -> BeliefState:
        if self._pending is None:
            raise ValueError("No pending offer: response is out of order or already consumed.")
        response = response if isinstance(response, ResponseAction) else ResponseAction(response)
        self._state.validate_response(self._pending, response)
        self._condition(self._pending.partner_id, response, response=True)
        self._state.resolve_offer(self._pending, response)
        self._pending = None
        return self.belief

    def synchronize(self, obs: PlayerObservation) -> BeliefState:
        """Consume only unseen history and pending proposal; reject inconsistent input atomically."""
        if self._observation_identity(obs) != self._identity:
            raise ValueError("Observation belongs to a different game or ego information state.")
        backup = self._state.clone(), self.belief, self._pending, list(self.updates), self.log_evidence
        try:
            consumed = len(self._state.transcript)
            if tuple(obs.transcript[:consumed]) != tuple(self._state.transcript):
                raise ValueError("History is stale or disagrees with previously consumed events.")
            for event in obs.transcript[consumed:]:
                if event.invalid_action or event.turn_index != self.turn_index or event.proposer_id != self._state.current_proposer():
                    raise ValueError("Invalid/fallback or out-of-order public event cannot be Bayesian evidence.")
                proposal = PassProposal() if event.action == "PASS" else OfferProposal(event.offer)
                if self._pending is None:
                    self.observe_proposal(proposal)
                elif event.action not in {"OFFER", "MENU"} or event.offer != self._pending:
                    raise ValueError("Completed event disagrees with pending proposal.")
                if event.action in {"OFFER", "MENU"}:
                    if event.response is None:
                        raise ValueError("Completed OFFER event must include a response.")
                    self.observe_response(event.response)
                if self._state.transcript[-1] != event:
                    raise ValueError("Recorded event/commitments disagree with the legal transition.")
            if (
                obs.turn_index != self.turn_index or obs.commitments != self._state.snapshot_commitments()
                or obs.current_proposer != self._state.current_proposer()
            ):
                raise ValueError("Observation state disagrees with its history.")
            if obs.pending_offer is not None:
                if obs.pending_proposer_id not in (None, self._state.current_proposer()):
                    raise ValueError("Pending proposer disagrees with schedule.")
                if self._pending is None:
                    self.observe_proposal(OfferProposal(obs.pending_offer))
                elif self._pending != obs.pending_offer:
                    raise ValueError("Pending proposal changed before response.")
            elif self._pending is not None:
                raise ValueError("Pending offer disappeared without a completed response.")
        except Exception:
            self._state, self.belief, self._pending, self.updates, self.log_evidence = backup
            raise
        return self.belief


@dataclass(frozen=True)
class FinitePreferencePrior:
    """Explicit public finite type support for controlled diagnostic fixtures.

    This is a different prior from the IID generator-conditioned prior. Every
    participant is told its full support and weights; it is never inferred
    from the realized private preferences or generator seed.
    """

    belief: BeliefState

    def initialize(self, observation):
        expected = set(range(observation.n_players)) - {observation.player_id}
        if set(self.belief.partner_ids) != expected or len(self.belief.hypotheses[0][0]) != len(observation.goals):
            raise ValueError("Finite prior must cover all partners and goals.")
        return self.belief

    def specification(self):
        return {"version": "explicit-finite-prior-v1", "belief": self.belief.to_dict()}
