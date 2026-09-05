"""Mutable BENAC-P v0 state and transition rules."""

from __future__ import annotations

import copy
from itertools import combinations
from typing import Iterable

import numpy as np

from benac_p.schema import GameSpec, Offer, PublicEvent, ResponseAction


class InvalidActionError(ValueError):
    """Raised when a policy emits an action that is illegal in the state."""


class GameState:
    """The physical state of one negotiation episode.

    Preferences remain on ``spec`` and are intentionally not used by the
    transition logic.  The only mutable physical state is the commitment
    matrix, the schedule cursor, and the public transcript.
    """

    def __init__(self, spec: GameSpec) -> None:
        self.spec = spec
        self.commitments = np.zeros((spec.n_players, spec.n_actions), dtype=np.uint8)
        self.turn_index = 0
        self.transcript: list[PublicEvent] = []

    @property
    def n_players(self) -> int:
        return self.spec.n_players

    @property
    def n_actions(self) -> int:
        return self.spec.n_actions

    @property
    def is_terminal(self) -> bool:
        return self.turn_index >= len(self.spec.round_robin)

    def current_proposer(self) -> int | None:
        if self.is_terminal:
            return None
        return self.spec.round_robin[self.turn_index]

    def _require_active_turn(self) -> int:
        proposer = self.current_proposer()
        if proposer is None:
            raise InvalidActionError("The game is already terminal.")
        return proposer

    def _validate_player(self, player_id: int) -> None:
        if not isinstance(player_id, (int, np.integer)):
            raise InvalidActionError(f"player_id must be an integer, got {player_id!r}.")
        if int(player_id) < 0 or int(player_id) >= self.n_players:
            raise InvalidActionError(f"Unknown player_id={player_id}.")

    def _row_tuple(self, player_id: int) -> tuple[int, ...]:
        return tuple(int(value) for value in self.commitments[player_id, : self.spec.n_actions_per_player[player_id]])

    def snapshot_commitments(self) -> tuple[tuple[int, ...], ...]:
        return tuple(self._row_tuple(player) for player in range(self.n_players))

    def public_state(self) -> dict[str, object]:
        """Return a serializable state view without any private preferences."""

        return {
            "n_players": self.spec.n_players,
            "n_actions_per_player": list(self.spec.n_actions_per_player),
            "max_changes": self.spec.max_changes,
            "forbidden_actions": (
                None
                if self.spec.forbidden_actions is None
                else self.spec.forbidden_actions.astype(int).tolist()
            ),
            "goals": [goal.to_dict() for goal in self.spec.goals],
            "commitments": [list(row) for row in self.snapshot_commitments()],
            "round_robin": list(self.spec.round_robin),
            "turn_index": self.turn_index,
            "current_proposer": self.current_proposer(),
            "transcript": [event.to_dict() for event in self.transcript],
        }

    def goal_satisfaction(self) -> np.ndarray:
        """Return one binary completion value for every goal."""

        satisfied = np.zeros(self.spec.n_goals, dtype=np.int8)
        for goal in self.spec.goals:
            satisfied[goal.goal_id] = int(
                all(self.commitments[action.player_id, action.action_id] == 1 for action in goal.required_actions)
            )
        return satisfied

    def terminal_rewards(self) -> np.ndarray:
        """Return the additive preference-weighted goal rewards."""

        return self.spec.private_preferences.astype(np.int64) @ self.goal_satisfaction().astype(np.int64)

    def reward(self, player_id: int) -> int:
        self._validate_player(player_id)
        return int(self.terminal_rewards()[player_id])

    def legal_partners(self, proposer_id: int | None = None) -> tuple[int, ...]:
        if proposer_id is None:
            proposer_id = self.current_proposer()
        if proposer_id is None:
            return ()
        self._validate_player(proposer_id)
        return tuple(player for player in range(self.n_players) if player != proposer_id)

    def _validate_vector(self, vector: Iterable[int], player_id: int, field_name: str) -> tuple[int, ...]:
        self._validate_player(player_id)
        try:
            values = tuple(vector)
        except TypeError as exc:
            raise InvalidActionError(f"{field_name} must be an iterable binary vector.") from exc
        expected = self.spec.n_actions_per_player[player_id]
        if len(values) != expected:
            raise InvalidActionError(
                f"{field_name} for player {player_id} must have length {expected}, got {len(values)}."
            )
        if any(
            not isinstance(value, (int, np.integer))
            or isinstance(value, bool)
            or int(value) not in (0, 1)
            for value in values
        ):
            raise InvalidActionError(f"{field_name} must contain only integer 0/1 values.")
        return tuple(int(value) for value in values)

    def validate_offer(self, offer: Offer, proposer_id: int | None = None) -> tuple[int, int]:
        """Validate an offer and return its proposer/partner delta sizes."""

        current_proposer = self._require_active_turn()
        if proposer_id is None:
            proposer_id = current_proposer
        if proposer_id != current_proposer:
            raise InvalidActionError(
                f"It is player {current_proposer}'s turn, not player {proposer_id}'s turn."
            )
        if not isinstance(offer, Offer):
            raise InvalidActionError("An OFFER must contain an Offer object.")
        self._validate_player(offer.partner_id)
        if offer.partner_id == proposer_id:
            raise InvalidActionError("A proposer cannot offer to itself.")

        proposer_vector = self._validate_vector(offer.proposer_action, proposer_id, "proposer_action")
        partner_vector = self._validate_vector(offer.partner_action, offer.partner_id, "partner_action")
        deltas = []
        for player_id, target in (
            (proposer_id, proposer_vector),
            (offer.partner_id, partner_vector),
        ):
            current = self._row_tuple(player_id)
            forbidden = (
                None
                if self.spec.forbidden_actions is None
                else self.spec.forbidden_actions[player_id, : len(target)]
            )
            delta = 0
            for action_id, (was_set, desired) in enumerate(zip(current, target)):
                if was_set == 1 and desired != 1:
                    raise InvalidActionError("An offer cannot unset an existing commitment.")
                if desired == 1 and was_set == 0:
                    if forbidden is not None and int(forbidden[action_id]) == 1:
                        raise InvalidActionError(
                            f"Offer adds forbidden action ({player_id}, {action_id})."
                        )
                    delta += 1
            if delta > self.spec.max_changes:
                raise InvalidActionError(
                    f"Offer adds {delta} actions for player {player_id}; "
                    f"max_changes={self.spec.max_changes}."
                )
            deltas.append(delta)

        if sum(deltas) == 0:
            raise InvalidActionError("Empty/no-op offers are prohibited; use PASS instead.")
        return int(deltas[0]), int(deltas[1])

    def _candidate_vectors(self, player_id: int) -> tuple[tuple[int, ...], ...]:
        """Enumerate target vectors that add at most max_changes commitments."""

        current = self._row_tuple(player_id)
        available = [
            action_id
            for action_id, value in enumerate(current)
            if value == 0
            and (
                self.spec.forbidden_actions is None
                or int(self.spec.forbidden_actions[player_id, action_id]) == 0
            )
        ]
        vectors: list[tuple[int, ...]] = []
        for count in range(min(self.spec.max_changes, len(available)) + 1):
            for selected in combinations(available, count):
                vector = list(current)
                for action_id in selected:
                    vector[action_id] = 1
                vectors.append(tuple(vector))
        return tuple(vectors)

    def legal_offers(self, partner_id: int, proposer_id: int | None = None) -> tuple[Offer, ...]:
        """Enumerate all valid full-vector offers for a partner."""

        if self.is_terminal:
            return ()
        current_proposer = self._require_active_turn()
        if proposer_id is None:
            proposer_id = current_proposer
        if proposer_id != current_proposer:
            raise InvalidActionError("Only the current proposer can enumerate offers.")
        self._validate_player(partner_id)
        if partner_id == proposer_id:
            raise InvalidActionError("A proposer cannot offer to itself.")
        proposer_vectors = self._candidate_vectors(proposer_id)
        partner_vectors = self._candidate_vectors(partner_id)
        offers = []
        for proposer_vector in proposer_vectors:
            proposer_delta = sum(
                desired == 1 and current == 0
                for desired, current in zip(proposer_vector, self._row_tuple(proposer_id))
            )
            for partner_vector in partner_vectors:
                partner_delta = sum(
                    desired == 1 and current == 0
                    for desired, current in zip(partner_vector, self._row_tuple(partner_id))
                )
                if proposer_delta + partner_delta == 0:
                    continue
                offers.append(
                    Offer(
                        partner_id=partner_id,
                        proposer_action=proposer_vector,
                        partner_action=partner_vector,
                    )
                )
        return tuple(offers)

    def apply_pass(self, invalid_action: bool = False) -> PublicEvent:
        """Consume the current proposer turn without changing commitments."""

        proposer_id = self._require_active_turn()
        event = PublicEvent(
            turn_index=self.turn_index,
            proposer_id=proposer_id,
            action="PASS",
            partner_id=None,
            offer=None,
            response=None,
            commitments_after=self.snapshot_commitments(),
            invalid_action=invalid_action,
        )
        self.transcript.append(event)
        self.turn_index += 1
        return event

    def resolve_offer(
        self,
        offer: Offer,
        response: ResponseAction | str,
        invalid_action: bool = False,
    ) -> PublicEvent:
        """Resolve one validated offer and advance the schedule cursor."""

        proposer_id = self._require_active_turn()
        self.validate_offer(offer, proposer_id=proposer_id)
        normalized_response = response if isinstance(response, ResponseAction) else ResponseAction(str(response))
        if normalized_response.accepted:
            proposer_vector = self._validate_vector(offer.proposer_action, proposer_id, "proposer_action")
            partner_vector = self._validate_vector(
                offer.partner_action, offer.partner_id, "partner_action"
            )
            self.commitments[proposer_id, : len(proposer_vector)] = np.maximum(
                self.commitments[proposer_id, : len(proposer_vector)], proposer_vector
            )
            self.commitments[offer.partner_id, : len(partner_vector)] = np.maximum(
                self.commitments[offer.partner_id, : len(partner_vector)], partner_vector
            )
        event = PublicEvent(
            turn_index=self.turn_index,
            proposer_id=proposer_id,
            action="OFFER",
            partner_id=offer.partner_id,
            offer=offer,
            response=normalized_response.value,
            commitments_after=self.snapshot_commitments(),
            invalid_action=invalid_action,
        )
        self.transcript.append(event)
        self.turn_index += 1
        return event

    def clone(self) -> "GameState":
        # GameSpec is immutable and should remain shared so solvers can use
        # it as the fixed game-instance identity; mutable episode fields are
        # copied explicitly.
        cloned = copy.copy(self)
        cloned.commitments = self.commitments.copy()
        cloned.transcript = list(self.transcript)
        return cloned
