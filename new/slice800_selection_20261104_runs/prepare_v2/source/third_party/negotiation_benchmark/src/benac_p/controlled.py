"""Known stochastic Level-0 behavior for diagnostics, not a rational oracle.

Scores use only public state and the acting player's own preference vector.
Partial progress is a policy heuristic, never an environment reward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np

from benac_p.observations import PlayerObservation
from benac_p.schema import Offer, MenuOffer, response_actions, OfferProposal, PassProposal, ResponseAction, PREFERENCE_TO_VALUE


@dataclass
class SoftProgressPolicy:
    """Softmax over conditional-on-acceptance progress gains, with uniform noise.

    Phi(C) = sum_g V_g [S_g(C) + w * (1-S_g(C)) * completed_fraction_g].
    PASS / REJECT score zero; OFFER / ACCEPT score Phi(C_after)-Phi(C).
    On the last scheduled turn w=0, so scores use actual terminal utility.
    Proposals do not model acceptance or other players' beliefs. All parameters
    are public, fixed within an experiment, and are not hidden personality traits.
    """

    VERSION: ClassVar[str] = "soft-progress-v1"
    seed: int | None = None
    temperature: float = 0.5
    progress_weight: float = 0.5
    uniform_mix: float = 0.02
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not np.isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError("temperature must be finite and positive.")
        if not np.isfinite(self.progress_weight) or not 0 <= self.progress_weight <= 1:
            raise ValueError("progress_weight must be between zero and one.")
        if not np.isfinite(self.uniform_mix) or not 0 < self.uniform_mix <= 1:
            raise ValueError("uniform_mix must be positive and at most one.")
        self._rng = np.random.default_rng(self.seed)

    def specification(self) -> dict:
        """Public likelihood specification; seed is not partner knowledge."""
        return {
            "version": self.VERSION,
            "temperature": self.temperature,
            "progress_weight": self.progress_weight,
            "uniform_mix": self.uniform_mix,
            "potential": "sum V_g * (S_g + w * (1-S_g) * completed_fraction_g)",
            "menu_proposal_score": "max option gain (heuristic, not expected acceptance utility)",
            "menu_response_scores": "REJECT:0; CHOOSE_k: option k potential gain; joint softmax over all 3",
            "last_turn_progress_weight": 0.0,
            "scores": "PASS/REJECT: 0; OFFER/ACCEPT: Phi(C_if_accepted)-Phi(C)",
            "probabilities": "(1-uniform_mix)*softmax(scores/temperature)+uniform_mix/num_actions",
        }

    def _potential(self, obs: PlayerObservation, commitments) -> float:
        if obs.own_preferences is None:
            raise ValueError("Controlled policy requires own preferences.")
        weight = self.progress_weight if obs.turn_index + 1 < len(obs.round_robin) else 0.0
        score = 0.0
        for goal in obs.goals:
            fraction = sum(
                commitments[a.player_id][a.action_id] for a in goal.required_actions
            ) / len(goal.required_actions)
            score += PREFERENCE_TO_VALUE[obs.own_preferences[goal.goal_id]] * (
                1.0 if fraction == 1.0 else weight * fraction
            )
        return score

    def _probabilities(self, scores) -> tuple[float, ...]:
        scores = np.asarray(scores, dtype=float)
        # Subtract before dividing to avoid overflow with small temperatures.
        with np.errstate(over="ignore", under="ignore"):
            weights = np.exp((scores - scores.max()) / self.temperature)
        probabilities = (1 - self.uniform_mix) * weights / weights.sum()
        probabilities += self.uniform_mix / len(scores)
        return tuple(float(p) for p in probabilities)

    def proposal_distribution(self, obs: PlayerObservation) -> tuple:
        """Enumerate probabilities without advancing random state."""
        if not obs.is_proposer or obs.pending_offer is not None:
            raise ValueError("Expected an active proposer observation.")
        baseline = self._potential(obs, obs.commitments)
        actions = obs.legal_proposals
        scores = []
        for action in actions:
            if isinstance(action, PassProposal):
                scores.append(0.0)
            else:
                options = action.offer.offers if isinstance(action.offer, MenuOffer) else (action.offer,)
                scores.append(max(self._potential(obs, obs.commitments_if_accepted(o)) - baseline for o in options))
        return tuple(zip(actions, self._probabilities(scores)))

    def response_distribution(self, obs: PlayerObservation, offer: Offer) -> tuple:
        if (
            not obs.is_responder or offer.partner_id != obs.player_id
            or obs.pending_offer != offer or obs.current_proposer is None
            or (obs.pending_proposer_id is not None and obs.pending_proposer_id != obs.current_proposer)
        ):
            raise ValueError("Expected the matching pending offer addressed to this responder.")
        options = offer.offers if isinstance(offer, MenuOffer) else (offer,)
        baseline = self._potential(obs, obs.commitments)
        scores = [0.0] + [self._potential(obs, obs.commitments_if_accepted(o)) - baseline for o in options]
        return tuple(zip(response_actions(offer), self._probabilities(scores)))

    def proposal_probability(self, obs: PlayerObservation, action) -> float:
        return sum(p for candidate, p in self.proposal_distribution(obs) if candidate == action)

    def response_probability(self, obs: PlayerObservation, offer: Offer, action: ResponseAction) -> float:
        return sum(p for candidate, p in self.response_distribution(obs, offer) if candidate == action)

    def _sample(self, distribution):
        index = int(self._rng.choice(len(distribution), p=[p for _, p in distribution]))
        return distribution[index][0]

    def propose(self, observation: PlayerObservation):
        return self._sample(self.proposal_distribution(observation))

    def respond(self, observation: PlayerObservation, proposal: Offer) -> ResponseAction:
        return self._sample(self.response_distribution(observation, proposal))
