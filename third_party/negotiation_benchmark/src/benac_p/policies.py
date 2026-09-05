"""Policy interfaces and small reference policies for BENAC-P v0."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from benac_p.observations import PlayerObservation
from benac_p.schema import (
    Offer,
    OfferProposal,
    PassProposal,
    ResponseAction,
)

Proposal = PassProposal | OfferProposal


@runtime_checkable
class PlayerPolicy(Protocol):
    """Minimal interface shared by LLMs, scripted agents, and arbitrary policies."""

    def propose(self, observation: PlayerObservation) -> Proposal:
        """Choose PASS or one legal full-vector offer."""

    def respond(self, observation: PlayerObservation, proposal: Offer) -> ResponseAction:
        """Accept or reject a proposal addressed to this player."""


@dataclass
class RandomPolicy:
    """A deterministic-seedable policy useful for smoke tests and baselines."""

    seed: int | None = None
    pass_probability: float = 0.2
    accept_probability: float = 0.5
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.pass_probability <= 1.0:
            raise ValueError("pass_probability must be between zero and one.")
        if not 0.0 <= self.accept_probability <= 1.0:
            raise ValueError("accept_probability must be between zero and one.")
        self._rng = np.random.default_rng(self.seed)

    def propose(self, observation: PlayerObservation) -> Proposal:
        if not observation.legal_offers or self._rng.random() < self.pass_probability:
            return PassProposal()
        index = int(self._rng.integers(len(observation.legal_offers)))
        return OfferProposal(observation.legal_offers[index])

    def respond(self, observation: PlayerObservation, proposal: Offer) -> ResponseAction:
        del observation, proposal
        if self._rng.random() < self.accept_probability:
            return ResponseAction(ResponseAction.ACCEPT)
        return ResponseAction(ResponseAction.REJECT)


@dataclass
class ScriptedPolicy:
    """Replay finite proposal/response sequences, then use safe defaults."""

    proposals: Sequence[Proposal] = ()
    responses: Sequence[ResponseAction | str] = ()
    _proposal_index: int = field(default=0, init=False, repr=False)
    _response_index: int = field(default=0, init=False, repr=False)

    def propose(self, observation: PlayerObservation) -> Proposal:
        del observation
        if self._proposal_index >= len(self.proposals):
            return PassProposal()
        proposal = self.proposals[self._proposal_index]
        self._proposal_index += 1
        return proposal

    def respond(self, observation: PlayerObservation, proposal: OfferProposal) -> ResponseAction:
        del observation, proposal
        if self._response_index >= len(self.responses):
            return ResponseAction(ResponseAction.REJECT)
        response = self.responses[self._response_index]
        self._response_index += 1
        return response if isinstance(response, ResponseAction) else ResponseAction(str(response))

    def reset(self) -> None:
        self._proposal_index = 0
        self._response_index = 0
