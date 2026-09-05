"""Policy-facing observations for BENAC-P v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benac_p.schema import GameSpec, Goal, Offer, Preference, PublicEvent
from benac_p.state import GameState


def _player_name(player_id: int) -> str:
    return f"P{player_id}"


def _action_name(action_id: int) -> str:
    return f"A{action_id}"


def _commitment_names(row: tuple[int, ...], n_actions: int) -> list[str]:
    return [
        _action_name(action_id)
        for action_id, value in enumerate(row[:n_actions])
        if int(value) == 1
    ]


def _commitment_map(
    commitments: tuple[tuple[int, ...], ...],
    n_actions_per_player: tuple[int, ...],
) -> dict[str, list[str]]:
    return {
        _player_name(player_id): _commitment_names(
            commitments[player_id], n_actions_per_player[player_id]
        )
        for player_id in range(len(n_actions_per_player))
    }


def _goal_to_agent_dict(goal: Goal) -> dict[str, Any]:
    return {
        "goal": f"G{goal.goal_id}",
        "binary": goal.binary,
        "required_commitments": [
            f"{_player_name(action.player_id)}:{_action_name(action.action_id)}"
            for action in goal.required_actions
        ],
    }


def _offer_adds(
    current: tuple[int, ...],
    target: tuple[int, ...],
    n_actions: int,
) -> list[str]:
    return [
        _action_name(action_id)
        for action_id in range(n_actions)
        if int(current[action_id]) == 0 and int(target[action_id]) == 1
    ]


def _event_to_agent_dict(
    event: PublicEvent,
    commitments_before: tuple[tuple[int, ...], ...],
    n_actions_per_player: tuple[int, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "turn": event.turn_index,
        "proposer": _player_name(event.proposer_id),
        "action": event.action,
    }
    if event.action == "OFFER" and event.offer is not None:
        partner_id = event.offer.partner_id
        result["partner"] = _player_name(partner_id)
        result["offer"] = {
            "proposer_adds": _offer_adds(
                commitments_before[event.proposer_id],
                event.offer.proposer_action,
                n_actions_per_player[event.proposer_id],
            ),
            "partner_adds": _offer_adds(
                commitments_before[partner_id],
                event.offer.partner_action,
                n_actions_per_player[partner_id],
            ),
        }
        result["response"] = event.response
    if event.invalid_action:
        result["invalid_action"] = True
    return result


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

    def to_agent_dict(self) -> dict[str, Any]:
        """Return the compact named representation sent to an LLM policy.

        The internal observation deliberately retains matrix/full-vector
        objects because the runner and legality checks operate on those exact
        values.  The agent-facing view uses named commitments instead: this
        keeps the model focused on game reasoning rather than binary-vector
        bookkeeping.  In particular, it omits ``legal_offers`` and does not
        repeat ``commitments_after`` inside every transcript event.
        """

        transcript: list[dict[str, Any]] = []
        commitments_before = tuple(
            tuple(0 for _ in range(n_actions))
            for n_actions in self.n_actions_per_player
        )
        for event in self.transcript:
            transcript.append(
                _event_to_agent_dict(
                    event,
                    commitments_before,
                    self.n_actions_per_player,
                )
            )
            commitments_before = event.commitments_after

        forbidden_commitments = None
        if self.forbidden_actions is not None:
            forbidden_commitments = {
                _player_name(player_id): _commitment_names(
                    self.forbidden_actions[player_id],
                    self.n_actions_per_player[player_id],
                )
                for player_id in range(self.n_players)
            }

        result: dict[str, Any] = {
            "player": _player_name(self.player_id),
            "is_proposer": self.is_proposer,
            "n_players": self.n_players,
            "actions_per_player": {
                _player_name(player_id): [
                    _action_name(action_id)
                    for action_id in range(self.n_actions_per_player[player_id])
                ]
                for player_id in range(self.n_players)
            },
            "max_changes": self.max_changes,
            "forbidden_commitments": forbidden_commitments,
            "goals": [_goal_to_agent_dict(goal) for goal in self.goals],
            "current_proposer": (
                None
                if self.current_proposer is None
                else _player_name(self.current_proposer)
            ),
            "round_robin": [_player_name(player_id) for player_id in self.round_robin],
            "turn_index": self.turn_index,
            "current_commitments": _commitment_map(
                self.commitments,
                self.n_actions_per_player,
            ),
            "transcript": transcript,
            "own_preferences": (
                None
                if self.own_preferences is None
                else {
                    f"G{goal_id}": preference.value
                    for goal_id, preference in enumerate(self.own_preferences)
                }
            ),
            "legal_partners": [
                _player_name(player_id) for player_id in self.legal_partners
            ],
            "pending_offer": None,
        }
        if self.pending_offer is not None:
            proposer_id = self.pending_proposer_id
            if proposer_id is None:
                proposer_id = self.current_proposer
            if proposer_id is None:
                raise ValueError("pending_offer requires a pending proposer id.")
            partner_id = self.pending_offer.partner_id
            result["pending_offer"] = {
                "proposer": _player_name(proposer_id),
                "partner": _player_name(partner_id),
                "proposer_adds": _offer_adds(
                    self.commitments[proposer_id],
                    self.pending_offer.proposer_action,
                    self.n_actions_per_player[proposer_id],
                ),
                "you_add": _offer_adds(
                    self.commitments[partner_id],
                    self.pending_offer.partner_action,
                    self.n_actions_per_player[partner_id],
                ),
            }
        if self.all_preferences is not None:
            result["all_preferences"] = {
                _player_name(player_id): {
                    f"G{goal_id}": preference.value
                    for goal_id, preference in enumerate(preferences)
                }
                for player_id, preferences in enumerate(self.all_preferences)
            }
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
