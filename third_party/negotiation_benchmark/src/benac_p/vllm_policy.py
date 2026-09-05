"""vLLM-backed BENAC-P player policy."""

from __future__ import annotations

import json
from typing import Any, Mapping

from benac_p.observations import PlayerObservation
from benac_p.schema import Offer, OfferProposal, PassProposal, ResponseAction
from benac_p.state import InvalidActionError


class VLLMPlayerPolicy:
    """Use one shared text-generation client for proposer and responder turns.

    The policy receives a private player observation.  Consequently the same
    model/client can be placed behind all players without exposing another
    player's private preference labels through the prompt.
    """

    def __init__(self, client: Any, *, model: str | None = None) -> None:
        if not hasattr(client, "complete"):
            raise TypeError("client must provide a complete(messages=...) method.")
        self.client = client
        self.model = model

    @staticmethod
    def _parse_json(text: str) -> Mapping[str, Any]:
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

    def _complete(self, messages: list[dict[str, str]]) -> Mapping[str, Any]:
        text = self.client.complete(
            messages,
            response_format={"type": "json_object"},
            model=self.model,
        )
        return self._parse_json(text)

    @staticmethod
    def _observation_payload(observation: PlayerObservation) -> str:
        return json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True)

    def propose(self, observation: PlayerObservation) -> PassProposal | OfferProposal:
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
            result = self._complete(messages)
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
            # Let GameRunner decide whether this becomes a marked PASS or a
            # strict error.  Falling back inside the policy would make an
            # invalid LLM output indistinguishable from an intentional PASS.
            raise InvalidActionError("vLLM proposer output is malformed.") from exc

    def respond(
        self,
        observation: PlayerObservation,
        proposal: Offer,
    ) -> ResponseAction:
        del proposal
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
            result = self._complete(messages)
            response = result.get("response", result.get("action", result.get("value")))
            if response is None:
                raise ValueError("response is missing")
            return ResponseAction(str(response))
        except (TypeError, ValueError) as exc:
            raise InvalidActionError("vLLM responder output is malformed.") from exc
