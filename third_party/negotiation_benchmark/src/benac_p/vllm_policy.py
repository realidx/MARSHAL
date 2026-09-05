"""vLLM-backed BENAC-P player policies."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from benac_p.observations import PlayerObservation
from benac_p.schema import Offer, OfferProposal, PassProposal, ResponseAction
from benac_p.state import InvalidActionError


RETRY_FEEDBACK = (
    "Your previous response did not contain one valid game action. "
    "Choose exactly one of the available actions."
)


def _empty_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def _tool(name: str, description: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": dict(parameters),
            # With tool_choice=auto, vLLM uses this opt-in to constrain the
            # arguments while still allowing the model to emit ordinary text
            # or decide not to call a tool.
            "strict": True,
        },
    }


def _action_names(n_actions: int) -> list[str]:
    return [f"A{action_id}" for action_id in range(n_actions)]


def _player_name(player_id: int) -> str:
    return f"P{player_id}"


class VLLMPlayerPolicy:
    """Use a vLLM client for BENAC proposer and responder decisions.

    Clients exposing ``complete_with_tools`` use the canonical native
    OpenAI-compatible tool protocol.  The older ``complete``-only path is
    retained solely for the legacy ROLL in-process adapter and uses the old
    JSON-envelope protocol.

    Native decisions allow optional ordinary text before the tool call, but
    require exactly one tool call.  A missing, malformed, or illegal call is
    retried once with generic format feedback.  If the retry also fails, an
    :class:`InvalidActionError` is raised so ``GameRunner`` can either stop in
    strict mode or record an invalid fallback in non-strict mode.
    """

    def __init__(self, client: Any, *, model: str | None = None) -> None:
        if not hasattr(client, "complete"):
            raise TypeError("client must provide a complete(messages=...) method.")
        self.client = client
        self.model = model
        self.native_tools = callable(getattr(client, "complete_with_tools", None))

        # Per-policy protocol diagnostics.  These count native decision
        # attempts; GameRunner separately records final invalid transitions.
        self.decision_count = 0
        self.generation_request_count = 0
        self.first_attempt_valid_count = 0
        self.retry_count = 0
        self.retry_valid_count = 0
        self.final_invalid_count = 0
        self.last_reasoning = ""
        self.last_error = ""

    @staticmethod
    def _parse_json(text: str) -> Mapping[str, Any]:
        """Parse the legacy JSON envelope used only by the ROLL path."""

        cleaned = str(text).strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError(f"vLLM response is not JSON: {text!r}.")
            try:
                value = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(f"vLLM response is not valid JSON: {text!r}.") from exc
        if not isinstance(value, Mapping):
            raise ValueError("vLLM response JSON must be an object.")
        return value

    def _complete_legacy(self, messages: list[dict[str, str]]) -> Mapping[str, Any]:
        text = self.client.complete(
            messages,
            response_format={"type": "json_object"},
            model=self.model,
        )
        return self._parse_json(text)

    @staticmethod
    def _observation_payload(observation: PlayerObservation) -> str:
        return json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _proposer_tools(observation: PlayerObservation) -> tuple[dict[str, Any], ...]:
        tools: list[dict[str, Any]] = [
            _tool(
                "PASS",
                "Intentionally make no offer this turn.",
                _empty_parameters(),
            )
        ]
        legal_offer_partners = sorted({offer.partner_id for offer in observation.legal_offers})
        if not legal_offer_partners:
            return tuple(tools)

        max_partner_actions = max(
            observation.n_actions_per_player[partner_id]
            for partner_id in legal_offer_partners
        )
        offer_parameters = {
            "type": "object",
            "properties": {
                "partner": {
                    "type": "string",
                    "enum": [_player_name(player_id) for player_id in legal_offer_partners],
                    "description": "The player receiving this bilateral offer.",
                },
                "self_commitments": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _action_names(observation.n_actions_per_player[observation.player_id]),
                    },
                    "description": "New commitments by you, such as A0.",
                },
                "partner_commitments": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _action_names(max_partner_actions),
                    },
                    "description": "New commitments by the partner, such as A1.",
                },
            },
            "required": ["partner", "self_commitments", "partner_commitments"],
            "additionalProperties": False,
        }
        tools.append(
            _tool(
                "OFFER",
                "Offer one bilateral commitment package to one legal partner.",
                offer_parameters,
            )
        )
        return tuple(tools)

    @staticmethod
    def _responder_tools() -> tuple[dict[str, Any], ...]:
        return (
            _tool("ACCEPT", "Accept the pending offer.", _empty_parameters()),
            _tool("REJECT", "Reject the pending offer.", _empty_parameters()),
        )

    @staticmethod
    def _tool_calls(completion: Any) -> Sequence[Any]:
        if isinstance(completion, Mapping):
            calls = completion.get("tool_calls", ())
        else:
            calls = getattr(completion, "tool_calls", ())
        if calls is None:
            return ()
        if not isinstance(calls, (list, tuple)):
            raise InvalidActionError("tool_calls must be a list.")
        return calls

    @staticmethod
    def _call_name(call: Any) -> str:
        if isinstance(call, Mapping):
            if isinstance(call.get("function"), Mapping):
                return str(call["function"].get("name", ""))
            return str(call.get("name", ""))
        return str(getattr(call, "name", ""))

    @staticmethod
    def _call_arguments(call: Any) -> Mapping[str, Any] | None:
        if isinstance(call, Mapping):
            if isinstance(call.get("function"), Mapping):
                arguments = call["function"].get("arguments")
            else:
                arguments = call.get("arguments")
        else:
            arguments = getattr(call, "arguments", None)
        return arguments if isinstance(arguments, Mapping) else None

    def _native_decision(
        self,
        messages: list[dict[str, str]],
        tools: Sequence[Mapping[str, Any]],
        decode: Callable[[Any], Any],
    ) -> Any:
        complete_with_tools = getattr(self.client, "complete_with_tools", None)
        if not callable(complete_with_tools):
            raise RuntimeError("Native tool calling is not available on this vLLM client.")

        self.decision_count += 1
        for attempt in range(2):
            self.generation_request_count += 1
            completion = complete_with_tools(
                messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                model=self.model,
            )
            if isinstance(completion, Mapping):
                self.last_reasoning = str(completion.get("content", ""))
            else:
                self.last_reasoning = str(getattr(completion, "content", ""))
            try:
                calls = self._tool_calls(completion)
                if len(calls) != 1:
                    raise InvalidActionError(
                        f"Expected exactly one tool call, received {len(calls)}."
                    )
                decoded = decode(calls[0])
            except InvalidActionError as exc:
                self.last_error = str(exc)
                if attempt == 0:
                    self.retry_count += 1
                    messages = [
                        *messages,
                        {"role": "user", "content": RETRY_FEEDBACK},
                    ]
                    continue
                self.final_invalid_count += 1
                raise

            if attempt == 0:
                self.first_attempt_valid_count += 1
            else:
                self.retry_valid_count += 1
            self.last_error = ""
            return decoded

        raise AssertionError("native decision loop must return or raise")

    @staticmethod
    def _target_vector(
        current: Sequence[int],
        values: Any,
        *,
        field_name: str,
    ) -> tuple[int, ...]:
        if not isinstance(values, (list, tuple)):
            raise InvalidActionError(f"{field_name} must be an array of action names.")
        target = [int(value) for value in current]
        seen: set[int] = set()
        for value in values:
            if not isinstance(value, str) or not value.startswith("A"):
                raise InvalidActionError(f"{field_name} contains an invalid action name.")
            try:
                action_id = int(value[1:])
            except ValueError as exc:
                raise InvalidActionError(f"{field_name} contains an invalid action name.") from exc
            if value != f"A{action_id}" or action_id < 0 or action_id >= len(target):
                raise InvalidActionError(f"{field_name} contains an out-of-range action.")
            if action_id in seen:
                raise InvalidActionError(f"{field_name} contains a duplicate action.")
            seen.add(action_id)
            target[action_id] = 1
        return tuple(target)

    def _decode_proposer_call(
        self,
        call: Any,
        observation: PlayerObservation,
    ) -> PassProposal | OfferProposal:
        name = self._call_name(call).upper()
        arguments = self._call_arguments(call)
        if name == "PASS":
            if arguments is None or arguments:
                raise InvalidActionError("PASS must have an empty argument object.")
            return PassProposal()
        if name != "OFFER":
            raise InvalidActionError(f"Unknown proposer tool: {name!r}.")
        if arguments is None:
            raise InvalidActionError("OFFER arguments must be an object.")

        partner = arguments.get("partner")
        if not isinstance(partner, str) or not partner.startswith("P"):
            raise InvalidActionError("OFFER.partner must be a player name such as P1.")
        try:
            partner_id = int(partner[1:])
        except ValueError as exc:
            raise InvalidActionError("OFFER.partner must be a player name such as P1.") from exc
        if partner != _player_name(partner_id) or partner_id not in observation.legal_partners:
            raise InvalidActionError("OFFER.partner is not a legal partner in this state.")

        offer = Offer(
            partner_id=partner_id,
            proposer_action=self._target_vector(
                observation.commitments[observation.player_id],
                arguments.get("self_commitments"),
                field_name="self_commitments",
            ),
            partner_action=self._target_vector(
                observation.commitments[partner_id],
                arguments.get("partner_commitments"),
                field_name="partner_commitments",
            ),
        )
        if offer not in observation.legal_offers:
            raise InvalidActionError("OFFER is not legal in the current game state.")
        return OfferProposal(offer)

    def _decode_responder_call(self, call: Any) -> ResponseAction:
        name = self._call_name(call).upper()
        arguments = self._call_arguments(call)
        if name not in {ResponseAction.ACCEPT, ResponseAction.REJECT}:
            raise InvalidActionError(f"Unknown responder tool: {name!r}.")
        if arguments is None or arguments:
            raise InvalidActionError(f"{name} must have an empty argument object.")
        return ResponseAction(name)

    def _propose_native(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a BENAC-P negotiation player. You may optionally write concise "
                    "ordinary-text reasoning, then you must call exactly one of the available "
                    "tools. The tool call is the executable action. Do not return a standalone "
                    "JSON action. PASS means an intentional strategic decision not to make an "
                    "offer. For OFFER, list only new commitments using names such as A0; the "
                    "environment checks binding commitments, budgets, forbidden actions, and "
                    "all other legality constraints. A response without exactly one tool call is "
                    "invalid."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Here is your private observation as JSON. Other players' preferences are "
                    "not included.\n" + self._observation_payload(observation)
                ),
            },
        ]
        return self._native_decision(
            messages,
            self._proposer_tools(observation),
            lambda call: self._decode_proposer_call(call, observation),
        )

    def _respond_native(
        self,
        observation: PlayerObservation,
    ) -> ResponseAction:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a BENAC-P negotiation player responding to an offer. You may "
                    "optionally write concise ordinary-text reasoning, then you must call "
                    "exactly one available response tool: ACCEPT or REJECT. The tool call is "
                    "the executable action. Do not return a standalone JSON action. A response "
                    "without exactly one tool call is invalid. Decide using only your own "
                    "private preferences and the public observation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "The pending offer is included in pending_offer. Here is your observation "
                    "as JSON:\n" + self._observation_payload(observation)
                ),
            },
        ]
        return self._native_decision(
            messages,
            self._responder_tools(),
            self._decode_responder_call,
        )

    def propose(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
        if self.native_tools:
            return self._propose_native(observation)

        # Legacy compatibility for the ROLL in-process adapter.  This path is
        # deliberately not used by the canonical HTTP/vLLM 0.28 interface.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a BENAC-P negotiation player. Return exactly one JSON object. "
                    "Choose PASS, or OFFER with partner_id, proposer_action, and partner_action. "
                    "Action vectors are full final binary vectors, not deltas. Existing 1s must "
                    "remain 1; an offer must add at least one commitment and may add at most "
                    "max_changes per side. Empty offers are illegal; use PASS when making no offer."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Here is your private observation as JSON. Other players' preferences are "
                    "not included.\n" + self._observation_payload(observation)
                ),
            },
        ]
        try:
            result = self._complete_legacy(messages)
            action = str(result.get("action", "")).upper()
            if action == "PASS":
                return PassProposal()
            if action != "OFFER":
                raise ValueError("proposal action must be PASS or OFFER")
            source = result.get("offer", result)
            if not isinstance(source, Mapping):
                raise ValueError("OFFER must be an object")
            return OfferProposal(
                Offer(
                    partner_id=int(source["partner_id"]),
                    proposer_action=tuple(source["proposer_action"]),
                    partner_action=tuple(source["partner_action"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidActionError("vLLM proposer output is malformed.") from exc

    def respond(
        self,
        observation: PlayerObservation,
        proposal: Offer,
    ) -> ResponseAction:
        del proposal
        if self.native_tools:
            return self._respond_native(observation)

        # Legacy compatibility for the ROLL in-process adapter.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a BENAC-P negotiation player responding to an offer. Return exactly "
                    "one JSON object with response equal to ACCEPT or REJECT. Decide using only "
                    "your own private preferences and the public observation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "The pending offer is included in pending_offer. Here is your observation as "
                    "JSON:\n" + self._observation_payload(observation)
                ),
            },
        ]
        try:
            result = self._complete_legacy(messages)
            response = result.get("response", result.get("action", result.get("value")))
            if response is None:
                raise ValueError("response is missing")
            return ResponseAction(str(response))
        except (TypeError, ValueError) as exc:
            raise InvalidActionError("vLLM responder output is malformed.") from exc

    def metrics(self) -> dict[str, int | float | bool]:
        """Return protocol diagnostics for this policy instance."""

        return {
            "native_tools": self.native_tools,
            "decision_count": self.decision_count,
            "generation_request_count": self.generation_request_count,
            "first_attempt_valid_count": self.first_attempt_valid_count,
            "retry_count": self.retry_count,
            "retry_valid_count": self.retry_valid_count,
            "final_invalid_count": self.final_invalid_count,
            "raw_valid_action_rate": (
                self.first_attempt_valid_count / self.decision_count
                if self.decision_count
                else 0.0
            ),
            "after_retry_valid_action_rate": (
                (self.first_attempt_valid_count + self.retry_valid_count) / self.decision_count
                if self.decision_count
                else 0.0
            ),
        }
