"""Perfect-information backward-induction reference solver for BENAC-P v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benac_p.schema import (
    Offer,
    OfferProposal,
    PassProposal,
    Proposal,
    ResponseAction,
)
from benac_p.state import GameState, InvalidActionError


class SolverLimitError(RuntimeError):
    """Raised when an exact solve exceeds its configured state budget."""


@dataclass(frozen=True)
class SolverResult:
    """Optimal continuation values and proposer action at one state."""

    values: tuple[int, ...]
    proposal: Proposal

    def to_dict(self) -> dict[str, Any]:
        return {"values": list(self.values), "proposal": self.proposal.to_dict()}


@dataclass(frozen=True)
class ResponseEvaluation:
    """Perfect-information response comparison for one pending offer."""

    offer: Offer
    responder_id: int
    response: ResponseAction
    accept_values: tuple[int, ...]
    reject_values: tuple[int, ...]

    @property
    def accepted(self) -> bool:
        return self.response.accepted

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer": self.offer.to_dict(),
            "responder_id": self.responder_id,
            "response": self.response.value,
            "accept_values": list(self.accept_values),
            "reject_values": list(self.reject_values),
        }


@dataclass(frozen=True)
class SolverStep:
    """One step in a deterministic optimal reference rollout."""

    turn_index: int
    proposer_id: int
    proposal: Proposal
    response: ResponseAction | None
    response_evaluation: ResponseEvaluation | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "proposer_id": self.proposer_id,
            "proposal": self.proposal.to_dict(),
            "response": None if self.response is None else self.response.value,
            "response_evaluation": (
                None
                if self.response_evaluation is None
                else self.response_evaluation.to_dict()
            ),
        }


@dataclass(frozen=True)
class SolverRollout:
    """Serializable summary of applying the solver's policy to a clone."""

    final_commitments: tuple[tuple[int, ...], ...]
    goal_satisfaction: tuple[int, ...]
    terminal_rewards: tuple[int, ...]
    transcript: tuple[Any, ...]
    steps: tuple[SolverStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_commitments": [list(row) for row in self.final_commitments],
            "goal_satisfaction": list(self.goal_satisfaction),
            "terminal_rewards": list(self.terminal_rewards),
            "transcript": [event.to_dict() for event in self.transcript],
            "steps": [step.to_dict() for step in self.steps],
        }


class PerfectInfoSolver:
    """Exact finite-horizon solver for the BENAC-P v0 mechanism.

    The solver is deliberately a reference tool, not part of the environment.
    It uses the complete private preference matrix in ``GameSpec`` and applies
    backward induction with these deterministic rules:

    * a responder accepts iff its accept continuation value is at least its
      reject continuation value (weak-improvement tie break);
    * a proposer chooses an accepted offer that maximizes its own continuation
      value;
    * PASS is the baseline and wins ties against offers, avoiding gratuitous
      irreversible commitments;
    * equal-valued offers are resolved by legal partner/offer enumeration order.

    This is the old BENAC reference logic expressed over the new public action
    protocol.  In particular, the environment never calls this solver.
    """

    def __init__(
        self,
        spec,
        *,
        max_states: int | None = None,
        tie_tolerance: float = 1e-12,
    ) -> None:
        if max_states is not None and max_states < 1:
            raise ValueError("max_states must be positive or None.")
        if tie_tolerance < 0:
            raise ValueError("tie_tolerance must be non-negative.")
        self.spec = spec
        self.max_states = max_states
        self.tie_tolerance = float(tie_tolerance)
        self._cache: dict[tuple[int, bytes], SolverResult] = {}
        self.states_solved = 0

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def clear_cache(self) -> None:
        self._cache.clear()
        self.states_solved = 0

    def state_key(self, state: GameState) -> tuple[int, bytes]:
        self._validate_state(state)
        return state.turn_index, state.commitments.tobytes()

    def _validate_state(self, state: GameState) -> None:
        if state.spec is not self.spec:
            raise ValueError("PerfectInfoSolver and GameState must share the same GameSpec object.")

    def _reserve_state(self, key: tuple[int, bytes]) -> None:
        if key in self._cache:
            return
        if self.max_states is not None and self.states_solved >= self.max_states:
            raise SolverLimitError(
                f"Exact solve exceeded max_states={self.max_states}; "
                "increase the budget or use a smaller game."
            )
        self.states_solved += 1

    def _solve_state(self, state: GameState) -> SolverResult:
        key = self.state_key(state)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._reserve_state(key)

        if state.is_terminal:
            result = SolverResult(
                values=tuple(int(value) for value in state.terminal_rewards()),
                proposal=PassProposal(),
            )
            self._cache[key] = result
            return result

        proposer_id = state.current_proposer()
        assert proposer_id is not None

        # PASS is the continuation baseline and wins ties against an offer.
        reject_state = state.clone()
        reject_state.apply_pass()
        reject_result = self._solve_state(reject_state)
        best_result = reject_result
        best_proposal: Proposal = PassProposal()

        for partner_id in state.legal_partners(proposer_id):
            for offer in state.legal_offers(partner_id, proposer_id=proposer_id):
                accepted_state = state.clone()
                accepted_state.resolve_offer(offer, ResponseAction.ACCEPT)
                accepted_result = self._solve_state(accepted_state)

                # The responder compares its own future value with rejecting.
                if accepted_result.values[partner_id] + self.tie_tolerance < reject_result.values[partner_id]:
                    continue

                if accepted_result.values[proposer_id] > best_result.values[proposer_id] + self.tie_tolerance:
                    best_result = accepted_result
                    best_proposal = OfferProposal(offer)

        result = SolverResult(values=best_result.values, proposal=best_proposal)
        self._cache[key] = result
        return result

    def solve(self, state: GameState) -> SolverResult:
        """Return the exact continuation values and current proposer action."""

        return self._solve_state(state)

    def best_proposal(self, state: GameState) -> Proposal:
        """Return only the optimal PASS/OFFER action at ``state``."""

        return self.solve(state).proposal

    def response_for_offer(
        self,
        state: GameState,
        offer: Offer,
        *,
        responder_id: int | None = None,
    ) -> ResponseEvaluation:
        """Evaluate ACCEPT/REJECT for an offer using continuation values."""

        self._validate_state(state)
        proposer_id = state.current_proposer()
        if proposer_id is None:
            raise InvalidActionError("Cannot evaluate a response at a terminal state.")
        state.validate_offer(offer, proposer_id=proposer_id)
        if responder_id is None:
            responder_id = offer.partner_id
        if responder_id != offer.partner_id:
            raise InvalidActionError("responder_id must equal offer.partner_id.")

        reject_state = state.clone()
        reject_state.apply_pass()
        reject_result = self._solve_state(reject_state)

        accepted_state = state.clone()
        accepted_state.resolve_offer(offer, ResponseAction.ACCEPT)
        accepted_result = self._solve_state(accepted_state)
        response = (
            ResponseAction(ResponseAction.ACCEPT)
            if accepted_result.values[responder_id] + self.tie_tolerance >= reject_result.values[responder_id]
            else ResponseAction(ResponseAction.REJECT)
        )
        return ResponseEvaluation(
            offer=offer,
            responder_id=responder_id,
            response=response,
            accept_values=accepted_result.values,
            reject_values=reject_result.values,
        )

    def rollout(self, state: GameState | None = None) -> SolverRollout:
        """Apply the solver's policy to a clone and return its public trace."""

        working = GameState(self.spec) if state is None else state.clone()
        self._validate_state(working)
        steps: list[SolverStep] = []
        while not working.is_terminal:
            proposer_id = working.current_proposer()
            assert proposer_id is not None
            proposal = self.best_proposal(working)
            if isinstance(proposal, PassProposal):
                turn_index = working.turn_index
                working.apply_pass()
                steps.append(
                    SolverStep(
                        turn_index=turn_index,
                        proposer_id=proposer_id,
                        proposal=proposal,
                        response=None,
                        response_evaluation=None,
                    )
                )
                continue

            evaluation = self.response_for_offer(working, proposal.offer)
            turn_index = working.turn_index
            working.resolve_offer(proposal.offer, evaluation.response)
            steps.append(
                SolverStep(
                    turn_index=turn_index,
                    proposer_id=proposer_id,
                    proposal=proposal,
                    response=evaluation.response,
                    response_evaluation=evaluation,
                )
            )

        return SolverRollout(
            final_commitments=working.snapshot_commitments(),
            goal_satisfaction=tuple(int(value) for value in working.goal_satisfaction()),
            terminal_rewards=tuple(int(value) for value in working.terminal_rewards()),
            transcript=tuple(working.transcript),
            steps=tuple(steps),
        )

