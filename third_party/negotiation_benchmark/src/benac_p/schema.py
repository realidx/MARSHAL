"""Data structures for the BENAC-P v0 game.

The schema deliberately separates the complete internal game specification
from the public game objects shown to policies.  Private preferences live on
``GameSpec`` but are never included in a default ``PlayerObservation``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import numpy as np


class Preference(str, Enum):
    """Qualitative per-player preference over a goal."""

    WANT = "WANT"
    NEUTRAL = "NEUTRAL"
    AVOID = "AVOID"


PREFERENCE_TO_VALUE = {
    Preference.WANT: 1,
    Preference.NEUTRAL: 0,
    Preference.AVOID: -1,
}
VALUE_TO_PREFERENCE = {value: key for key, value in PREFERENCE_TO_VALUE.items()}


@dataclass(frozen=True, order=True)
class ActionRef:
    """A public reference to one player's commitment."""

    player_id: int
    action_id: int

    def to_dict(self) -> dict[str, int]:
        return {"player_id": self.player_id, "action_id": self.action_id}


@dataclass(frozen=True)
class Goal:
    """A public binary goal and the commitments required to complete it."""

    goal_id: int
    required_actions: tuple[ActionRef, ...]
    binary: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_actions", tuple(self.required_actions))
        if self.goal_id < 0:
            raise ValueError("goal_id must be non-negative.")
        if not self.required_actions:
            raise ValueError("A goal must require at least one action.")
        if not self.binary:
            raise ValueError("BENAC-P v0 supports binary goals only.")
        if len(set(self.required_actions)) != len(self.required_actions):
            raise ValueError("A goal cannot contain duplicate action requirements.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "binary": self.binary,
            "required_actions": [action.to_dict() for action in self.required_actions],
        }


@dataclass(frozen=True)
class Offer:
    """A bilateral offer represented by final target action vectors.

    The vectors follow the original BENAC convention: they contain the full
    desired binary action vectors, not only the newly added bits.  The state
    validates that existing commitments remain set and computes the 0->1
    delta internally.
    """

    partner_id: int
    proposer_action: tuple[int, ...]
    partner_action: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposer_action", tuple(self.proposer_action))
        object.__setattr__(self, "partner_action", tuple(self.partner_action))

    def to_dict(self) -> dict[str, Any]:
        return {
            "partner_id": self.partner_id,
            "proposer_action": list(self.proposer_action),
            "partner_action": list(self.partner_action),
        }


@dataclass(frozen=True)
class PassProposal:
    """The proposer declines to make an offer for the current turn."""

    action: str = field(default="PASS", init=False)

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action}


@dataclass(frozen=True)
class OfferProposal:
    """The proposer selects a partner and submits one bilateral offer."""

    offer: Offer
    action: str = field(default="OFFER", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, **self.offer.to_dict()}


@dataclass(frozen=True)
class ResponseAction:
    """The selected partner responds to an offer."""

    value: str

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"

    def __post_init__(self) -> None:
        normalized = str(self.value).upper()
        if normalized not in {self.ACCEPT, self.REJECT}:
            raise ValueError("ResponseAction must be ACCEPT or REJECT.")
        object.__setattr__(self, "value", normalized)

    @property
    def accepted(self) -> bool:
        return self.value == self.ACCEPT

    def to_dict(self) -> dict[str, str]:
        return {"response": self.value}


@dataclass(frozen=True)
class PublicEvent:
    """One completed public turn in the negotiation transcript."""

    turn_index: int
    proposer_id: int
    action: str
    partner_id: int | None
    offer: Offer | None
    response: str | None
    commitments_after: tuple[tuple[int, ...], ...]
    invalid_action: bool = False

    def __post_init__(self) -> None:
        if self.action not in {"PASS", "OFFER"}:
            raise ValueError("PublicEvent action must be PASS or OFFER.")
        if self.action == "PASS" and (self.partner_id is not None or self.offer is not None):
            raise ValueError("PASS events cannot contain a partner or offer.")
        if self.action == "OFFER" and (self.partner_id is None or self.offer is None):
            raise ValueError("OFFER events require a partner and offer.")
        if self.response is not None and self.response not in {
            ResponseAction.ACCEPT,
            ResponseAction.REJECT,
        }:
            raise ValueError("PublicEvent response must be ACCEPT or REJECT.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "proposer_id": self.proposer_id,
            "action": self.action,
            "partner_id": self.partner_id,
            "offer": None if self.offer is None else self.offer.to_dict(),
            "response": self.response,
            "commitments_after": [list(row) for row in self.commitments_after],
            "invalid_action": self.invalid_action,
        }


@dataclass(frozen=True)
class GameSpec:
    """Complete immutable specification of one BENAC-P game instance."""

    n_players: int
    n_actions_per_player: tuple[int, ...]
    goals: tuple[Goal, ...]
    private_preferences: np.ndarray
    round_robin: tuple[int, ...]
    max_changes: int
    seed: int
    forbidden_actions: np.ndarray | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "n_actions_per_player", tuple(int(value) for value in self.n_actions_per_player))
        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "round_robin", tuple(int(value) for value in self.round_robin))
        if self.n_players < 2:
            raise ValueError("BENAC-P requires at least two players.")
        if len(self.n_actions_per_player) != self.n_players:
            raise ValueError("n_actions_per_player must contain one value per player.")
        if any(actions <= 0 for actions in self.n_actions_per_player):
            raise ValueError("Every player must have at least one action.")
        if not self.goals:
            raise ValueError("A game must contain at least one goal.")
        if any(goal.goal_id != idx for idx, goal in enumerate(self.goals)):
            raise ValueError("Goal IDs must be contiguous and start at zero.")
        expected_pref_shape = (self.n_players, len(self.goals))
        preferences = np.asarray(self.private_preferences)
        if preferences.shape != expected_pref_shape:
            raise ValueError(
                "private_preferences must have shape "
                f"{expected_pref_shape}, got {preferences.shape}."
            )
        if not np.all(np.isin(preferences, [-1, 0, 1])):
            raise ValueError("private_preferences must contain only -1, 0, or 1.")
        preferences = preferences.astype(np.int8)
        preferences = preferences.copy()
        preferences.setflags(write=False)
        object.__setattr__(self, "private_preferences", preferences)

        expected_turns = len(self.round_robin)
        if expected_turns == 0:
            raise ValueError("round_robin cannot be empty.")
        if any(player < 0 or player >= self.n_players for player in self.round_robin):
            raise ValueError("round_robin contains an out-of-range player id.")
        if self.max_changes < 1:
            raise ValueError("max_changes must be at least one.")

        shape = (self.n_players, max(self.n_actions_per_player))
        if self.forbidden_actions is not None:
            forbidden = np.asarray(self.forbidden_actions)
            if forbidden.shape != shape:
                raise ValueError(
                    f"forbidden_actions must have shape {shape}, got {forbidden.shape}."
                )
            if not np.all(np.isin(forbidden, [0, 1])):
                raise ValueError("forbidden_actions must contain only 0 or 1 values.")
            forbidden = forbidden.astype(np.uint8)
            forbidden = forbidden.copy()
            forbidden.setflags(write=False)
            object.__setattr__(self, "forbidden_actions", forbidden)

        for goal in self.goals:
            players = set()
            for action in goal.required_actions:
                if action.player_id < 0 or action.player_id >= self.n_players:
                    raise ValueError("Goal requirement contains an invalid player id.")
                if action.action_id < 0 or action.action_id >= self.n_actions_per_player[action.player_id]:
                    raise ValueError("Goal requirement contains an invalid action id.")
                players.add(action.player_id)
            if len(players) < 2:
                raise ValueError("Every BENAC-P v0 goal must involve at least two players.")

    @property
    def n_goals(self) -> int:
        return len(self.goals)

    @property
    def n_rounds(self) -> int:
        return len(self.round_robin) // self.n_players

    @property
    def n_actions(self) -> int:
        return max(self.n_actions_per_player)

    def preference_labels(self, player_id: int) -> tuple[Preference, ...]:
        if player_id < 0 or player_id >= self.n_players:
            raise IndexError(f"Unknown player_id={player_id}.")
        return tuple(VALUE_TO_PREFERENCE[int(value)] for value in self.private_preferences[player_id])

    def public_dict(self) -> dict[str, Any]:
        """Return only game data that is public to every player."""
        return self.to_dict(include_private=False)

    def to_dict(self, *, include_private: bool = False) -> dict[str, Any]:
        """Serialize the spec, optionally including evaluation-only labels."""

        result: dict[str, Any] = {
            "n_players": self.n_players,
            "n_actions_per_player": list(self.n_actions_per_player),
            "goals": [goal.to_dict() for goal in self.goals],
            "round_robin": list(self.round_robin),
            "max_changes": self.max_changes,
            "seed": self.seed,
            "forbidden_actions": (
                None
                if self.forbidden_actions is None
                else self.forbidden_actions.astype(int).tolist()
            ),
        }
        if include_private:
            result["private_preferences"] = self.private_preferences.astype(int).tolist()
            result["metadata"] = dict(self.metadata)
        return result


# Public type aliases kept near the schema so custom policies need not import
# the implementation modules just to annotate their action signatures.
Proposal = PassProposal | OfferProposal
Response = ResponseAction
