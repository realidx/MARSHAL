"""Policy-facing observations for BENAC-P v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benac_p.schema import GameSpec, Goal, Offer, Preference, PublicEvent
from benac_p.state import GameState


@dataclass(frozen=True)
class PlayerObservation:
    """Immutable observation delivered to one policy for one decision."""

    player_id: int
    current_proposer: int | None
    n_players: int
    n_actions_per_player: tuple[int, ...]
    max_changes: int
    forbidden_actions: tuple[tuple[int, ...], ...] | None
    goals: tuple[Goal, ...]
    commitments: tuple[tuple[int, ...], ...]
    round_robin: tuple[int, ...]
    turn_index: int
    transcript: tuple[PublicEvent, ...]
    own_preferences: tuple[Preference, ...] | None
    legal_partners: tuple[int, ...]
    legal_offers: tuple[Offer, ...]
    pending_proposer_id: int | None = None
    pending_offer: Offer | None = None
    all_preferences: tuple[tuple[Preference, ...], ...] | None = None

    @property
    def is_proposer(self) -> bool:
        return self.current_proposer == self.player_id

    @property
    def is_responder(self) -> bool:
        return self.pending_offer is not None and self.pending_proposer_id != self.player_id

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "player_id": self.player_id,
            "current_proposer": self.current_proposer,
            "is_proposer": self.is_proposer,
            "n_players": self.n_players,
            "n_actions_per_player": list(self.n_actions_per_player),
            "max_changes": self.max_changes,
            "forbidden_actions": (
                None
                if self.forbidden_actions is None
                else [list(row) for row in self.forbidden_actions]
            ),
            "goals": [goal.to_dict() for goal in self.goals],
            "commitments": [list(row) for row in self.commitments],
            "round_robin": list(self.round_robin),
            "turn_index": self.turn_index,
            "transcript": [event.to_dict() for event in self.transcript],
            "own_preferences": (
                None
                if self.own_preferences is None
                else [preference.value for preference in self.own_preferences]
            ),
            "legal_partners": list(self.legal_partners),
            "legal_offers": [offer.to_dict() for offer in self.legal_offers],
            "pending_proposer_id": self.pending_proposer_id,
            "pending_offer": None if self.pending_offer is None else self.pending_offer.to_dict(),
        }
        if self.all_preferences is not None:
            result["all_preferences"] = [
                [preference.value for preference in preferences]
                for preferences in self.all_preferences
            ]
        return result


def _validate_player(spec: GameSpec, player_id: int) -> None:
    if player_id < 0 or player_id >= spec.n_players:
        raise IndexError(f"Unknown player_id={player_id}.")


def build_player_observation(
    state: GameState,
    player_id: int,
    *,
    mode: str = "private",
    pending_proposer_id: int | None = None,
    pending_offer: Offer | None = None,
) -> PlayerObservation:
    """Build a private, public, or explicit full/debug observation.

    ``private`` is the normal mode: a player sees only its own goal labels.
    ``public`` removes labels altogether.  ``full`` is an opt-in diagnostic
    view and is the only mode that exposes every player's preferences.
    """

    _validate_player(state.spec, player_id)
    if mode not in {"private", "public", "full"}:
        raise ValueError("observation mode must be private, public, or full.")
    current_proposer = state.current_proposer()
    is_current_proposer = current_proposer == player_id
    legal_partners = state.legal_partners(player_id) if is_current_proposer else ()
    legal_offers = (
        tuple(
            offer
            for partner_id in legal_partners
            for offer in state.legal_offers(partner_id, proposer_id=player_id)
        )
        if is_current_proposer
        else ()
    )
    own_preferences = (
        None if mode == "public" else state.spec.preference_labels(player_id)
    )
    all_preferences = (
        tuple(state.spec.preference_labels(other) for other in range(state.spec.n_players))
        if mode == "full"
        else None
    )
    return PlayerObservation(
        player_id=player_id,
        current_proposer=current_proposer,
        n_players=state.spec.n_players,
        n_actions_per_player=state.spec.n_actions_per_player,
        max_changes=state.spec.max_changes,
        forbidden_actions=(
            None
            if state.spec.forbidden_actions is None
            else tuple(
                tuple(int(value) for value in row)
                for row in state.spec.forbidden_actions[:, : state.spec.n_actions]
            )
        ),
        goals=state.spec.goals,
        commitments=state.snapshot_commitments(),
        round_robin=state.spec.round_robin,
        turn_index=state.turn_index,
        transcript=tuple(state.transcript),
        own_preferences=own_preferences,
        legal_partners=tuple(legal_partners),
        legal_offers=tuple(legal_offers),
        pending_proposer_id=pending_proposer_id,
        pending_offer=pending_offer,
        all_preferences=all_preferences,
    )
