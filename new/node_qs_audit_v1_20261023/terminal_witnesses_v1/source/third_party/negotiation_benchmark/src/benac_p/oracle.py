"""Simple rational oracle policy for controlled BENAC-P diagnostics."""

from __future__ import annotations

from benac_p.observations import PlayerObservation
from benac_p.schema import Offer, OfferProposal, PassProposal, ResponseAction
from benac_p.solver import PerfectInfoSolver
from benac_p.state import GameState


class RationalOraclePolicy:
    """A policy backed by the perfect-information reference solver.

    This policy is intentionally an evaluation/debug baseline.  The solver
    receives the complete ``GameSpec`` (including every preference row), while
    normal LLM/RL policies still receive only their observation.  ``bind`` is
    an optional runner hook; it gives the oracle the live public state without
    changing the required ``PlayerPolicy`` interface.
    """

    def __init__(
        self,
        solver: PerfectInfoSolver | None = None,
        *,
        max_states: int | None = None,
    ) -> None:
        self.solver = solver
        self.max_states = max_states
        self._state: GameState | None = None
        self._player_id: int | None = None

    def bind(self, state: GameState, player_id: int) -> None:
        """Bind this decision to the current live state and player."""

        if self.solver is None:
            self.solver = PerfectInfoSolver(state.spec, max_states=self.max_states)
        elif self.solver.spec is not state.spec:
            raise ValueError("Oracle solver and live state must share the same GameSpec object.")
        if player_id < 0 or player_id >= state.spec.n_players:
            raise ValueError(f"Unknown player_id={player_id}.")
        self._state = state
        self._player_id = player_id

    def _require_binding(self) -> tuple[GameState, int, PerfectInfoSolver]:
        if self._state is None or self._player_id is None or self.solver is None:
            raise RuntimeError("RationalOraclePolicy must be bound by GameRunner before acting.")
        return self._state, self._player_id, self.solver

    def _validate_observation(self, observation: PlayerObservation) -> None:
        _state, player_id, _solver = self._require_binding()
        if observation.player_id != player_id:
            raise ValueError(
                f"Oracle was bound to player {player_id} but received player "
                f"{observation.player_id}'s observation."
            )

    def propose(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
        self._validate_observation(observation)
        state, player_id, solver = self._require_binding()
        if state.current_proposer() != player_id:
            raise ValueError("Oracle proposer action requested outside this player's turn.")
        return solver.best_proposal(state)

    def respond(self, observation: PlayerObservation, proposal: Offer) -> ResponseAction:
        self._validate_observation(observation)
        state, player_id, solver = self._require_binding()
        evaluation = solver.response_for_offer(
            state,
            proposal,
            responder_id=player_id,
        )
        return evaluation.response


class OraclePartnerPolicy(RationalOraclePolicy):
    """Named alias for using the rational oracle as a controlled partner."""


OraclePolicy = RationalOraclePolicy
