"""vLLM-backed BENAC-P player policies."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from benac_p.observations import PlayerObservation
from benac_p.schema import MenuOffer, response_actions, Offer, OfferProposal, PassProposal, ResponseAction
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
        return json.dumps(observation.to_agent_dict(), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _legacy_observation_payload(observation: PlayerObservation) -> str:
        """Serialize the old ROLL-only observation without changing its contract."""

        return json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _proposer_tools(observation: PlayerObservation) -> tuple[dict[str, Any], ...]:
        tools: list[dict[str, Any]] = [
            _tool(
                "PASS",
                "Intentionally make no offer this turn. Use PASS when no legal offer adds a commitment.",
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
                    "description": (
                        "New commitments by you, such as A0. Include only actions that "
                        "are currently 0; never repeat an action that is already 1."
                    ),
                },
                "partner_commitments": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _action_names(max_partner_actions),
                    },
                    "description": (
                        "New commitments by the partner, such as A1. Include only actions "
                        "that are currently 0; never repeat an action that is already 1."
                    ),
                },
            },
            "required": ["partner", "self_commitments", "partner_commitments"],
            "additionalProperties": False,
        }
        tools.append(
            _tool(
                "OFFER",
                (
                    "Offer one bilateral commitment package to one legal partner. The offer "
                    "must add at least one new commitment across the two lists; a no-op offer "
                    "is illegal."
                ),
                offer_parameters,
            )
        )
        if observation.menu_enabled:
            tools.append(_tool("MENU", "Offer two distinct packages to the SAME partner. Only the chosen package binds immediately.", {
                "type": "object", "properties": {"options": {
                    "type": "array", "minItems": 2, "maxItems": 2, "items": offer_parameters,
                }}, "required": ["options"], "additionalProperties": False,
            }))
        return tuple(tools)

    @staticmethod
    def _responder_tools(pending=None) -> tuple[dict[str, Any], ...]:
        if isinstance(pending, MenuOffer):
            return tuple(_tool(a.value, "Reject all options." if a.value == "REJECT" else "Choose this option; it binds immediately.", _empty_parameters()) for a in response_actions(pending))
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
        if name == "MENU":
            if not observation.menu_enabled or not isinstance(arguments, Mapping):
                raise InvalidActionError("MENU is unavailable or malformed.")
            options = arguments.get("options")
            if not isinstance(options, list) or len(options) != 2:
                raise InvalidActionError("MENU requires exactly two options.")
            offers = tuple(self._decode_proposer_call({"name": "OFFER", "arguments": o}, observation).offer for o in options)
            try:
                return OfferProposal(MenuOffer(offers))
            except ValueError as exc:
                raise InvalidActionError(str(exc)) from exc
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

    def _decode_responder_call(self, call: Any, pending=None) -> ResponseAction:
        name = self._call_name(call).upper()
        arguments = self._call_arguments(call)
        if name not in {a.value for a in response_actions(pending)}:
            raise InvalidActionError(f"Unknown responder tool: {name!r}.")
        if arguments is None or arguments:
            raise InvalidActionError(f"{name} must have an empty argument object.")
        return ResponseAction(name)

    @staticmethod
    def _proposer_system_prompt(observation: PlayerObservation) -> str:
        """Describe the game without supplying the strategic diagnosis."""

        return (
            f"You are player {_player_name(observation.player_id)}, an expert strategic "
            "negotiator in a multi-issue bargaining game. You will receive your BENAC-P "
            "observation as JSON. It contains the public game state and your own private "
            "preferences.\n\n"
            "--- OBJECTIVE ---\n"
            "Maximize your terminal utility according to your private goal preferences. "
            "Other players have their own private preferences and choose actions to maximize "
            "their own terminal utility.\n\n"
            "--- DATA SCHEMA ---\n"
            "1. goals: each goal has type ALL_OF, a requires list of named player/action "
            "commitments, and your_preference (WANT, NEUTRAL, or AVOID).\n"
            "2. binding_commitments: the current binding commitments, such as P0:[A0].\n"
            "3. pending offers are hypothetical until accepted; transcript entries record "
            "events and named additions without repeating the full state.\n"
            "4. actions_per_player: the named actions available to each player.\n"
            "5. round_robin, current_proposer, and turn_index: the public turn schedule.\n"
            "6. max_changes and forbidden_commitments: the per-player commitment constraints.\n"
            "7. legal_partners: the partners currently available to the proposer.\n"
            "8. transcript: previous public PASS/OFFER events.\n"
            "9. current_state_facts gives computed goal satisfaction, missing commitments, "
            "and your utility if the game ended in this state. These are state facts, "
            "not predictions of future utility.\n\n"
            "--- STATE AND UTILITY RULES ---\n"
            "1. Every goal is ALL_OF: it is satisfied only when every commitment in its "
            "requires list is present in binding_commitments. If any requirement is missing, "
            "the goal contributes 0; a partial match does not count.\n"
            "2. binding_commitments is the current state. An OFFER is hypothetical until the "
            "partner accepts it.\n"
            "3. If an offer is accepted, the next state is the current binding_commitments "
            "plus exactly and only the commitments explicitly listed in that offer. Do not "
            "infer or add any unlisted commitment.\n"
            "4. At the terminal state, your utility is the number of fully satisfied WANT "
            "goals minus the number of fully satisfied AVOID goals. NEUTRAL goals contribute "
            "0, and partially satisfied goals contribute 0.\n\n"
            "--- HARD CONSTRAINTS ---\n"
            "1. Commitments are binding and can only be added; existing commitments remain.\n"
            f"2. Add at most {observation.max_changes} new commitments for each player in this "
            "turn.\n"
            "3. Choose a legal partner different from yourself.\n"
            "4. An OFFER must add at least one commitment. A no-op offer is invalid.\n"
            "5. In an OFFER, self_commitments and partner_commitments contain named additions, "
            "not full vectors.\n"
            "6. The environment validates all remaining legality constraints.\n\n"
            "--- DECISION PROTOCOL ---\n"
            "Before calling a tool, first write a brief reasoning statement explaining what you "
            "plan to do and why.\n\n"
            "Then immediately call exactly ONE available tool:\n"
            "- PASS()\n"
            "- OFFER(...)\n\n"
            "Always provide reasoning before the tool call.\n"
            "Do not write anything after the tool call."
        )

    @staticmethod
    def _responder_system_prompt(observation: PlayerObservation) -> str:
        """Describe response semantics without supplying a long-horizon rule."""

        return (
            f"You are player {_player_name(observation.player_id)}, an expert strategic "
            "negotiator responding to a bilateral offer in a multi-issue bargaining game. "
            "You will receive your BENAC-P observation as JSON. It contains the public game "
            "state, the pending offer, and your own private preferences.\n\n"
            "--- OBJECTIVE ---\n"
            "Your goal is to maximize your terminal utility according to your private goal "
            "preferences. Other players have their own private preferences and choose actions "
            "to maximize their own terminal utility.\n\n"
            "--- DATA SCHEMA ---\n"
            "1. goals maps each goal to type ALL_OF, its requires list of named player/action "
            "commitments, and your_preference (WANT, NEUTRAL, or AVOID).\n"
            "2. binding_commitments lists the commitments that are already binding.\n"
            "3. pending_offer contains the proposer, partner, and an additions map of the "
            "named commitments each player would receive if ACCEPT is chosen.\n"
            "4. transcript, round_robin, and turn_index describe the public history and schedule.\n"
            "5. current_state_facts gives computed goal satisfaction, missing commitments, "
            "and your utility if the game ended now. if_accepted gives these facts and "
            "binding_commitments for the hypothetical accepted state, plus the number of "
            "new commitments. These facts do not predict future utility.\n\n"
            "--- STATE AND UTILITY RULES ---\n"
            "1. Every goal is ALL_OF: it is satisfied only when every commitment in its "
            "requires list is present in binding_commitments. If any requirement is missing, "
            "the goal contributes 0; a partial match does not count.\n"
            "2. binding_commitments is the current state. The pending offer is a hypothetical "
            "next state, not part of the current state.\n"
            "3. ACCEPT makes the next state equal to the current binding_commitments plus "
            "exactly and only pending_offer.additions. No unlisted commitment is inferred. "
            "REJECT leaves binding_commitments unchanged and advances the game.\n"
            "4. At the terminal state, your utility is the number of fully satisfied WANT "
            "goals minus the number of fully satisfied AVOID goals. NEUTRAL goals contribute "
            "0, and partially satisfied goals contribute 0.\n\n"
            "--- RESPONSE SEMANTICS ---\n"
            "ACCEPT() or REJECT() is the only response action.\n\n"
            "--- DECISION PROTOCOL ---\n"
            "Before calling a tool, first write a brief reasoning statement explaining what you "
            "plan to do and why.\n\n"
            "Then immediately call exactly ONE available tool:\n"
            "- ACCEPT()\n"
            "- REJECT()\n\n"
            "Always provide reasoning before the tool call.\n"
            "Do not write anything after the tool call."
        )

    def _propose_native(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
        messages = [
            {
                "role": "system",
                "content": self._proposer_system_prompt(observation) + ("\nMENU({options:[offer1,offer2]}) is also available. Options must be distinct legal offers to the same partner. Partner chooses CHOOSE_1/CHOOSE_2 or REJECT; only the chosen offer binds, consuming one turn." if observation.menu_enabled else ""),
            },
            {
                "role": "user",
                "content": (
                    "--- CURRENT TURN STATE ---\n"
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
                "content": ("You are a BENAC-P negotiator maximizing your own terminal utility. The pending menu contains two legal binding offers to you. Use CHOOSE_1(), CHOOSE_2(), or REJECT(). Only the chosen offer binds immediately; rejection binds neither. Your private observation includes projected state facts for both options. Give reasoning, then exactly one tool call." if isinstance(observation.pending_offer, MenuOffer) else self._responder_system_prompt(observation)),
            },
            {
                "role": "user",
                "content": (
                    "--- CURRENT TURN STATE ---\n"
                    "The pending offer is included in pending_offer. Here is your observation "
                    "as JSON:\n" + self._observation_payload(observation)
                ),
            },
        ]
        return self._native_decision(
            messages,
            self._responder_tools(observation.pending_offer),
            lambda call: self._decode_responder_call(call, observation.pending_offer),
        )

    def propose(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
        if self.native_tools:
            return self._propose_native(observation)

        if observation.menu_enabled:
            raise ValueError("Menu games require the native-tools adapter.")

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
                    "not included.\n" + self._legacy_observation_payload(observation)
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
                    "JSON:\n" + self._legacy_observation_payload(observation)
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
