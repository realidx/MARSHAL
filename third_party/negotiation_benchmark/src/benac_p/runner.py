"""Policy-agnostic episode execution for BENAC-P v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from benac_p.observations import PlayerObservation, build_player_observation
from benac_p.policies import PlayerPolicy, Proposal
from benac_p.schema import GameSpec, Offer, OfferProposal, PassProposal, ResponseAction, PublicEvent
from benac_p.state import GameState, InvalidActionError


def _normalise_proposal(raw: Any) -> Proposal:
    if isinstance(raw, (PassProposal, OfferProposal)):
        return raw
    if not isinstance(raw, Mapping):
        raise InvalidActionError("A proposal must be PASS/OFFER or a mapping.")
    action = str(raw.get("action", "")).upper()
    if action == "PASS":
        return PassProposal()
    if action != "OFFER":
        raise InvalidActionError("Proposal action must be PASS or OFFER.")
    source = raw.get("offer", raw)
    if not isinstance(source, Mapping):
        raise InvalidActionError("An OFFER mapping must contain offer fields.")
    try:
        offer = Offer(
            partner_id=int(source["partner_id"]),
            proposer_action=tuple(source["proposer_action"]),
            partner_action=tuple(source["partner_action"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidActionError(f"Malformed OFFER: {raw!r}.") from exc
    return OfferProposal(offer)


def _normalise_response(raw: Any) -> ResponseAction:
    if isinstance(raw, ResponseAction):
        return raw
    if isinstance(raw, Mapping):
        raw = raw.get("response", raw.get("action", raw.get("value")))
    if raw is None:
        raise InvalidActionError("A response must be ACCEPT or REJECT.")
    try:
        return ResponseAction(str(raw))
    except ValueError as exc:
        raise InvalidActionError("A response must be ACCEPT or REJECT.") from exc


@dataclass(frozen=True)
class EpisodeResult:
    """Public result of one completed episode."""

    seed: int
    final_commitments: tuple[tuple[int, ...], ...]
    goal_satisfaction: tuple[int, ...]
    terminal_rewards: tuple[int, ...]
    transcript: tuple[PublicEvent, ...]
    invalid_action_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "final_commitments": [list(row) for row in self.final_commitments],
            "goal_satisfaction": list(self.goal_satisfaction),
            "terminal_rewards": list(self.terminal_rewards),
            "transcript": [event.to_dict() for event in self.transcript],
            "invalid_action_count": self.invalid_action_count,
        }


class GameRunner:
    """Run a game with any collection of proposer/responder policies."""

    def __init__(
        self,
        spec: GameSpec,
        policies: Mapping[int, PlayerPolicy] | Sequence[PlayerPolicy],
        *,
        observation_mode: str = "private",
        strict: bool = True,
    ) -> None:
        self.spec = spec
        if isinstance(policies, Mapping):
            self.policies = dict(policies)
        else:
            self.policies = {player_id: policy for player_id, policy in enumerate(policies)}
        missing = set(range(spec.n_players)) - set(self.policies)
        if missing:
            raise ValueError(f"Missing policies for players: {sorted(missing)}.")
        if observation_mode not in {"private", "public", "full"}:
            raise ValueError("observation_mode must be private, public, or full.")
        self.observation_mode = observation_mode
        self.strict = strict

    def _observation(
        self,
        state: GameState,
        player_id: int,
        *,
        pending_proposer_id: int | None = None,
        pending_offer: Offer | None = None,
    ) -> PlayerObservation:
        return build_player_observation(
            state,
            player_id,
            mode=self.observation_mode,
            pending_proposer_id=pending_proposer_id,
            pending_offer=pending_offer,
        )

    @staticmethod
    def _bind_policy(policy: PlayerPolicy, state: GameState, player_id: int) -> None:
        """Call the optional state-binding hook used by oracle policies."""

        binder = getattr(policy, "bind", None)
        if binder is not None:
            binder(state, player_id)

    def run(self, state: GameState | None = None) -> EpisodeResult:
        state = state or GameState(self.spec)
        if state.spec is not self.spec:
            raise ValueError("The supplied state must use this runner's GameSpec.")

        while not state.is_terminal:
            proposer_id = state.current_proposer()
            assert proposer_id is not None
            proposer_policy = self.policies[proposer_id]
            proposer_observation = self._observation(state, proposer_id)
            self._bind_policy(proposer_policy, state, proposer_id)
            try:
                proposal = _normalise_proposal(proposer_policy.propose(proposer_observation))
            except (InvalidActionError, TypeError, ValueError, KeyError) as exc:
                if self.strict:
                    if isinstance(exc, InvalidActionError):
                        raise
                    raise InvalidActionError(
                        f"Player {proposer_id} emitted an invalid proposal: {exc}"
                    ) from exc
                state.apply_pass(invalid_action=True)
                continue

            if isinstance(proposal, PassProposal):
                state.apply_pass()
                continue

            try:
                state.validate_offer(proposal.offer, proposer_id=proposer_id)
            except InvalidActionError:
                if self.strict:
                    raise
                state.apply_pass(invalid_action=True)
                continue

            partner_id = proposal.offer.partner_id
            responder_observation = self._observation(
                state,
                partner_id,
                pending_proposer_id=proposer_id,
                pending_offer=proposal.offer,
            )
            self._bind_policy(self.policies[partner_id], state, partner_id)
            try:
                response = _normalise_response(
                    self.policies[partner_id].respond(responder_observation, proposal.offer)
                )
                invalid_response = False
            except (InvalidActionError, TypeError, ValueError, KeyError) as exc:
                if self.strict:
                    if isinstance(exc, InvalidActionError):
                        raise
                    raise InvalidActionError(
                        f"Player {partner_id} emitted an invalid response: {exc}"
                    ) from exc
                response = ResponseAction(ResponseAction.REJECT)
                invalid_response = True
            state.resolve_offer(proposal.offer, response, invalid_action=invalid_response)

        return EpisodeResult(
            seed=int(self.spec.seed),
            final_commitments=state.snapshot_commitments(),
            goal_satisfaction=tuple(int(value) for value in state.goal_satisfaction()),
            terminal_rewards=tuple(int(value) for value in state.terminal_rewards()),
            transcript=tuple(state.transcript),
            invalid_action_count=sum(event.invalid_action for event in state.transcript),
        )


def run_episode(
    spec: GameSpec,
    policies: Mapping[int, PlayerPolicy] | Sequence[PlayerPolicy],
    *,
    observation_mode: str = "private",
    strict: bool = True,
) -> EpisodeResult:
    """Convenience wrapper around :class:`GameRunner`."""

    return GameRunner(
        spec,
        policies,
        observation_mode=observation_mode,
        strict=strict,
    ).run()
