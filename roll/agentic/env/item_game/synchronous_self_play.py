"""Synchronous, symmetric test-only self-play for the new ItemGame suite.

The runtime has two separate phases per round.  First, each agent answers all
mandatory messages from the previous round.  Then all active agents choose one
optional message and zero or more state actions from the same immutable snapshot.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .config import ItemGameConfig
from .generator import ItemGameInstance, generate_instance


@dataclass(frozen=True)
class ItemGameToolCall:
    """One OpenAI-compatible function call selected by the policy."""

    tool_name: str
    arguments: Mapping[str, Any]
    tool_call_id: str = ""


@dataclass(frozen=True)
class SelfPlayPolicyOutput:
    """Backend-neutral policy result: private text plus native tool calls.

    ``content``/``reasoning`` remain optional compatibility fields for the two
    legacy protocol baselines. Native ItemGame rollouts use ``reason`` and
    ``tool_calls`` only.
    """

    reason: str = ""
    tool_calls: tuple[ItemGameToolCall, ...] = ()
    raw_message: Mapping[str, Any] | None = None
    usage: Mapping[str, Any] | None = None
    reasoning: str = ""
    content: str = ""
    output_mode: str = "reason_action"


class SynchronousSelfPlayPolicy(Protocol):
    def generate(
        self,
        *,
        agent: str,
        observation: str,
        legal_actions: Sequence[str],
        context: Sequence[Mapping[str, str]],
        action_schema: Mapping[str, Any] | None = None,
        available_actions: Sequence[Mapping[str, Any]] | None = None,
    ) -> str | SelfPlayPolicyOutput:
        ...


class SynchronousActionError(ValueError):
    """A model action or response is not legal in the supplied snapshot."""


class StructuredActionError(SynchronousActionError):
    """The model answer is not a typed JSON action."""


DECISION_ACTION_NAMES = {
    "PASS", "QUERY", "INFORM", "REQUEST_TRANSFER", "GIVE", "PROPOSE_JOIN", "COMMIT",
}
RESPONSE_ACTION_NAMES = {
    "INFORM", "GIVE", "REJECT_TRANSFER", "ACCEPT_JOIN", "REJECT_JOIN", "INACTIVE",
}

ACTION_DESCRIPTIONS = {
    "QUERY": "Ask another agent for their private GOAL or current HOLDINGS.",
    "INFORM": "Truthfully tell another agent your GOAL or current HOLDINGS.",
    "REQUEST_TRANSFER": "Ask another agent to transfer the specified items to you.",
    "GIVE": "Transfer specified items that you currently hold to another agent.",
    "REJECT_TRANSFER": "Refuse the pending transfer request.",
    "PROPOSE_JOIN": "Propose forming a coalition with another active agent.",
    "ACCEPT_JOIN": "Accept the pending coalition proposal.",
    "REJECT_JOIN": "Reject the pending coalition proposal.",
    "COMMIT": "Publicly and permanently commit the specified items.",
    "PASS": "Take no proactive action this round.",
    "INACTIVE": "Environment-only response for an inactive recipient.",
}


def _format_set(items: set[str] | frozenset[str]) -> str:
    return "{" + ",".join(sorted(items)) + "}"


def _normalize(text: str) -> str:
    text = " ".join(str(text).strip().split())
    return re.sub(r"\s*,\s*", ",", text)


def _answer_text(response: str) -> str:
    match = re.search(r"<answer>\s*(.*?)\s*</answer>\s*$", response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return re.sub(r"<(?:reason|think)>.*?</(?:reason|think)>", "", response, flags=re.DOTALL | re.IGNORECASE).strip()


def _parse_reason(response: str) -> str:
    matches = re.findall(r"<(?:reason|think)>\s*(.*?)\s*</(?:reason|think)>", response, re.DOTALL | re.IGNORECASE)
    return "\n".join(match.strip() for match in matches)


def _reason_is_english(reason: str) -> bool:
    """Cheap language guard for the English-reason protocol baseline.

    This is deliberately a separate diagnostic rather than part of action
    schema validity. Item/player identifiers and punctuation remain allowed.
    """
    return bool(reason.strip()) and re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", reason) is None


def _reason_is_natural_content(reason: str) -> bool:
    """Exclude leaked/raw tool serialization from reason diagnostics."""
    text = reason.strip()
    if not text:
        return False
    lowered = text.lower()
    if "<tool_call" in lowered or "</tool_call" in lowered:
        return False
    if re.fullmatch(r"\s*\{.*\}\s*", text, re.DOTALL) and '"name"' in text:
        return False
    return True


def _answer_is_json(response: str) -> bool:
    """Whether the answer block uses the new structured-output interface."""
    answer = _answer_text(response).strip()
    answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer, flags=re.IGNORECASE | re.DOTALL).strip()
    return answer.startswith(("{", "["))


def _load_json_answer(response: str) -> Any:
    answer = _answer_text(response).strip()
    answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(answer)
    except (TypeError, json.JSONDecodeError) as exc:
        # Tolerate one stray quote after an otherwise complete JSON array or
        # object. Keep this repair deliberately narrow so real malformed
        # outputs still reach the normal syntax/semantic error path.
        if answer.endswith('"'):
            repaired = answer[:-1].rstrip()
            try:
                return json.loads(repaired)
            except (TypeError, json.JSONDecodeError):
                pass
        raise StructuredActionError("answer must contain one JSON action object or an array of action objects") from exc


def _unwrap_reason_action(value: Any) -> tuple[str, Any]:
    """Extract mandatory private reasoning and the executable action payload."""
    if not isinstance(value, dict) or set(value) != {"reason", "action"}:
        raise StructuredActionError("answer must contain exactly reason and action")
    reason = value["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise StructuredActionError("JSON field 'reason' must be a non-empty string")
    action = value["action"]
    if not isinstance(action, (dict, list)):
        raise StructuredActionError("JSON field 'action' must be an object or array of objects")
    return reason, action


def _require_json_action_object(value: Any, *, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StructuredActionError("each JSON action must be an object")
    if set(value) - {"action", "recipient", "field", "value", "items", "message_id", "requester", "proposer"}:
        raise StructuredActionError("JSON action contains an unknown field")
    action = value.get("action")
    if not isinstance(action, str) or action.upper() not in allowed:
        raise StructuredActionError(f"unknown JSON action {action!r}")
    result = dict(value)
    result["action"] = action.upper()
    return result


def _validate_action_fields(obj: Mapping[str, Any], *, response: bool) -> None:
    action = str(obj["action"])
    fields = set(obj)
    required: dict[str, set[str]] = {
        "PASS": {"action"},
        "QUERY": {"action", "recipient", "field"},
        "INFORM": {"action", "recipient", "field", "value"},
        "REQUEST_TRANSFER": {"action", "recipient", "items"},
        "GIVE": {"action", "recipient", "items"},
        "PROPOSE_JOIN": {"action", "recipient"},
        "COMMIT": {"action", "items"},
        "REJECT_TRANSFER": {"action", "requester", "items"},
        "ACCEPT_JOIN": {"action", "proposer"},
        "REJECT_JOIN": {"action", "proposer"},
        "INACTIVE": {"action"},
    }
    if action not in required:
        raise StructuredActionError(f"unknown JSON action {action!r}")
    expected = required[action] | ({"message_id"} if response else set())
    if fields != expected:
        missing = sorted(expected - fields)
        extra = sorted(fields - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unknown {extra}")
        raise StructuredActionError(f"wrong fields for {action}: {', '.join(details)}")


def _require_json_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise StructuredActionError(f"JSON field {field!r} must be a non-empty string")
    return value


def _require_json_items(value: Any, field: str = "items") -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise StructuredActionError(f"JSON field {field!r} must be a non-empty array of item names")
    if len(set(value)) != len(value):
        raise StructuredActionError(f"JSON field {field!r} must not contain duplicates")
    return value


def _json_field(value: Any) -> str:
    field = _require_json_string(value, "field").upper()
    if field not in {"GOAL", "HOLDINGS"}:
        raise StructuredActionError("JSON field 'field' must be GOAL or HOLDINGS")
    return field


def _validate_json_enums(value: Any, *, players: Sequence[str], items: Sequence[str], response: bool, message_ids: Sequence[int] = ()) -> None:
    """Validate the episode-dependent enum slots of a typed answer."""
    objects = value if isinstance(value, list) else [value]
    player_set = set(players)
    item_set = set(items)
    message_id_set = set(message_ids)
    for obj in objects:
        if not isinstance(obj, dict):
            raise StructuredActionError("each JSON action must be an object")
        for key in ("recipient", "requester", "proposer"):
            if key in obj and obj[key] not in player_set:
                raise StructuredActionError(f"JSON field {key!r} is not a player in this episode")
        for key in ("items", "value"):
            if key in obj and any(item not in item_set for item in obj[key]):
                raise StructuredActionError(f"JSON field {key!r} contains an item not in this episode")
        if response and obj.get("message_id") not in message_id_set:
            raise StructuredActionError("response message_id is not pending for this agent")


def _validate_json_response_references(value: Any, requests: Sequence[Mapping[str, Any]]) -> None:
    objects = value if isinstance(value, list) else [value]
    by_id = {int(obj["message_id"]): obj for obj in objects}
    for request in requests:
        obj = by_id[int(request["id"])]
        action = obj["action"]
        if request["kind"] == "TRANSFER" and action == "REJECT_TRANSFER":
            if (
                obj["requester"] != request["sender"]
                or set(obj["items"]) != set(request["items"])
            ):
                raise SynchronousActionError("REJECT_TRANSFER must refer to the exact incoming request")
        if request["kind"] == "JOIN" and action in {"ACCEPT_JOIN", "REJECT_JOIN"}:
            if obj["proposer"] != request["sender"]:
                raise SynchronousActionError("JOIN response must refer to the exact proposer")


def _validate_tool_call_schema(
    call: ItemGameToolCall,
    available_actions: Sequence[Mapping[str, Any]],
) -> None:
    """Validate function name and arguments independently of game legality."""
    by_name = {str(definition.get("name")): definition for definition in available_actions}
    if call.tool_name not in by_name:
        raise StructuredActionError(f"unknown tool {call.tool_name!r}")
    schema = by_name[call.tool_name].get("arguments", {})
    properties = schema.get("properties", {})
    required = set(schema.get("required", ()))
    arguments = dict(call.arguments)
    missing = required - set(arguments)
    extra = set(arguments) - set(properties)
    if missing or extra:
        raise StructuredActionError(
            f"wrong arguments for {call.tool_name}: missing={sorted(missing)}, unknown={sorted(extra)}"
        )
    for key, value in arguments.items():
        spec = properties[key]
        expected_type = spec.get("type")
        type_ok = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }.get(expected_type, True)
        if not type_ok:
            raise StructuredActionError(f"tool argument {key!r} has wrong type")
        if "enum" in spec and value not in spec["enum"]:
            raise StructuredActionError(f"tool argument {key!r} is outside its enum")
        if expected_type == "array":
            if not value:
                raise StructuredActionError(f"tool argument {key!r} must not be empty")
            item_spec = spec.get("items", {})
            if any(not isinstance(item, str) for item in value):
                raise StructuredActionError(f"tool argument {key!r} must contain strings")
            if "enum" in item_spec and any(item not in item_spec["enum"] for item in value):
                raise StructuredActionError(f"tool argument {key!r} contains a value outside its enum")
            if len(set(value)) != len(value):
                raise StructuredActionError(f"tool argument {key!r} contains duplicates")


def _remap_instance(instance: ItemGameInstance) -> dict[str, Any]:
    mapping = {"EGO": "P0"}
    mapping.update({agent: agent for agent in instance.goals if agent != "EGO"})
    remap = lambda agent: mapping.get(agent, agent)
    return {
        "players": tuple(["P0"] + sorted(remap(agent) for agent in instance.goals if agent != "EGO")),
        "goals": {remap(agent): frozenset(goal) for agent, goal in instance.goals.items()},
        "holdings": {remap(agent): frozenset(items) for agent, items in instance.holdings.items()},
        "active_partner": remap(instance.active_partner) if instance.active_partner else None,
        "partner_roles": {remap(agent): role for agent, role in instance.partner_roles.items()},
        "partner_policies": {remap(agent): policy for agent, policy in instance.partner_policies.items()},
    }


@dataclass
class SynchronousEpisodeResult:
    seed: int
    subtype: str
    ground_truth: dict[str, Any]
    rounds: list[dict[str, Any]]
    terminal: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "subtype": self.subtype,
            "ground_truth": self.ground_truth,
            "rounds": self.rounds,
            "terminal": self.terminal,
            "diagnostics": self.diagnostics,
        }


class SynchronousItemGame:
    """Pure transition engine for symmetric P0/P1/P2/P3 self-play."""

    # These are descriptions, not concrete legal-action lists.  Concrete
    # player/item values are supplied by the observation and checked by the
    # environment after parsing.
    MESSAGE_TEMPLATES = (
        '{"action":"QUERY","recipient":"<agent_id>","field":"GOAL"}',
        '{"action":"INFORM","recipient":"<agent_id>","field":"HOLDINGS","value":["<item_1>","<item_2>"]}',
        '{"action":"REQUEST_TRANSFER","recipient":"<agent_id>","items":["<item_1>"]}',
        '{"action":"PROPOSE_JOIN","recipient":"<agent_id>"}',
    )
    STATE_ACTION_TEMPLATES = (
        '{"action":"GIVE","recipient":"<agent_id>","items":["<item_1>"]}',
        '{"action":"COMMIT","items":["<item_1>","<item_2>"]}',
        '{"action":"PASS"}',
    )

    SUPPORTED_SUBTYPES = (
        "collaboration",
        "request_surplus_reroute",
        "respond_to_give_request",
    )

    def __init__(self, instance: ItemGameInstance, config: ItemGameConfig):
        if instance.subtype not in self.SUPPORTED_SUBTYPES:
            raise ValueError(f"unsupported synchronous subtype {instance.subtype!r}")
        if config.max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if config.max_invalid_retries_per_decision < 0:
            raise ValueError("max_invalid_retries_per_decision must be non-negative")
        data = _remap_instance(instance)
        self.instance = instance
        self.config = config
        self.subtype = instance.subtype
        self.players = tuple(data["players"])
        self.items = tuple(instance.items)
        self.goals = {agent: set(goal) for agent, goal in data["goals"].items()}
        self.holdings = {agent: set(items) for agent, items in data["holdings"].items()}
        self.active: set[str] = set(self.players)
        self.round_index = 0
        self.done = False
        self.terminal_reason: str | None = None
        self.pending_messages: list[dict[str, Any]] = []
        self.next_message_id = 1
        self.agreements: list[dict[str, Any]] = []
        self.coalition: dict[str, Any] | None = None
        self.settled = False
        self.join_accepted = False  # compatibility alias
        self.committed: dict[str, set[str]] = {}
        self.known: dict[str, dict[str, dict[str, set[str]]]] = {agent: {} for agent in self.players}
        self.inboxes: dict[str, list[dict[str, Any]]] = {agent: [] for agent in self.players}
        self.public_events: list[dict[str, Any]] = []
        self.transfers: list[dict[str, Any]] = []
        self.metrics = {
            "communications_per_player": {agent: 0 for agent in self.players},
            "queries_sent": 0,
            "informs_sent": 0,
            "proposals_sent": 0,
            "proposals_accepted": 0,
            "proposals_rejected": 0,
            "requests_sent": 0,
            "requests_given": 0,
            "requests_rejected": 0,
            "schema_valid_actions": 0,
            "schema_invalid_actions": 0,
            "schema_valid_responses": 0,
            "schema_invalid_responses": 0,
            "tool_call_present": 0,
            "tool_call_missing": 0,
            "exactly_one_tool_call": 0,
            "not_exactly_one_tool_call": 0,
            "semantic_valid_actions": 0,
            "semantic_invalid_actions": 0,
            "semantic_valid_responses": 0,
            "semantic_invalid_responses": 0,
            "invalid_action_retries": 0,
            "invalid_response_retries": 0,
            "transfers": 0,
            "commits": 0,
            "passes": 0,
            "invalid_actions": 0,
            "request_proposed": 0,
            "request_responded": 0,
            "safe_give_correct": 0,
            "harmful_give_refused": 0,
            "messages_dropped_due_to_commit": 0,
        }

    @property
    def focal_player(self) -> str:
        return self.config.focal_player

    @property
    def active_players(self) -> tuple[str, ...]:
        return tuple(agent for agent in self.players if agent in self.active)

    def _subsets(self, items: set[str]) -> tuple[frozenset[str], ...]:
        ordered = tuple(sorted(items))
        return tuple(
            frozenset(item for index, item in enumerate(ordered) if mask & (1 << index))
            for mask in range(1 << len(ordered))
        )

    def _snapshot(self) -> dict[str, Any]:
        return {
            "round": self.round_index,
            "active": tuple(self.active_players),
            "goals": {agent: frozenset(self.goals[agent]) for agent in self.players},
            "holdings": {agent: frozenset(self.holdings[agent]) for agent in self.players},
            "committed": {agent: frozenset(self.committed.get(agent, ())) for agent in self.players},
            "known": {
                agent: {
                    other: {field: frozenset(values) for field, values in fields.items()}
                    for other, fields in self.known[agent].items()
                }
                for agent in self.players
            },
            "inboxes": {agent: tuple(self.inboxes[agent]) for agent in self.players},
            "public_events": tuple(tuple(sorted(event.items())) for event in self.public_events),
            "agreements": tuple(
                {
                    key: (frozenset(value) if isinstance(value, (set, frozenset)) else value)
                    for key, value in agreement.items()
                }
                for agreement in self.agreements
            ),
            "coalition": self.coalition,
        }

    def build_round_snapshot(self) -> dict[str, Any]:
        return self._snapshot()

    def build_response_snapshot(self) -> dict[str, Any]:
        return self._snapshot()

    def _format_inbox(self, agent: str) -> list[str]:
        return [f"- round {message['round']}: {message['text']}" for message in self.inboxes[agent]]

    def get_action_templates(self, agent: str) -> tuple[str, ...]:
        """Return the protocol grammar shown to the model.

        Concrete legality is deliberately checked by ``_parse_decision``
        against the round snapshot.  The model should learn the protocol
        semantics, not copy a large pre-enumerated action table.
        """
        if agent not in self.active:
            return ()
        return self.MESSAGE_TEMPLATES + self.STATE_ACTION_TEMPLATES

    def get_available_actions(
        self,
        agent: str,
        *,
        phase: str,
        snapshot: Mapping[str, Any] | None = None,
        requests: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Return the environment-owned typed action families for a decision point.

        Concrete recipients/items remain model-selected arguments.  The
        returned definitions describe only the action family and its typed
        fields; no legacy MESSAGE/ACTIONS DSL is exposed to the vLLM prompt.
        """
        if agent not in self.players:
            raise ValueError(f"unknown player {agent!r}")
        if phase not in {"decision", "response"}:
            raise ValueError(f"unknown action phase {phase!r}")
        other_players = [player for player in self.players if player != agent]
        item_array = {"type": "array", "items": {"type": "string", "enum": list(self.items)}}
        recipient = {"type": "string", "enum": other_players}

        def definition(
            name: str,
            properties: Mapping[str, Any],
            required: Sequence[str] = (),
        ) -> dict[str, Any]:
            return {
                "name": name,
                "description": ACTION_DESCRIPTIONS[name],
                "arguments": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": dict(properties),
                    "required": list(required),
                },
            }

        if phase == "decision":
            definitions = [
                definition("QUERY", {"recipient": recipient, "field": {"type": "string", "enum": ["GOAL", "HOLDINGS"]}}, ("recipient", "field")),
                definition("INFORM", {"recipient": recipient, "field": {"type": "string", "enum": ["GOAL", "HOLDINGS"]}, "value": item_array}, ("recipient", "field", "value")),
                definition("REQUEST_TRANSFER", {"recipient": recipient, "items": item_array}, ("recipient", "items")),
                definition("GIVE", {"recipient": recipient, "items": item_array}, ("recipient", "items")),
                definition("COMMIT", {"items": item_array}, ("items",)),
                # Qwen3 + Hermes is more reliable when even a no-op tool has
                # one explicit, schema-constrained argument.  The runner
                # strips this transport-only confirmation before execution.
                definition("PASS", {"confirm": {"type": "boolean", "enum": [True]}}, ("confirm",)),
            ]
            if self.subtype == "collaboration":
                definitions.insert(4, definition("PROPOSE_JOIN", {"recipient": recipient}, ("recipient",)))
            return tuple(definitions)

        response_names: set[str] = set()
        effective_requests = tuple(requests) if requests else tuple(
            message for message in self.pending_messages if message["recipient"] == agent
        )
        for request in effective_requests:
            if request["kind"] == "QUERY":
                response_names.add("INFORM")
            elif request["kind"] == "TRANSFER":
                response_names.update({"GIVE", "REJECT_TRANSFER"})
            elif request["kind"] == "JOIN":
                response_names.update({"ACCEPT_JOIN", "REJECT_JOIN"})
        message_ids = [int(request["id"]) for request in effective_requests]
        message_id = {"type": "integer", "enum": message_ids}
        response_definitions = {
            "INFORM": definition("INFORM", {"message_id": message_id, "recipient": recipient, "field": {"type": "string", "enum": ["GOAL", "HOLDINGS"]}, "value": item_array}, ("message_id", "recipient", "field", "value")),
            "GIVE": definition("GIVE", {"message_id": message_id, "recipient": recipient, "items": item_array}, ("message_id", "recipient", "items")),
            "REJECT_TRANSFER": definition("REJECT_TRANSFER", {"message_id": message_id, "requester": recipient, "items": item_array}, ("message_id", "requester", "items")),
            "ACCEPT_JOIN": definition("ACCEPT_JOIN", {"message_id": message_id, "proposer": recipient}, ("message_id", "proposer")),
            "REJECT_JOIN": definition("REJECT_JOIN", {"message_id": message_id, "proposer": recipient}, ("message_id", "proposer")),
            "INACTIVE": definition("INACTIVE", {"message_id": message_id}, ("message_id",)),
        }
        return tuple(response_definitions[name] for name in sorted(response_names) if name in response_definitions)

    def get_action_schema(
        self,
        agent: str,
        *,
        response: bool = False,
        output_mode: str = "reason_action",
        requests: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Return the schema for the selected self-play output mode.

        The schema deliberately describes only the JSON envelope and primitive
        value types. Action-specific required fields and game legality remain
        semantic checks in the environment. In particular, avoid ``oneOf``,
        ``minItems``, and ``uniqueItems`` here because they are not accepted by
        the xgrammar backend used by older vLLM releases.
        """
        if agent not in self.players:
            raise ValueError(f"unknown player {agent!r}")
        if output_mode == "native_tools":
            # Native function calling carries one schema per tool, not a
            # response_format envelope schema.
            return {}
        if output_mode not in {"reason_action", "action_only"}:
            raise ValueError(f"unknown output_mode {output_mode!r}")
        players = [player for player in self.players if player != agent]
        items = list(self.items)
        item_array = {"type": "array", "items": {"type": "string", "enum": items}}
        if response:
            effective_requests = tuple(requests) if requests else tuple(
                message for message in self.pending_messages if message["recipient"] == agent
            )
            available_names = {
                definition["name"]
                for definition in self.get_available_actions(agent, phase="response", requests=effective_requests)
            }
            message_ids = [message["id"] for message in effective_requests]
            message_id = {"type": "integer", "enum": message_ids}
            recipient = {"type": "string", "enum": players}
            action_object = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": sorted(available_names or RESPONSE_ACTION_NAMES)},
                    "message_id": message_id,
                    "recipient": recipient,
                    "requester": recipient,
                    "proposer": recipient,
                    "field": {"type": "string", "enum": ["GOAL", "HOLDINGS"]},
                    "value": item_array,
                    "items": item_array,
                },
                "required": ["action"],
            }
            action_schema: dict[str, Any] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    # Keep the decoder schema inside the conservative vLLM
                    # 0.9 structured-output subset. Non-empty/English checks are
                    # application-level envelope diagnostics below.
                    "reason": {"type": "string"},
                    "action": {"type": "array", "items": action_object},
                },
                "required": ["reason", "action"],
            }
            if output_mode == "action_only":
                return action_schema["properties"]["action"]
            return {
                **action_schema,
            }
        available_names = {
            definition["name"]
            for definition in self.get_available_actions(agent, phase="decision")
        }
        recipient = {"type": "string", "enum": players}
        action_object = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": sorted(available_names)},
                "recipient": recipient,
                "field": {"type": "string", "enum": ["GOAL", "HOLDINGS"]},
                "value": item_array,
                "items": item_array,
            },
            "required": ["action"],
        }
        action_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reason": {"type": "string"},
                "action": action_object,
            },
            "required": ["reason", "action"],
        }
        if output_mode == "action_only":
            return action_schema["properties"]["action"]
        return {
            **action_schema,
        }

    def get_response_action_templates(self, agent: str) -> tuple[str, ...]:
        if agent not in self.players:
            raise ValueError(f"unknown player {agent!r}")
        return (
            '{"message_id":0,"action":"INFORM","recipient":"<sender>","field":"GOAL","value":["<item_1>"]}',
            '{"message_id":0,"action":"GIVE","recipient":"<request_receiver>","items":["<item_1>"]}',
            '{"message_id":0,"action":"REJECT_TRANSFER","requester":"<sender>","items":["<item_1>"]}',
            '{"message_id":0,"action":"ACCEPT_JOIN","proposer":"<sender>"}',
        )

    def get_observation(
        self,
        agent: str,
        snapshot: Mapping[str, Any] | None = None,
        *,
        include_action_templates: bool = True,
    ) -> str:
        if agent not in self.goals:
            raise ValueError(f"unknown player {agent!r}")
        snap = snapshot or self._snapshot()
        lines = [
            "You are an agent in a synchronous Item Coalition Game.",
            f"Your identity: {agent}",
            f"Your goal: {_format_set(set(snap['goals'][agent]))}",
            f"Your holdings: {_format_set(set(snap['holdings'][agent]))}",
            f"Round: {snap['round']}/{self.config.max_rounds}",
            f"Active players: {', '.join(snap['active'])}",
            "All active players choose independently from this same round snapshot.",
        ]
        known = snap["known"][agent]
        known_text = {
            other: {field: _format_set(set(values)) for field, values in fields.items()}
            for other, fields in known.items()
        }
        lines.append("Known private information: " + (str(known_text) if known_text else "none"))
        lines.append("Direct messages:")
        lines.extend(self._format_inbox(agent) or ["- none"])
        lines.append("Public commit events:")
        lines.extend((f"- {dict(event)}" for event in snap["public_events"]) or ["- none"])
        lines.extend([
            "DECISION PHASE.",
            "All mandatory responses from the previous round have already been completed.",
            "Briefly reason in assistant content about the relevant private state, interaction history, and next interaction.",
            "Keep that private reason concise, then make exactly one available ItemGame tool call.",
            "The environment consumes only the tool call; never encode an action in prose.",
            "Do not use XML, a JSON reason/action envelope, MESSAGE/ACTIONS labels, or placeholder values.",
            "Use an exact player id from Active players and exact item names from the state or your known information.",
            "QUERY field must be exactly GOAL or HOLDINGS.",
            "INFORM must include your own truthful GOAL or current HOLDINGS in value as an array of item names.",
            "REQUEST_TRANSFER asks the named recipient to give items to you; you do not need to hold the requested items.",
            "A transfer request never needs the requester to hold the requested item.",
            "The requested owner responds with GIVE or REJECT; GIVE transfers immediately.",
            "GIVE is also allowed as a proactive transfer of your own unfrozen items.",
            "Send at most one proactive communication per round.",
            "Do not output response-only ACCEPT, REJECT, or INFORM in this phase.",
            "COMMIT is a one-shot public action and is exclusive: if you COMMIT, do not include any other action.",
            "PASS means choose no message and no state action.",
        ])
        if include_action_templates:
            lines.append("Action shapes:")
            lines.extend(f"- {action}" for action in self.MESSAGE_TEMPLATES)
            lines.append("State-action shapes:")
            lines.extend(f"- {action}" for action in self.STATE_ACTION_TEMPLATES)
        return "\n".join(lines)

    def get_response_observation(
        self,
        request: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        snapshot: Mapping[str, Any] | None = None,
    ) -> str:
        requests = [request] if isinstance(request, Mapping) else list(request)
        if not requests:
            raise SynchronousActionError("response observation requires at least one message")
        agent = str(requests[0]["recipient"])
        if any(str(message["recipient"]) != agent for message in requests):
            raise SynchronousActionError("all batched response messages must have one recipient")
        snap = snapshot or self._snapshot()
        lines = [
            "You are an agent in a synchronous Item Coalition Game.",
            f"Your identity: {agent}",
            f"Your goal: {_format_set(set(snap['goals'][agent]))}",
            f"Your holdings: {_format_set(set(snap['holdings'][agent]))}",
            f"Round: {snap['round']}/{self.config.max_rounds}",
            "RESPONSE PHASE.",
            "You are responding to messages from the previous round.",
            "Do not take any new decision-phase action in this phase.",
            "Respond to every listed message exactly once. Responses are free and do not use the proactive message slot.",
            "QUERY requires a truthful INFORM response.",
            "REQUEST TRANSFER requires either GIVE of the requested items or REJECT.",
            "JOIN requires ACCEPT or REJECT while the recipient is active; an inactive recipient returns INACTIVE.",
        ]
        for message in requests:
            lines.extend((
                "",
                f"Message #{message['id']} from {message['sender']}:",
                self._response_message_text(message),
                "Choose one JSON response object for this message.",
            ))
        lines.extend((
            "",
            "Briefly reason in assistant content about the relevant private state and interaction history.",
            "Keep that private reason concise, then make exactly one available ItemGame tool call.",
            "The tool arguments must contain the exact message_id shown above.",
            "For QUERY use INFORM with recipient, field, and truthful value.",
            "For a transfer request use GIVE with recipient and the exact requested items, or REJECT_TRANSFER.",
            "For JOIN use ACCEPT_JOIN or REJECT_JOIN with proposer.",
            "Use the exact message_id shown above. Do not invent or omit value/items.",
        ))
        return "\n".join(lines)

    def response_requests(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.pending_messages)

    def response_actions(self, request: Mapping[str, Any]) -> tuple[str, ...]:
        message_id = request["id"]
        if request["kind"] == "QUERY":
            noun = "GOAL" if request["field"] == "GOAL" else "HOLDINGS"
            verb = "IS" if noun == "GOAL" else "ARE"
            values = self.goals[request["recipient"]] if noun == "GOAL" else self.holdings[request["recipient"]]
            return (f"RESPOND #{message_id}: INFORM {request['sender']} MY {noun} {verb} {_format_set(values)}",)
        if request["kind"] == "TRANSFER":
            requested_items = set(request["items"])
            giver = request["from"]
            if (
                not requested_items.issubset(self.holdings[giver])
                or requested_items.intersection(self.committed.get(giver, ()))
            ):
                return (f"RESPOND #{message_id}: REJECT",)
            return (
                f"RESPOND #{message_id}: GIVE {_format_set(set(request['items']))} TO {request['to']}",
                f"RESPOND #{message_id}: REJECT",
            )
        if request["recipient"] not in self.active:
            return (f"RESPOND #{message_id}: INACTIVE",)
        return (f"RESPOND #{message_id}: ACCEPT", f"RESPOND #{message_id}: REJECT")

    def _response_message_text(self, message: Mapping[str, Any]) -> str:
        if message["kind"] == "QUERY":
            field = "GOAL" if message["field"] == "GOAL" else "HOLDINGS"
            return f"{message['sender']} asks you to reveal your {field}."
        if message["kind"] == "JOIN":
            return f"{message['sender']} asks to form a coalition with you."
        return (
            f"{message['sender']} asks you to give {_format_set(set(message['items']))} "
            f"to {message['to']}."
        )

    def _proposal_atoms(self, agent: str, snapshot: Mapping[str, Any]) -> list[str]:
        actions = []
        for other in self.players:
            if other == agent:
                continue
            # A request is sent by the receiver to the owner.  The owner can
            # already be inactive: committed players remain response-only.
            for item_set in self._subsets(set(self.items)):
                if item_set:
                    actions.append(f"REQUEST TRANSFER {_format_set(set(item_set))} FROM {other} TO {agent}")
        return actions

    def get_legal_actions(
        self, agent: str, snapshot: Mapping[str, Any] | None = None
    ) -> tuple[str, ...]:
        snap = snapshot or self._snapshot()
        if agent not in snap["active"]:
            return ()
        actions: list[str] = []
        for other in self.players:
            if other == agent:
                continue
            actions.extend((f"QUERY {other} FOR THEIR GOAL", f"QUERY {other} FOR THEIR HOLDINGS"))
            actions.extend((
                f"INFORM {other} MY GOAL IS {_format_set(set(snap['goals'][agent]))}",
                f"INFORM {other} MY HOLDINGS ARE {_format_set(set(snap['holdings'][agent]))}",
            ))
        actions.extend(self._proposal_atoms(agent, snap))
        # JOIN must target an active player in the decision snapshot.  If the
        # target commits in this same atomic round, the queued JOIN is still
        # delivered and receives an automatic INACTIVE response next round.
        if self.subtype == "collaboration":
            for other in self.players:
                if other != agent and other in snap["active"]:
                    actions.append(f"PROPOSE JOIN WITH {other}")
        for other in self.players:
            if other == agent:
                continue
            for item_set in self._subsets(set(snap["holdings"][agent])):
                if item_set:
                    actions.append(f"GIVE {_format_set(set(item_set))} TO {other}")
        # JOIN is intentionally not required before COMMIT. Final settlement
        # decides whether committed contributions formed a valid coalition.
        actions.extend(f"COMMIT {_format_set(set(subset))}" for subset in self._subsets(set(snap["holdings"][agent])))
        return tuple(dict.fromkeys(actions))

    @staticmethod
    def _is_message_atom(action: str) -> bool:
        return action.startswith(("QUERY ", "INFORM ", "REQUEST ", "PROPOSE "))

    def _parse_set(self, raw: str) -> frozenset[str]:
        if not raw.startswith("{") or not raw.endswith("}"):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        values = tuple(value.strip() for value in raw[1:-1].split(",") if value.strip())
        result = frozenset(values)
        if len(result) != len(values) or not result.issubset(set(self.items)):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        return result

    def _parse_give(
        self, agent: str, action: str, snapshot: Mapping[str, Any]
    ) -> dict[str, Any]:
        match = re.fullmatch(r"GIVE (\{[^}]*\}) TO (\w+)", action)
        if match is None:
            raise SynchronousActionError(f"invalid GIVE action {action!r}")
        items, target = self._parse_set(match.group(1)), match.group(2)
        if target not in self.players or target == agent:
            raise SynchronousActionError("GIVE target must be another player")
        if not items:
            raise SynchronousActionError("GIVE must contain at least one item")
        if not items.issubset(snapshot["holdings"][agent]):
            raise SynchronousActionError("giver does not hold every item in GIVE")
        if set(items).intersection(snapshot.get("committed", {}).get(agent, ())):
            raise SynchronousActionError("committed items cannot be given")
        return {"kind": "GIVE", "items": items, "to": target}

    def _parse_commit(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(r"COMMIT (\{[^}]*\})", action)
        if match is None:
            raise SynchronousActionError(f"invalid COMMIT action {action!r}")
        return {"kind": "COMMIT", "items": self._parse_set(match.group(1))}

    def _parse_message(self, agent: str, action: str, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
        if action == "NO MESSAGE":
            return None
        match = re.fullmatch(r"QUERY (\w+) FOR THEIR (GOAL|HOLDINGS)", action)
        if match:
            target, field = match.groups()
            if target not in self.players or target == agent:
                raise SynchronousActionError(f"invalid QUERY target {target!r}")
            return {"kind": "QUERY", "sender": agent, "recipient": target, "field": field}
        match = re.fullmatch(r"INFORM (\w+) MY (GOAL|HOLDINGS) (IS|ARE) (\{[^}]*\})", action)
        if match:
            target, field, verb, raw = match.groups()
            expected = snapshot["goals"][agent] if field == "GOAL" else snapshot["holdings"][agent]
            if (
                target not in self.players
                or target == agent
                or verb != ("IS" if field == "GOAL" else "ARE")
                or self._parse_set(raw) != expected
            ):
                raise SynchronousActionError("INFORM must truthfully disclose current state")
            return {
                "kind": "INFORM",
                "sender": agent,
                "recipient": target,
                "field": field,
                "value": frozenset(expected),
            }
        match = re.fullmatch(r"REQUEST TRANSFER (\{[^}]*\}) FROM (\w+) TO (\w+)", action)
        if match:
            raw_items, giver, receiver = match.groups()
            items = self._parse_set(raw_items)
            if (
                giver not in self.players
                or receiver not in self.players
                or giver == receiver
                or agent != receiver
                or not items
            ):
                raise SynchronousActionError("transfer request has invalid participants or direction")
            return {
                "kind": "TRANSFER",
                "from": giver,
                "to": receiver,
                "items": items,
                "sender": agent,
                "recipient": receiver if agent == giver else giver,
            }
        match = re.fullmatch(r"PROPOSE JOIN WITH (\w+)", action)
        if match:
            target = match.group(1)
            if (
                self.subtype != "collaboration"
                or agent not in snapshot["active"]
                or target == agent
                or target not in snapshot["active"]
            ):
                raise SynchronousActionError("JOIN is only available from an active Collaboration player")
            return {"kind": "JOIN", "sender": agent, "recipient": target}
        raise SynchronousActionError(f"unsupported MESSAGE {action!r}")

    def _parse_decision(
        self,
        agent: str,
        decision: Mapping[str, Any] | Sequence[str] | str,
        snapshot: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if isinstance(decision, str):
            decision = _parse_decision_output(decision, agent=agent)
        if isinstance(decision, Mapping):
            message = _canonicalize_protocol(str(decision.get("message", "NO MESSAGE")))
            actions = tuple(_canonicalize_protocol(str(action)) for action in decision.get("actions", ()))
        else:
            atoms = tuple(_canonicalize_protocol(str(atom)) for atom in decision)
            messages = [atom for atom in atoms if self._is_message_atom(atom)]
            if len(messages) > 1:
                raise SynchronousActionError("at most one MESSAGE is allowed per round")
            message = messages[0] if messages else "NO MESSAGE"
            actions = tuple(atom for atom in atoms if atom not in messages)
        if message != "NO MESSAGE" and not self._is_message_atom(message):
            raise SynchronousActionError("MESSAGE must be one QUERY, INFORM, REQUEST, PROPOSE, or NO MESSAGE")
        legal = set(self.get_legal_actions(agent, snapshot))
        if message != "NO MESSAGE" and message not in legal:
            raise SynchronousActionError("MESSAGE is not legal in the round snapshot")
        if any(action not in legal or self._is_message_atom(action) for action in actions):
            raise SynchronousActionError("ACTIONS contains an illegal or communication action")
        if any(action.startswith("COMMIT ") for action in actions) and (
            len(actions) != 1 or message != "NO MESSAGE"
        ):
            raise SynchronousActionError("COMMIT is exclusive within a round")
        parsed: list[dict[str, Any]] = []
        if message != "NO MESSAGE":
            parsed.append(self._parse_message(agent, message, snapshot))
        for action in actions:
            parsed.append(
                self._parse_give(agent, action, snapshot)
                if action.startswith("GIVE ")
                else self._parse_commit(action)
            )
        return tuple(parsed)

    def _new_message(self, action: Mapping[str, Any]) -> dict[str, Any]:
        message = dict(action)
        message["id"] = self.next_message_id
        self.next_message_id += 1
        message["round"] = self.round_index
        message["text"] = self._message_text(action)
        return message

    def _message_text(self, action: Mapping[str, Any]) -> str:
        kind = action.get("kind")
        if kind == "QUERY":
            field = "GOAL" if action["field"] == "GOAL" else "HOLDINGS"
            return f"{action['sender']} asks {action['recipient']} to reveal {action['recipient']}'s {field}."
        if kind == "INFORM":
            field = "GOAL" if action["field"] == "GOAL" else "HOLDINGS"
            value = action.get("value")
            if value is None:
                return f"{action['sender']} informs {action['recipient']} of their {field}."
            return (
                f"{action['sender']} informs {action['recipient']} that their {field} are "
                f"{_format_set(set(value))}."
            )
        if kind == "JOIN":
            return f"{action['sender']} asks {action['recipient']} to form a coalition."
        if kind == "TRANSFER":
            return (
                f"{action['sender']} asks {action['from']} to give "
                f"{_format_set(set(action['items']))} to {action['to']}."
            )
        raise SynchronousActionError(f"cannot format unknown message kind {kind!r}")

    def _apply_transfer(
        self, giver: str, receiver: str, items: frozenset[str], *, request: bool = False
    ) -> None:
        self.holdings[giver] -= set(items)
        self.holdings[receiver].update(items)
        self.transfers.append({
            "round": self.round_index,
            "from": giver,
            "to": receiver,
            "items": sorted(items),
            "request": request,
        })
        self.metrics["transfers"] += 1
        self.inboxes[receiver].append({
            "round": self.round_index,
            "text": f"{giver}: GIVE {_format_set(items)} TO {receiver}",
            "from": giver,
        })

    def resolve_responses(
        self, responses: Mapping[int | str, str], snapshot: Mapping[str, Any] | None = None
    ) -> None:
        if snapshot is None:
            snapshot = self.build_response_snapshot()
        pending = list(self.pending_messages)
        expected_ids = {message["id"] for message in pending}
        normalized: dict[int, str] = {}
        for key, value in responses.items():
            try:
                message_id = int(key)
            except (TypeError, ValueError) as exc:
                raise SynchronousActionError("response key must be a message id") from exc
            normalized[message_id] = _normalize(value)
        if set(normalized) != expected_ids:
            raise SynchronousActionError("every pending communication needs exactly one response")
        response_transfers: list[tuple[str, str, frozenset[str], bool]] = []
        consumed: dict[str, set[str]] = {}
        for message in pending:
            response = normalized[message["id"]]
            if response not in self.response_actions(message):
                raise SynchronousActionError("invalid mandatory response")
            if message["kind"] == "QUERY":
                requester = message["sender"]
                responder = message["recipient"]
                field = message["field"]
                values = self.goals[responder] if field == "GOAL" else self.holdings[responder]
                self.known[requester].setdefault(responder, {})[field] = set(values)
                self.inboxes[requester].append({
                    "round": self.round_index,
                    "message_id": message["id"],
                    "text": (
                        f"{responder} informs you that their {field} "
                        f"{'is' if field == 'GOAL' else 'are'} "
                        f"{_format_set(values)}."
                    ),
                    "from": responder,
                })
                self.metrics["informs_sent"] += 1
                continue
            proposer = message["sender"]
            recipient = message["recipient"]
            self.inboxes[proposer].append({
                "round": self.round_index,
                "message_id": message["id"],
                "text": self._response_event_text(message, response),
                "from": recipient,
            })
            if message["kind"] == "TRANSFER":
                is_request = (
                    self.subtype == "respond_to_give_request"
                    and message["from"] == "P0"
                    and message["to"] != "P0"
                    and message["sender"] != "P0"
                )
                self.metrics["request_responded"] += int(is_request)
                if response.endswith(": REJECT"):
                    self.metrics["requests_rejected"] += 1
                    self.metrics["proposals_rejected"] += 1
                    if is_request and self.instance.request_case == "harmful":
                        self.metrics["harmful_give_refused"] += 1
                    continue
                self.metrics["requests_given"] += 1
                self.metrics["proposals_accepted"] += 1
                giver = message["from"]
                items = frozenset(message["items"])
                if message["recipient"] != giver:
                    raise SynchronousActionError("only the requested giver can respond with GIVE")
                if not items.issubset(snapshot["holdings"][giver]):
                    raise SynchronousActionError("response GIVE contains an item not held by the giver")
                if set(items).intersection(self.committed.get(giver, ())):
                    raise SynchronousActionError("committed items cannot be given in response")
                if set(items) & consumed.setdefault(giver, set()):
                    raise SynchronousActionError("the same item cannot be given twice in one response phase")
                consumed[giver].update(items)
                response_transfers.append((giver, message["to"], items, is_request))
                if is_request and self.instance.request_case == "safe":
                    self.metrics["safe_give_correct"] += 1
                continue

            if response.endswith(": INACTIVE"):
                self.metrics["proposals_rejected"] += 1
                continue
            accepted = response.endswith(": ACCEPT")
            if accepted:
                self.metrics["proposals_accepted"] += 1
                members = frozenset({message["sender"], message["recipient"]})
                self.coalition = {"members": members, "accepted": True}
                self.join_accepted = True
                self.agreements.append({
                    "type": "JOIN", "members": members, "accepted": True, "fulfilled": False,
                })
            else:
                self.metrics["proposals_rejected"] += 1
        for giver, receiver, items, is_request in response_transfers:
            self._apply_transfer(giver, receiver, items, request=is_request)
        self.pending_messages = []

    def _response_event_text(self, message: Mapping[str, Any], response: str) -> str:
        if message["kind"] == "TRANSFER":
            items = _format_set(set(message["items"]))
            if response.endswith(": REJECT"):
                return f"{message['recipient']} rejected the request to give {items}."
            return f"{message['recipient']} gave {items} to {message['to']}."
        if response.endswith(": ACCEPT"):
            return f"{message['recipient']} accepted the coalition proposal."
        if response.endswith(": INACTIVE"):
            return f"{message['recipient']} is inactive and cannot join."
        return f"{message['recipient']} rejected the coalition proposal."

    def resolve_round(
        self,
        decisions: Mapping[str, Mapping[str, Any] | Sequence[str] | str],
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        if snapshot is None:
            snapshot = self.build_round_snapshot()
        active = tuple(snapshot["active"])
        if set(decisions) != set(active):
            raise SynchronousActionError("every active player must submit one decision")
        parsed = {agent: self._parse_decision(agent, decisions[agent], snapshot) for agent in active}
        commits = {
            agent: next((action for action in actions if action["kind"] == "COMMIT"), None)
            for agent, actions in parsed.items()
        }
        for agent, commit in commits.items():
            if commit is not None and not commit["items"].issubset(snapshot["holdings"][agent]):
                raise SynchronousActionError("COMMIT contains an item not held in the round snapshot")

        transfer_actions: list[tuple[str, dict[str, Any]]] = []
        consumed: dict[str, set[str]] = {agent: set() for agent in active}
        for agent, actions in parsed.items():
            for action in actions:
                if action["kind"] != "GIVE":
                    continue
                if not action["items"].issubset(snapshot["holdings"][agent]):
                    raise SynchronousActionError("giver does not hold every item in GIVE")
                if set(action["items"]).intersection(snapshot.get("committed", {}).get(agent, ())):
                    raise SynchronousActionError("committed items cannot be given")
                if consumed[agent] & set(action["items"]):
                    raise SynchronousActionError("the same item cannot be given twice in one round")
                consumed[agent].update(action["items"])
                transfer_actions.append((agent, action))

        outgoing: list[dict[str, Any]] = []
        for agent, actions in parsed.items():
            for action in actions:
                if action["kind"] not in {"QUERY", "INFORM", "TRANSFER", "JOIN"}:
                    continue
                if action["kind"] in {"TRANSFER", "JOIN", "QUERY"}:
                    outgoing.append(self._new_message(action))
                    if action["kind"] == "QUERY":
                        self.metrics["queries_sent"] += 1
                    elif action["kind"] == "TRANSFER":
                        self.metrics["requests_sent"] += 1
                        self.metrics["proposals_sent"] += 1  # compatibility alias
                        if (
                            self.subtype == "respond_to_give_request"
                            and action["from"] == "P0"
                            and action["to"] != "P0"
                            and action["sender"] != "P0"
                        ):
                            self.metrics["request_proposed"] += 1
                    else:
                        self.metrics["proposals_sent"] += 1
                else:
                    target = action["recipient"]
                    field = action["field"]
                    values = self.goals[agent] if field == "GOAL" else self.holdings[agent]
                    self.known[target].setdefault(agent, {})[field] = set(values)
                    self.inboxes[target].append({
                        "round": self.round_index,
                        "text": self._message_text(action),
                        "from": agent,
                    })
                    self.metrics["informs_sent"] += 1

        for agent, action in transfer_actions:
            self._apply_transfer(agent, action["to"], action["items"])

        for agent, commit in commits.items():
            if commit is None:
                continue
            self.committed[agent] = set(commit["items"])
            self.active.remove(agent)
            self.metrics["commits"] += 1
            self.public_events.append({
                "round": self.round_index,
                "agent": agent,
                "action": f"COMMIT {_format_set(commit['items'])}",
            })

        # Keep messages addressed to a player that commits in this same
        # round.  That player is inactive next round but remains response-only.
        self.pending_messages = outgoing
        for agent, actions in parsed.items():
            if not actions:
                self.metrics["passes"] += 1
            for action in actions:
                if action["kind"] in {"QUERY", "INFORM", "TRANSFER", "JOIN"}:
                    self.metrics["communications_per_player"][agent] += 1

        self.round_index += 1
        if not self.active:
            self._finish("all_players_committed")
        elif self.round_index >= self.config.max_rounds:
            self._finish("max_rounds")

    def coalition_success(self) -> bool:
        if not self.coalition or not self.coalition.get("accepted"):
            return False
        members = set(self.coalition["members"])
        if not members.issubset(self.committed):
            return False
        pool = set().union(*(self.committed[agent] for agent in members))
        return self.goals["P0"].issubset(pool)

    def scenario_objective_success(self) -> bool:
        # Transfer requests are not agreements.  They either cause an
        # immediate response-phase GIVE or are rejected; only JOIN creates a
        # persistent agreement whose fulfillment is settled at episode end.
        if not all(agreement["fulfilled"] for agreement in self.agreements):
            return False
        if self.subtype == "collaboration":
            return self.coalition_success()
        if self.subtype == "respond_to_give_request":
            # This subtype evaluates a response to an active partner request,
            # not merely whether P0 can commit its own goal.  The partner
            # must have proposed the request and P0 must have responded with
            # the case-appropriate outcome.
            if not (
                self.metrics["request_proposed"] > 0
                and self.metrics["request_responded"] > 0
            ):
                return False
            if self.instance.request_case == "safe" and self.metrics["safe_give_correct"] <= 0:
                return False
            if self.instance.request_case == "harmful" and self.metrics["harmful_give_refused"] <= 0:
                return False
        return "P0" in self.committed and self.goals["P0"].issubset(self.committed["P0"])

    def diagnostics(self) -> dict[str, Any]:
        player_success = {
            agent: agent in self.committed and self.goals[agent].issubset(self.committed[agent])
            for agent in self.players
        }
        result = {
            "player_success": player_success,
            "all_players_success": float(bool(self.players) and all(player_success.values())),
            "scenario_objective_success": float(self.scenario_objective_success()),
            "rounds_used": float(self.round_index),
            "agreements_fulfilled": float(all(agreement["fulfilled"] for agreement in self.agreements)),
            "join_accepted": float(self.join_accepted),
            "request_proposed": float(self.metrics["request_proposed"] > 0),
            "request_responded": float(self.metrics["request_responded"] > 0),
            "safe_give_correct": float(self.metrics["safe_give_correct"]),
            "harmful_give_refused": float(self.metrics["harmful_give_refused"]),
            "terminal_success": float(self.done and self.scenario_objective_success()),
            "task_success": float(self.scenario_objective_success()),
            "invalid_actions": float(self.metrics["invalid_actions"]),
        }
        schema_total = self.metrics["schema_valid_actions"] + self.metrics["schema_invalid_actions"]
        schema_response_total = self.metrics["schema_valid_responses"] + self.metrics["schema_invalid_responses"]
        semantic_total = self.metrics["semantic_valid_actions"] + self.metrics["semantic_invalid_actions"]
        semantic_response_total = self.metrics["semantic_valid_responses"] + self.metrics["semantic_invalid_responses"]
        result.update({
            "schema_valid_rate": float(
                (self.metrics["schema_valid_actions"] + self.metrics["schema_valid_responses"])
                / (schema_total + schema_response_total)
            ) if schema_total + schema_response_total else 0.0,
            "semantic_valid_rate": float(
                (self.metrics["semantic_valid_actions"] + self.metrics["semantic_valid_responses"])
                / (semantic_total + semantic_response_total)
            ) if semantic_total + semantic_response_total else 0.0,
            "tool_call_present_rate": float(
                self.metrics["tool_call_present"]
                / (self.metrics["tool_call_present"] + self.metrics["tool_call_missing"])
            ) if self.metrics["tool_call_present"] + self.metrics["tool_call_missing"] else 0.0,
            "exactly_one_tool_call_rate": float(
                self.metrics["exactly_one_tool_call"]
                / (self.metrics["exactly_one_tool_call"] + self.metrics["not_exactly_one_tool_call"])
            ) if self.metrics["exactly_one_tool_call"] + self.metrics["not_exactly_one_tool_call"] else 0.0,
            "tool_schema_valid_rate": float(
                (self.metrics["schema_valid_actions"] + self.metrics["schema_valid_responses"])
                / (schema_total + schema_response_total)
            ) if schema_total + schema_response_total else 0.0,
        })
        result.update({key: value for key, value in self.metrics.items() if key not in result})
        return result

    def finish_invalid(self, reason: str = "invalid_action") -> None:
        self.metrics["invalid_actions"] += 1
        self._finish(reason)

    def _finish(self, reason: str) -> None:
        if not self.settled:
            # JOIN is an agreement whose fulfillment is decided only at
            # episode end.  A member that never commits therefore cannot
            # satisfy the coalition by free riding on another member.
            coalition_ok = self.coalition_success()
            for agreement in self.agreements:
                if agreement["type"] == "JOIN":
                    agreement["fulfilled"] = coalition_ok
            self.settled = True
        self.done = True
        self.terminal_reason = reason


def _typed_decision_to_legacy(value: Any, *, agent: str | None) -> dict[str, Any]:
    raw_actions = value if isinstance(value, list) else [value]
    if not raw_actions:
        raise StructuredActionError("JSON action array must not be empty")
    actions: list[str] = []
    for raw in raw_actions:
        obj = _require_json_action_object(raw, allowed=DECISION_ACTION_NAMES)
        _validate_action_fields(obj, response=False)
        action = obj["action"]
        if action == "PASS":
            if len(raw_actions) != 1:
                raise StructuredActionError("PASS cannot be combined with another action")
            actions.append("NO MESSAGE")
        elif action == "QUERY":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            field = _json_field(obj.get("field"))
            actions.append(f"QUERY {recipient} FOR THEIR {field}")
        elif action == "INFORM":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            field = _json_field(obj.get("field"))
            values = _require_json_items(obj.get("value"), "value")
            verb = "IS" if field == "GOAL" else "ARE"
            actions.append(f"INFORM {recipient} MY {field} {verb} {_format_set(set(values))}")
        elif action == "REQUEST_TRANSFER":
            if agent is None:
                raise StructuredActionError("agent identity is required to parse REQUEST_TRANSFER")
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            values = _require_json_items(obj.get("items"))
            actions.append(f"REQUEST TRANSFER {_format_set(set(values))} FROM {recipient} TO {agent}")
        elif action == "GIVE":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            values = _require_json_items(obj.get("items"))
            actions.append(f"GIVE {_format_set(set(values))} TO {recipient}")
        elif action == "PROPOSE_JOIN":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            actions.append(f"PROPOSE JOIN WITH {recipient}")
        elif action == "COMMIT":
            values = _require_json_items(obj.get("items"))
            actions.append(f"COMMIT {_format_set(set(values))}")
    if actions == ["NO MESSAGE"]:
        return {"message": "NO MESSAGE", "actions": ()}
    messages = [action for action in actions if SynchronousItemGame._is_message_atom(action)]
    if len(messages) > 1:
        raise StructuredActionError("at most one proactive communication is allowed per round")
    message = messages[0] if messages else "NO MESSAGE"
    return {"message": message, "actions": tuple(action for action in actions if action not in messages)}


def _typed_response_to_legacy(value: Any) -> dict[int, str]:
    raw_actions = value if isinstance(value, list) else [value]
    if not raw_actions:
        raise StructuredActionError("response JSON array must not be empty")
    parsed: dict[int, str] = {}
    for raw in raw_actions:
        obj = _require_json_action_object(raw, allowed=RESPONSE_ACTION_NAMES)
        _validate_action_fields(obj, response=True)
        if not isinstance(obj.get("message_id"), int) or isinstance(obj.get("message_id"), bool):
            raise StructuredActionError("response JSON requires integer message_id")
        message_id = obj["message_id"]
        if message_id in parsed:
            raise StructuredActionError("a message received more than one response")
        action = obj["action"]
        if action == "INFORM":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            field = _json_field(obj.get("field"))
            values = _require_json_items(obj.get("value"), "value")
            verb = "IS" if field == "GOAL" else "ARE"
            response = f"INFORM {recipient} MY {field} {verb} {_format_set(set(values))}"
        elif action == "GIVE":
            recipient = _require_json_string(obj.get("recipient"), "recipient")
            values = _require_json_items(obj.get("items"))
            response = f"GIVE {_format_set(set(values))} TO {recipient}"
        elif action == "REJECT_TRANSFER":
            _require_json_string(obj.get("requester"), "requester")
            _require_json_items(obj.get("items"))
            response = "REJECT"
        elif action == "ACCEPT_JOIN":
            _require_json_string(obj.get("proposer"), "proposer")
            response = "ACCEPT"
        elif action == "REJECT_JOIN":
            _require_json_string(obj.get("proposer"), "proposer")
            response = "REJECT"
        else:
            response = "INACTIVE"
        parsed[message_id] = response
    return parsed


def _parse_response_output(response: str) -> dict[int, str]:
    if _answer_is_json(response):
        return _typed_response_to_legacy(_load_json_answer(response))
    # Models sometimes wrap the same answer in XML, markdown bullets, or an
    # extra RESPONSE label.  Keep the protocol strict after extracting the
    # individual response lines, but do not make formatting part of the task.
    answer = _protocol_text(response)
    parsed: dict[int, str] = {}
    for line in _split_protocol_lines(answer):
        match = re.fullmatch(r"(?:RESPOND|RESPONSE)\s*#(\d+)\s*:\s*(.+)", line, re.IGNORECASE)
        if match is None:
            continue
        message_id = int(match.group(1))
        if message_id in parsed:
            raise SynchronousActionError("a message received more than one response")
        response_text = _canonicalize_protocol(_normalize(match.group(2)))
        if response_text.upper() in {"ACCEPT", "REJECT", "INACTIVE"}:
            response_text = response_text.upper()
        parsed[message_id] = f"RESPOND #{message_id}: {response_text}"
    if not parsed:
        raise SynchronousActionError("response must contain RESPOND #<id>: <response>")
    return parsed


def _parse_decision_output(response: str, *, agent: str | None = None) -> dict[str, Any]:
    if _answer_is_json(response):
        return _typed_decision_to_legacy(_load_json_answer(response), agent=agent)
    lines = _split_protocol_lines(_protocol_text(response))
    candidates: list[str] = []
    saw_empty = False
    for line in lines:
        upper = line.upper()
        if upper in {"NONE", "- NONE", "NO MESSAGE"}:
            saw_empty = True
            continue
        # Backward-compatible extraction for old outputs.  The prompt no
        # longer asks for these headings, but accepting them prevents a
        # formatting mistake from becoming an environment failure.
        if upper.startswith(("MESSAGE:", "ACTIONS:", "ACTION:")):
            payload = line.split(":", 1)[1].strip()
            if not payload or payload.upper() in {"NONE", "- NONE", "NO MESSAGE"}:
                saw_empty = True
                continue
            line = payload
        line = _canonicalize_protocol(line)
        if line == "NO MESSAGE":
            continue
        if line.startswith(("QUERY ", "INFORM ", "REQUEST ", "PROPOSE ", "GIVE ", "COMMIT ")):
            candidates.append(line)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        if saw_empty:
            return {"message": "NO MESSAGE", "actions": ()}
        raise SynchronousActionError("decision contains no recognizable protocol action")
    messages = [line for line in candidates if SynchronousItemGame._is_message_atom(line)]
    if len(messages) > 1:
        raise SynchronousActionError("at most one MESSAGE is allowed per round")
    message = messages[0] if messages else "NO MESSAGE"
    actions = [line for line in candidates if line not in messages]
    return {"message": message, "actions": tuple(actions)}


def _protocol_text(response: str) -> str:
    """Return protocol-bearing text while excluding private reasoning."""
    without_reason = re.sub(
        r"<(?:reason|think)>.*?</(?:reason|think)>", "", response, flags=re.DOTALL | re.IGNORECASE
    )
    blocks = re.findall(
        r"<(?:answer|message|actions)>\s*(.*?)\s*</(?:answer|message|actions)>",
        without_reason,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return "\n".join(blocks) if blocks else without_reason


def _split_protocol_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in re.split(r"[\n;]+", text):
        line = raw_line.strip().strip("`").strip()
        line = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line)
        if line:
            lines.append(_normalize(line))
    return list(dict.fromkeys(lines))


def _canonicalize_protocol(line: str) -> str:
    """Normalize vocabulary aliases used by older pilots.

    ASK/TELL are accepted only as parser aliases.  Legal actions and all
    prompts expose QUERY/INFORM, so new model outputs use the new vocabulary.
    """
    line = _normalize(line).rstrip(".")
    # Normalize command vocabulary and fixed grammar words while preserving
    # opaque item/player identifiers exactly as supplied.
    line = re.sub(r"^ASK(?=\s)", "QUERY", line, flags=re.IGNORECASE)
    line = re.sub(r"^TELL(?=\s)", "INFORM", line, flags=re.IGNORECASE)
    line = re.sub(r"^PROPOSE TRANSFER(?=\s)", "REQUEST TRANSFER", line, flags=re.IGNORECASE)
    match = re.fullmatch(r"QUERY\s+(\w+)\s+FOR\s+THEIR\s+(GOAL|HOLDINGS)", line, re.IGNORECASE)
    if match:
        return f"QUERY {match.group(1)} FOR THEIR {match.group(2).upper()}"
    match = re.fullmatch(
        r"INFORM\s+(\w+)\s+MY\s+(GOAL|HOLDINGS)\s+(IS|ARE)\s+(\{[^}]*\})",
        line,
        re.IGNORECASE,
    )
    if match:
        return (
            f"INFORM {match.group(1)} MY {match.group(2).upper()} "
            f"{match.group(3).upper()} {_normalize(match.group(4))}"
        )
    match = re.fullmatch(
        r"REQUEST\s+TRANSFER\s+(\{[^}]*\})\s+FROM\s+(\w+)\s+TO\s+(\w+)",
        line,
        re.IGNORECASE,
    )
    if match:
        return (
            f"REQUEST TRANSFER {_normalize(match.group(1))} FROM "
            f"{match.group(2)} TO {match.group(3)}"
        )
    match = re.fullmatch(r"PROPOSE\s+JOIN\s+WITH\s+(\w+)", line, re.IGNORECASE)
    if match:
        return f"PROPOSE JOIN WITH {match.group(1)}"
    match = re.fullmatch(r"GIVE\s+(\{[^}]*\})\s+TO\s+(\w+)", line, re.IGNORECASE)
    if match:
        return f"GIVE {_normalize(match.group(1))} TO {match.group(2)}"
    match = re.fullmatch(r"COMMIT\s+(\{[^}]*\})", line, re.IGNORECASE)
    if match:
        return f"COMMIT {_normalize(match.group(1))}"
    if line.upper() == "NO MESSAGE":
        return "NO MESSAGE"
    return line


class SynchronousSelfPlayRunner:
    def __init__(
        self,
        policy: SynchronousSelfPlayPolicy,
        config: ItemGameConfig,
        *,
        instance_factory: Callable[[int, ItemGameConfig], ItemGameInstance] | None = None,
    ):
        self.policy = policy
        self.config = config
        self.instance_factory = instance_factory or (lambda seed, cfg: generate_instance(seed, config=cfg))
        self.contexts: dict[str, list[dict[str, str]]] = {}

    def _call_policy(
        self,
        *,
        agent: str,
        observation: str,
        legal: Sequence[str],
        phase: str,
        action_schema: Mapping[str, Any] | None = None,
        available_actions: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "agent": agent,
            "observation": observation,
            "legal_actions": legal,
            "context": tuple(self.contexts[agent]),
        }
        # Keep compatibility with small test policies written before the
        # schema hook existed.  The vLLM policy consumes this argument.
        if "action_schema" in inspect.signature(self.policy.generate).parameters:
            kwargs["action_schema"] = action_schema
        if "available_actions" in inspect.signature(self.policy.generate).parameters:
            kwargs["available_actions"] = tuple(available_actions)
        backend_output = self.policy.generate(**kwargs)
        if isinstance(backend_output, SelfPlayPolicyOutput):
            if backend_output.output_mode == "native_tools":
                reasoning = backend_output.reason
                calls = backend_output.tool_calls
                tool_call_present = bool(calls)
                exactly_one_tool_call = len(calls) == 1
                content = ""
                tool_schema_valid = False
                tool_error = None
                policy_action = None
                if exactly_one_tool_call:
                    call = calls[0]
                    policy_action = {
                        "tool_name": call.tool_name,
                        "arguments": dict(call.arguments),
                    }
                    try:
                        _validate_tool_call_schema(call, available_actions)
                        tool_schema_valid = True
                        environment_arguments = dict(call.arguments)
                        if call.tool_name == "PASS" and environment_arguments.get("confirm") is True:
                            environment_arguments.pop("confirm")
                        content = json.dumps(
                            {"action": call.tool_name, **environment_arguments},
                            separators=(",", ":"),
                        )
                    except StructuredActionError as exc:
                        tool_error = str(exc)
                raw_response = dict(backend_output.raw_message or {
                    "content": reasoning,
                    "tool_calls": [
                        {"id": call.tool_call_id, "type": "function", "function": {
                            "name": call.tool_name,
                            "arguments": json.dumps(dict(call.arguments), separators=(",", ":")),
                        }} for call in calls
                    ],
                })
                context_response = reasoning
            else:
                reasoning = ""
                raw_content = backend_output.content
                content = raw_content
                try:
                    parsed_content = _load_json_answer(content)
                    if backend_output.output_mode == "reason_action":
                        if isinstance(parsed_content, dict) and isinstance(parsed_content.get("reason"), str):
                            reasoning = parsed_content["reason"]
                        reasoning, action = _unwrap_reason_action(parsed_content)
                    elif backend_output.output_mode == "action_only":
                        action = parsed_content
                        if not isinstance(action, (dict, list)):
                            raise StructuredActionError("action-only content must be an object or array of objects")
                    else:
                        raise StructuredActionError(f"unknown self-play output mode {backend_output.output_mode!r}")
                    content = json.dumps(action, separators=(",", ":"))
                except StructuredActionError:
                    pass
                raw_response = {"reasoning": backend_output.reasoning, "content": raw_content}
                context_response = content
                tool_call_present = None
                exactly_one_tool_call = None
                tool_schema_valid = None
                tool_error = None
                policy_action = None
        else:
            raw = str(backend_output)
            reasoning = _parse_reason(raw)
            content = _answer_text(raw)
            raw_response = raw
            context_response = raw
            tool_call_present = None
            exactly_one_tool_call = None
            tool_schema_valid = None
            tool_error = None
            policy_action = None
        record = {
            "agent": agent,
            "phase": phase,
            "observation": observation,
            "legal_actions": list(legal),
            # This is the environment-owned action space used to build the
            # structured schema. Keep it in the trajectory so a rollout can
            # be audited without reconstructing the game state.
            "available_actions": [dict(definition) for definition in available_actions],
            "reason": reasoning,
            "action": policy_action,
            "reason_is_english": (
                _reason_is_english(reasoning) if reasoning else None
            ),
            "raw_response": raw_response,
            "answer": content,
            "content": content,
            "output_format": (
                "native_tool_call"
                if isinstance(backend_output, SelfPlayPolicyOutput) and backend_output.output_mode == "native_tools"
                else ("json" if _answer_is_json(content) else "legacy_text")
            ),
            "tool_call_present": tool_call_present,
            "tool_call_count": len(backend_output.tool_calls) if isinstance(backend_output, SelfPlayPolicyOutput) and backend_output.output_mode == "native_tools" else None,
            "exactly_one_tool_call": exactly_one_tool_call,
            "tool_schema_valid": tool_schema_valid,
            "tool_error": tool_error,
            "schema_valid": tool_schema_valid,
            "_schema_recorded": False,
            "semantic_valid": None,
            "valid": True,
        }
        self.contexts[agent].extend((
            {"role": "user", "content": observation},
            {"role": "assistant", "content": context_response},
        ))
        return content, {}, record

    @staticmethod
    def _record_schema_result(
        game: SynchronousItemGame,
        record: dict[str, Any],
        *,
        phase: str,
        valid: bool | None = None,
    ) -> None:
        valid = bool(_answer_is_json(record["content"])) if valid is None else valid
        record["schema_valid"] = valid
        key = "schema_valid_actions" if phase == "decision" else "schema_valid_responses"
        invalid_key = "schema_invalid_actions" if phase == "decision" else "schema_invalid_responses"
        game.metrics[key if valid else invalid_key] += 1
        record["_schema_recorded"] = True
        if record.get("tool_call_present") is not None:
            game.metrics["tool_call_present" if record["tool_call_present"] else "tool_call_missing"] += 1
            game.metrics[
                "exactly_one_tool_call" if record["exactly_one_tool_call"] else "not_exactly_one_tool_call"
            ] += 1

    def _retry_observation(
        self,
        observation: str,
        *,
        phase: str,
        error: str,
        attempt: int,
        limit: int,
    ) -> str:
        """Add deterministic environment feedback without changing the snapshot."""
        return (
            f"{observation}\n\n"
            f"Environment feedback (retry {attempt + 1}/{limit}): the previous {phase} "
            f"action was semantically invalid: {error}\n"
            "The game state has not changed. Choose one different action from the "
            "currently available typed actions."
        )

    def run_episode(self, seed: int) -> SynchronousEpisodeResult:
        instance = self.instance_factory(seed, self.config)
        game = SynchronousItemGame(instance, self.config)
        self.contexts = {agent: [] for agent in game.players}
        output_mode = getattr(self.config, "output_mode", "native_tools")
        if output_mode not in {"native_tools", "reason_action", "action_only"}:
            raise ValueError("unknown config.output_mode")
        if isinstance(self.policy, VLLMSelfPlayPolicy):
            # Keep direct ``ItemGameConfig(output_mode=...)`` construction
            # consistent with the CLI path.
            self.policy.output_mode = output_mode
        include_action_templates = not isinstance(self.policy, VLLMSelfPlayPolicy)
        rounds: list[dict[str, Any]] = []

        while not game.done:
            round_record: dict[str, Any] = {"round": game.round_index, "responses": [], "decisions": []}
            response_snapshot = game.build_response_snapshot()
            requests = game.response_requests()
            responses: dict[int, str] = {}
            # Native protocol requires exactly one tool call per model turn.
            # Resolve multiple pending messages as separate response turns,
            # while retaining the same immutable response snapshot and atomic
            # environment resolution at the end of the phase.
            request_batches = [
                (str(request["recipient"]), [request]) for request in requests
            ]
            for agent, agent_requests in request_batches:
                automatic = {
                    request["id"]: f"RESPOND #{request['id']}: INACTIVE"
                    for request in agent_requests
                    if request["kind"] == "JOIN" and request["recipient"] not in game.active
                }
                model_requests = [request for request in agent_requests if request["id"] not in automatic]
                if automatic:
                    round_record["responses"].append({
                        "agent": agent,
                        "phase": "response",
                        "observation": "automatic INACTIVE response for committed player",
                        "legal_actions": [automatic[request["id"]] for request in agent_requests if request["id"] in automatic],
                        "reason": "",
                        "raw_response": "",
                        "answer": "\n".join(automatic.values()),
                        "valid": True,
                        "automatic": True,
                    })
                    responses.update(automatic)
                if not model_requests:
                    continue
                observation = game.get_response_observation(model_requests, response_snapshot)
                legal = game.get_response_action_templates(agent)
                available_actions = game.get_available_actions(
                    agent, phase="response", requests=model_requests, snapshot=response_snapshot
                )
                action_schema = game.get_action_schema(
                    agent,
                    response=True,
                    output_mode=output_mode,
                    requests=model_requests,
                )
                response_succeeded = False
                for retry_index in range(self.config.max_invalid_retries_per_decision + 1):
                    raw, _, record = self._call_policy(
                        agent=agent,
                        observation=observation,
                        legal=legal,
                        phase="response",
                        action_schema=action_schema,
                        available_actions=available_actions,
                    )
                    record["retry_index"] = retry_index
                    try:
                        parsed = _parse_response_output(raw)
                        record["semantic_valid"] = True
                        if _answer_is_json(raw):
                            _validate_json_enums(
                                _load_json_answer(raw),
                                players=game.players,
                                items=game.items,
                                response=True,
                                message_ids=tuple(message["id"] for message in model_requests),
                            )
                        self._record_schema_result(game, record, phase="response")
                        expected = {message["id"] for message in model_requests}
                        if set(parsed) != expected:
                            raise SynchronousActionError("response must cover every incoming message exactly once")
                        if _answer_is_json(raw):
                            _validate_json_response_references(_load_json_answer(raw), model_requests)
                        for message in model_requests:
                            if parsed[message["id"]] not in game.response_actions(message):
                                raise SynchronousActionError("response is not legal for its message")
                        game.metrics["semantic_valid_responses"] += 1
                        responses.update(parsed)
                        round_record["responses"].append(record)
                        response_succeeded = True
                        break
                    except SynchronousActionError as exc:
                        if not record["_schema_recorded"]:
                            self._record_schema_result(game, record, phase="response", valid=False)
                        record["semantic_valid"] = False
                        retryable = record["schema_valid"] is True and not isinstance(exc, StructuredActionError)
                        if retryable:
                            game.metrics["semantic_invalid_responses"] += 1
                        record["valid"] = False
                        record["error_type"] = "schema" if isinstance(exc, StructuredActionError) else "semantic"
                        record["error"] = str(exc)
                        record["retryable"] = retryable
                        round_record["responses"].append(record)
                        if retryable and retry_index < self.config.max_invalid_retries_per_decision:
                            game.metrics["invalid_response_retries"] += 1
                            observation = self._retry_observation(
                                observation,
                                phase="response",
                                error=str(exc),
                                attempt=retry_index,
                                limit=self.config.max_invalid_retries_per_decision,
                            )
                            continue
                        game.finish_invalid("invalid_response")
                        break
                if game.done:
                    break
                if not response_succeeded:
                    game.finish_invalid("invalid_response")
                    break
            if game.done:
                rounds.append(round_record)
                break
            if requests:
                try:
                    game.resolve_responses(responses, response_snapshot)
                except SynchronousActionError as exc:
                    game.finish_invalid("invalid_response")
                    round_record["response_error"] = str(exc)
                    rounds.append(round_record)
                    break

            decision_snapshot = game.build_round_snapshot()
            decisions: dict[str, Mapping[str, Any]] = {}
            for agent in decision_snapshot["active"]:
                observation = game.get_observation(
                    agent,
                    decision_snapshot,
                    include_action_templates=include_action_templates,
                )
                legal = game.get_action_templates(agent)
                available_actions = game.get_available_actions(
                    agent, phase="decision", snapshot=decision_snapshot
                )
                action_schema = game.get_action_schema(
                    agent, output_mode=output_mode
                )
                decision_succeeded = False
                for retry_index in range(self.config.max_invalid_retries_per_decision + 1):
                    raw, _, record = self._call_policy(
                        agent=agent,
                        observation=observation,
                        legal=legal,
                        phase="decision",
                        action_schema=action_schema,
                        available_actions=available_actions,
                    )
                    record["retry_index"] = retry_index
                    try:
                        decision = _parse_decision_output(raw, agent=agent)
                        record["semantic_valid"] = True
                        if _answer_is_json(raw):
                            _validate_json_enums(
                                _load_json_answer(raw),
                                players=game.players,
                                items=game.items,
                                response=False,
                            )
                        self._record_schema_result(game, record, phase="decision")
                        game._parse_decision(agent, decision, decision_snapshot)
                        game.metrics["semantic_valid_actions"] += 1
                        decisions[agent] = decision
                        round_record["decisions"].append(record)
                        decision_succeeded = True
                        break
                    except SynchronousActionError as exc:
                        if not record["_schema_recorded"]:
                            self._record_schema_result(game, record, phase="decision", valid=False)
                        record["semantic_valid"] = False
                        retryable = record["schema_valid"] is True and not isinstance(exc, StructuredActionError)
                        if retryable:
                            game.metrics["semantic_invalid_actions"] += 1
                        record["valid"] = False
                        record["error_type"] = "schema" if isinstance(exc, StructuredActionError) else "semantic"
                        record["error"] = str(exc)
                        record["retryable"] = retryable
                        round_record["decisions"].append(record)
                        if retryable and retry_index < self.config.max_invalid_retries_per_decision:
                            game.metrics["invalid_action_retries"] += 1
                            observation = self._retry_observation(
                                observation,
                                phase="decision",
                                error=str(exc),
                                attempt=retry_index,
                                limit=self.config.max_invalid_retries_per_decision,
                            )
                            continue
                        break
                if not decision_succeeded:
                    game.finish_invalid("invalid_action")
                    break
            # A retryable failed attempt is intentionally retained in the
            # trajectory. It must not invalidate the round when a later
            # attempt for the same agent succeeded.
            if game.done:
                rounds.append(round_record)
                break
            try:
                game.resolve_round(decisions, decision_snapshot)
            except SynchronousActionError as exc:
                game.finish_invalid("invalid_action")
                round_record["decision_error"] = str(exc)
                rounds.append(round_record)
                break
            rounds.append(round_record)

        remap = {"EGO": "P0"}
        remap.update({agent: agent for agent in instance.goals if agent != "EGO"})
        diagnostics = game.diagnostics()
        terminal = {
            "done": game.done,
            "reason": game.terminal_reason,
            "active_players": list(game.active_players),
            "holdings": {agent: sorted(items) for agent, items in game.holdings.items()},
            "committed": {agent: sorted(items) for agent, items in game.committed.items()},
            "player_success": diagnostics["player_success"],
            "scenario_objective_success": game.scenario_objective_success(),
        }
        return SynchronousEpisodeResult(
            seed=seed,
            subtype=instance.subtype,
            ground_truth={
                "agents": list(game.players),
                "goals": {remap[agent]: sorted(goal) for agent, goal in instance.goals.items()},
                "initial_holdings": {remap[agent]: sorted(items) for agent, items in instance.holdings.items()},
                "active_partner": remap.get(instance.active_partner, instance.active_partner),
                "request_case": instance.request_case,
                "partner_roles": {remap.get(agent, agent): role for agent, role in instance.partner_roles.items()},
                "partner_policies": {remap.get(agent, agent): policy for agent, policy in instance.partner_policies.items()},
            },
            rounds=rounds,
            terminal=terminal,
            diagnostics=diagnostics,
        )


class VLLMSelfPlayPolicy:
    """OpenAI-compatible vLLM policy using Qwen-native function calls."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "EMPTY",
        max_new_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 300.0,
        enable_thinking: bool = False,
        output_mode: str = "native_tools",
        native_tool_choice: str = "auto",
    ):
        if output_mode not in {"native_tools", "reason_action", "action_only"}:
            raise ValueError("unknown output_mode")
        if native_tool_choice not in {"auto", "required"}:
            raise ValueError("native_tool_choice must be 'auto' or 'required'")
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.model = model
        self.api_key = api_key
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.enable_thinking = enable_thinking
        self.output_mode = output_mode
        self.native_tool_choice = native_tool_choice

    def generate(
        self,
        *,
        agent: str,
        observation: str,
        legal_actions: Sequence[str],
        context: Sequence[Mapping[str, str]],
        action_schema: Mapping[str, Any] | None = None,
        available_actions: Sequence[Mapping[str, Any]] | None = None,
    ) -> SelfPlayPolicyOutput:
        if available_actions is None or not available_actions:
            raise ValueError("vLLM policy requires environment-owned available_actions")
        if self.output_mode == "native_tools":
            output_instructions = (
                "Briefly reason about the relevant private state, interaction history, and next interaction "
                "in normal assistant content. Keep it concise. Then make exactly one available ItemGame "
                "tool call. The content is private and must not contain or serialize the action."
            )
        elif self.output_mode == "reason_action":
            output_instructions = (
                "Return a JSON object with a non-empty string field 'reason' and an 'action' field. "
                "The value of 'action' must be a JSON object, never a natural-language string. "
                "Briefly reason about the relevant private state, interaction history, and what should happen next. "
                "Keep the reasoning concise and write it in English only. "
                "The reason is private and must not be put inside action."
            )
        else:
            output_instructions = (
                "Return only the executable JSON action value required by the schema. Do not include a reason field."
            )
        system = (
            f"You are {agent}. All players have equal status in a synchronous multi-agent game. "
            f"Follow the action semantics in the user message. {output_instructions} "
            "Do not invent players or items. Every INFORM value must be your own truthful current state."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(dict(message) for message in context)
        messages.append({
            "role": "user",
            "content": observation,
        })
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_new_tokens,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        if self.output_mode == "native_tools":
            body.update({
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": str(definition["name"]),
                            "description": str(definition.get("description", "")),
                            "parameters": dict(definition["arguments"]),
                        },
                    }
                    for definition in available_actions
                ],
                "tool_choice": self.native_tool_choice,
            })
        else:
            if action_schema is None:
                raise ValueError("legacy envelope mode requires an action schema")
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "item_game_action",
                    "schema": dict(action_schema),
                    "strict": True,
                },
            }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            message = payload["choices"][0]["message"]
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            if self.output_mode != "native_tools":
                if not content.strip():
                    raise ValueError("vLLM response did not contain final JSON content")
                return SelfPlayPolicyOutput(
                    content=content,
                    usage=dict(payload.get("usage") or {}),
                    output_mode=self.output_mode,
                )
            parsed_calls: list[ItemGameToolCall] = []
            for raw_call in message.get("tool_calls") or ():
                function = raw_call.get("function") or {}
                raw_arguments = function.get("arguments", "")
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except json.JSONDecodeError:
                    arguments = {"__malformed_arguments__": raw_arguments}
                if not isinstance(arguments, Mapping):
                    arguments = {"__non_object_arguments__": arguments}
                parsed_calls.append(ItemGameToolCall(
                    tool_name=str(function.get("name", "")),
                    arguments=dict(arguments),
                    tool_call_id=str(raw_call.get("id", "")),
                ))
            return SelfPlayPolicyOutput(
                reason=content,
                tool_calls=tuple(parsed_calls),
                raw_message=dict(message),
                usage=dict(payload.get("usage") or {}),
                output_mode="native_tools",
            )
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                error_body = ""
            detail = f": {error_body}" if error_body else ""
            raise RuntimeError(
                f"vLLM request failed with HTTP {exc.code}{detail}"
            ) from exc
        except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"vLLM request failed: {exc}") from exc


# Compatibility name for callers that used the initial synchronous-specific
# class name.
VLLMSynchronousSelfPlayPolicy = VLLMSelfPlayPolicy


class HuggingFaceSynchronousSelfPlayPolicy:
    """One shared HF model used for every active player."""

    def __init__(self, model_path: str, *, max_new_tokens: int = 1024, device: str = "auto"):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("requires torch and transformers") from exc
        self.max_new_tokens = max_new_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model_device = device if device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.bfloat16 if model_device.startswith("cuda") else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=dtype,
            device_map="auto" if device == "auto" else None,
            trust_remote_code=True,
        )
        if device != "auto":
            self.model.to(model_device)
        self._torch = torch

    def generate(
        self,
        *,
        agent: str,
        observation: str,
        legal_actions: Sequence[str],
        context: Sequence[Mapping[str, str]],
    ) -> str:
        system = (
            f"You are {agent}. All players have equal status in a synchronous multi-agent game. "
            "There are two completely separate phases. In RESPONSE PHASE, respond to every "
            "previous-round message exactly once using one JSON response object per message, and take no new action. "
            "In DECISION PHASE, all previous mandatory responses are complete. Do not output "
            "ACCEPT, REJECT, or response-only INFORM actions. Output one JSON action object, or a JSON "
            "array when combining a message with a compatible state action. Do not output prose or "
            "MESSAGE/ACTIONS labels. Use the typed action shapes in the user message. "
            "QUERY and INFORM send directed information messages. REQUEST TRANSFER asks the FROM "
            "player to give ITEMS to the requester; the requester does not need to hold the requested "
            "item. The owner responds with GIVE or REJECT, and GIVE transfers the items immediately. "
            "GIVE can also be a proactive transfer of your own items. "
            "PROPOSE JOIN creates an agreement only after ACCEPT. COMMIT is public, one-shot, and exclusive. "
            "Every INFORM value must be supplied by you and must be truthful. Keep reasoning private. "
            "Return <reason>...</reason> and exactly one <answer>...</answer> containing JSON."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(dict(message) for message in context)
        messages.append({
            "role": "user",
            "content": observation + "\n\nTyped action shapes:\n" + "\n".join(legal_actions),
        })
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        generated = output[0, inputs["input_ids"].shape[-1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True)


def _build_config(subtype: str, max_rounds: int) -> ItemGameConfig:
    if subtype == "collaboration":
        return ItemGameConfig(generator="pure_collaboration", subtype=subtype, self_play=True, max_rounds=max_rounds)
    return ItemGameConfig(generator="mixed_incentive", subtype=subtype, self_play=True, max_rounds=max_rounds)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run synchronous ItemGame self-play")
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--backend",
        choices=("hf", "vllm"),
        default="vllm",
        help="inference backend; vllm is the schema-constrained default, hf is an unconstrained legacy ablation",
    )
    parser.add_argument("--vllm-base-url", default="http://localhost:8000/v1")
    parser.add_argument("--vllm-api-key", default="EMPTY")
    parser.add_argument(
        "--output-mode",
        choices=("native_tools", "reason_action", "action_only"),
        default="native_tools",
        help="vLLM protocol; native_tools is the formal protocol, others are A/B baselines",
    )
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=840000)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--max-invalid-retries", type=int, default=1)
    parser.add_argument(
        "--tool-choice",
        choices=("auto", "required"),
        default="auto",
        help="vLLM native tool choice; auto matches the validated Qwen3/Hermes smoke test",
    )
    parser.add_argument("--subtype", choices=("all", *SynchronousItemGame.SUPPORTED_SUBTYPES), default="all")
    parser.add_argument("--output", type=Path, default=Path("item_game_synchronous_self_play.jsonl"))
    args = parser.parse_args()
    if args.max_invalid_retries < 0:
        parser.error("--max-invalid-retries must be non-negative")
    if args.backend == "vllm":
        policy = VLLMSynchronousSelfPlayPolicy(
            args.vllm_base_url,
            args.model,
            api_key=args.vllm_api_key,
            max_new_tokens=args.max_new_tokens,
            output_mode=args.output_mode,
            native_tool_choice=args.tool_choice,
        )
    else:
        policy = HuggingFaceSynchronousSelfPlayPolicy(args.model, max_new_tokens=args.max_new_tokens)
    subtypes = list(SynchronousItemGame.SUPPORTED_SUBTYPES) if args.subtype == "all" else [args.subtype]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for subtype_index, subtype in enumerate(subtypes):
            config = _build_config(subtype, args.max_rounds)
            config.max_invalid_retries_per_decision = args.max_invalid_retries
            config.output_mode = args.output_mode
            runner = SynchronousSelfPlayRunner(policy, config)
            for episode in range(args.episodes):
                seed = args.seed + subtype_index * 10000 + episode
                handle.write(json.dumps(runner.run_episode(seed).to_dict(), ensure_ascii=False) + "\n")
    print(f"wrote synchronous self-play results to {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
