"""Synchronous, symmetric test-only self-play for the new ItemGame suite.

The runtime has two separate phases per round.  First, each agent answers all
mandatory messages from the previous round.  Then all active agents choose one
optional MESSAGE and zero or more ACTIONS from the same immutable snapshot.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .config import ItemGameConfig
from .generator import ItemGameInstance, generate_instance


class SynchronousSelfPlayPolicy(Protocol):
    def generate(
        self,
        *,
        agent: str,
        observation: str,
        legal_actions: Sequence[str],
        context: Sequence[Mapping[str, str]],
    ) -> str:
        ...


class SynchronousActionError(ValueError):
    """A model action or response is not legal in the supplied snapshot."""


def _format_set(items: set[str] | frozenset[str]) -> str:
    return "{" + ",".join(sorted(items)) + "}"


def _normalize(text: str) -> str:
    text = " ".join(str(text).strip().split())
    return re.sub(r"\s*,\s*", ",", text)


def _answer_text(response: str) -> str:
    match = re.search(r"<answer>\s*(.*?)\s*</answer>\s*$", response, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else response.strip()


def _parse_reason(response: str) -> str:
    match = re.search(r"<reason>\s*(.*?)\s*</reason>", response, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


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

    def get_observation(self, agent: str, snapshot: Mapping[str, Any] | None = None) -> str:
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
            "Do NOT output ACCEPT, REJECT, or response-only TELL actions here.",
            "Choose exactly one MESSAGE (or NO MESSAGE) and zero or more ACTIONS.",
            "MESSAGE may be at most one ASK, TELL, or PROPOSE. ACTIONS may contain multiple legal actions.",
            "COMMIT is exclusive: if you COMMIT, do not include any other ACTION.",
            "Return exactly:",
            "MESSAGE: <one message or NO MESSAGE>",
            "ACTIONS:",
            "- <action>",
            "Use ACTIONS: followed by no entries, or - NONE, when there are no actions.",
            "Legal MESSAGE choices:",
        ])
        legal = self.get_legal_actions(agent, snap)
        lines.extend(f"- {action}" for action in legal if self._is_message_atom(action))
        lines.append("- NO MESSAGE")
        lines.append("Legal ACTION choices:")
        lines.extend(f"- {action}" for action in legal if not self._is_message_atom(action))
        lines.append("- NONE")
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
        lines = [
            "You are an agent in a synchronous Item Coalition Game.",
            f"Your identity: {agent}",
            f"Your goal: {_format_set(self.goals[agent])}",
            f"Your holdings: {_format_set(self.holdings[agent])}",
            f"Round: {self.round_index}/{self.config.max_rounds}",
            "RESPONSE PHASE.",
            "You are responding to messages from the previous round.",
            "Do not take any new action in this phase.",
            "Respond to every listed message exactly once. Responses are free and do not use the decision MESSAGE slot.",
        ]
        for message in requests:
            lines.extend((
                "",
                f"Message #{message['id']} from {message['sender']}:",
                self._response_message_text(message),
                "Legal response:",
            ))
            lines.extend(f"- {action}" for action in self.response_actions(message))
        lines.extend((
            "",
            "Return exactly one response line per message inside <answer>...</answer>:",
            "RESPOND #<id>: <response>",
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
            return (f"RESPOND #{message_id}: TELL {request['sender']} MY {noun} {verb} {_format_set(values)}",)
        return (f"RESPOND #{message_id}: ACCEPT", f"RESPOND #{message_id}: REJECT")

    def _response_message_text(self, message: Mapping[str, Any]) -> str:
        if message["kind"] == "QUERY":
            field = "GOAL" if message["field"] == "GOAL" else "HOLDINGS"
            return f"{message['sender']} asks YOU to reveal YOUR {field}."
        if message["kind"] == "JOIN":
            return f"{message['sender']} proposes JOIN WITH {message['recipient']}."
        return (
            f"{message['sender']} proposes TRANSFER {_format_set(set(message['items']))} "
            f"FROM {message['from']} TO {message['to']}."
        )

    def _proposal_atoms(self, agent: str, snapshot: Mapping[str, Any]) -> list[str]:
        actions = []
        active = set(snapshot["active"])
        for other in self.players:
            if other == agent or other not in active:
                continue
            for item in self.items:
                item_set = _format_set({item})
                actions.append(f"PROPOSE TRANSFER {item_set} FROM {agent} TO {other}")
                actions.append(f"PROPOSE TRANSFER {item_set} FROM {other} TO {agent}")
        return actions

    def get_legal_actions(
        self, agent: str, snapshot: Mapping[str, Any] | None = None
    ) -> tuple[str, ...]:
        snap = snapshot or self._snapshot()
        if agent not in snap["active"]:
            return ()
        actions: list[str] = []
        active = set(snap["active"])
        for other in self.players:
            if other == agent or other not in active:
                continue
            actions.extend((f"ASK {other} FOR THEIR GOAL", f"ASK {other} FOR THEIR HOLDINGS"))
            actions.extend((
                f"TELL {other} MY GOAL IS {_format_set(set(snap['goals'][agent]))}",
                f"TELL {other} MY HOLDINGS ARE {_format_set(set(snap['holdings'][agent]))}",
            ))
        actions.extend(self._proposal_atoms(agent, snap))
        if self.subtype == "collaboration" and set(self.players) == {"P0", "P1"}:
            actions.append("PROPOSE JOIN WITH P1" if agent == "P0" else "PROPOSE JOIN WITH P0")
        for agreement in snap["agreements"]:
            if (
                agreement["type"] == "TRANSFER"
                and not agreement["fulfilled"]
                and agreement["from"] == agent
                and set(agreement["items"]).issubset(set(snap["holdings"][agent]))
            ):
                actions.append(f"GIVE {_format_set(set(agreement['items']))} TO {agreement['to']}")
        # JOIN is intentionally not required before COMMIT. Final settlement
        # decides whether committed contributions formed a valid coalition.
        actions.extend(f"COMMIT {_format_set(set(subset))}" for subset in self._subsets(set(snap["holdings"][agent])))
        return tuple(dict.fromkeys(actions))

    @staticmethod
    def _is_message_atom(action: str) -> bool:
        return action.startswith(("ASK ", "TELL ", "PROPOSE "))

    def _parse_set(self, raw: str) -> frozenset[str]:
        if not raw.startswith("{") or not raw.endswith("}"):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        values = tuple(value.strip() for value in raw[1:-1].split(",") if value.strip())
        result = frozenset(values)
        if len(result) != len(values) or not result.issubset(set(self.items)):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        return result

    def _parse_give(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(r"GIVE (\{[^}]*\}) TO (\w+)", action)
        if match is None:
            raise SynchronousActionError(f"invalid GIVE action {action!r}")
        return {"kind": "GIVE", "items": self._parse_set(match.group(1)), "to": match.group(2)}

    def _parse_commit(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(r"COMMIT (\{[^}]*\})", action)
        if match is None:
            raise SynchronousActionError(f"invalid COMMIT action {action!r}")
        return {"kind": "COMMIT", "items": self._parse_set(match.group(1))}

    def _parse_message(self, agent: str, action: str, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
        if action == "NO MESSAGE":
            return None
        match = re.fullmatch(r"ASK (\w+) FOR THEIR (GOAL|HOLDINGS)", action)
        if match:
            target, field = match.groups()
            if target not in snapshot["active"] or target == agent:
                raise SynchronousActionError(f"invalid ASK target {target!r}")
            return {"kind": "QUERY", "sender": agent, "recipient": target, "field": field}
        match = re.fullmatch(r"TELL (\w+) MY (GOAL|HOLDINGS) (IS|ARE) (\{[^}]*\})", action)
        if match:
            target, field, verb, raw = match.groups()
            expected = snapshot["goals"][agent] if field == "GOAL" else snapshot["holdings"][agent]
            if (
                target not in snapshot["active"]
                or target == agent
                or verb != ("IS" if field == "GOAL" else "ARE")
                or self._parse_set(raw) != expected
            ):
                raise SynchronousActionError("TELL must truthfully disclose current state")
            return {"kind": "INFORM", "sender": agent, "recipient": target, "field": field}
        match = re.fullmatch(r"PROPOSE TRANSFER (\{[^}]*\}) FROM (\w+) TO (\w+)", action)
        if match:
            raw_items, giver, receiver = match.groups()
            items = self._parse_set(raw_items)
            if (
                giver not in snapshot["active"]
                or receiver not in snapshot["active"]
                or giver == receiver
                or agent not in {giver, receiver}
                or not items
            ):
                raise SynchronousActionError("transfer proposal has invalid participants")
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
                or set(snapshot["active"]) != {"P0", "P1"}
                or target == agent
                or target not in snapshot["active"]
            ):
                raise SynchronousActionError("JOIN is only available to active Collaboration players")
            return {"kind": "JOIN", "sender": agent, "recipient": target}
        raise SynchronousActionError(f"unsupported MESSAGE {action!r}")

    def _parse_decision(
        self,
        agent: str,
        decision: Mapping[str, Any] | Sequence[str] | str,
        snapshot: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if isinstance(decision, str):
            decision = _parse_decision_output(decision)
        if isinstance(decision, Mapping):
            message = str(decision.get("message", "NO MESSAGE"))
            actions = tuple(str(action) for action in decision.get("actions", ()))
        else:
            atoms = tuple(str(atom) for atom in decision)
            messages = [atom for atom in atoms if self._is_message_atom(atom)]
            if len(messages) > 1:
                raise SynchronousActionError("at most one MESSAGE is allowed per round")
            message = messages[0] if messages else "NO MESSAGE"
            actions = tuple(atom for atom in atoms if atom not in messages)
        if message != "NO MESSAGE" and not self._is_message_atom(message):
            raise SynchronousActionError("MESSAGE must be one ASK, TELL, PROPOSE, or NO MESSAGE")
        legal = set(self.get_legal_actions(agent, snapshot))
        if message != "NO MESSAGE" and message not in legal:
            raise SynchronousActionError("MESSAGE is not legal in the round snapshot")
        if any(action not in legal or self._is_message_atom(action) for action in actions):
            raise SynchronousActionError("ACTIONS contains an illegal or communication action")
        if any(action.startswith("COMMIT ") for action in actions) and len(actions) != 1:
            raise SynchronousActionError("COMMIT is exclusive within a round")
        parsed: list[dict[str, Any]] = []
        if message != "NO MESSAGE":
            parsed.append(self._parse_message(agent, message, snapshot))
        for action in actions:
            parsed.append(self._parse_give(action) if action.startswith("GIVE ") else self._parse_commit(action))
        return tuple(parsed)

    def _new_message(self, action: Mapping[str, Any]) -> dict[str, Any]:
        message = dict(action)
        message["id"] = self.next_message_id
        self.next_message_id += 1
        message["round"] = self.round_index
        message["text"] = self._message_text(action)
        return message

    def _message_text(self, action: Mapping[str, Any]) -> str:
        if action["kind"] == "QUERY":
            field = "GOAL" if action["field"] == "GOAL" else "HOLDINGS"
            return f"{action['sender']} asks {action['recipient']} to reveal {action['recipient']}'s {field}."
        if action["kind"] == "JOIN":
            return f"{action['sender']} proposes JOIN WITH {action['recipient']}."
        return (
            f"{action['sender']} proposes TRANSFER {_format_set(set(action['items']))} "
            f"FROM {action['from']} TO {action['to']}."
        )

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
                    "text": response,
                    "from": responder,
                })
                self.metrics["informs_sent"] += 1
                continue
            proposer = message["sender"]
            recipient = message["recipient"]
            accepted = response.endswith(": ACCEPT")
            self.inboxes[proposer].append({
                "round": self.round_index,
                "message_id": message["id"],
                "text": response,
                "from": recipient,
            })
            is_request = (
                self.subtype == "respond_to_give_request"
                and message["kind"] == "TRANSFER"
                and message["from"] == "P0"
                and message["to"] != "P0"
                and message["sender"] != "P0"
            )
            self.metrics["request_responded"] += int(is_request)
            if is_request and not accepted and self.instance.request_case == "harmful":
                self.metrics["harmful_give_refused"] += 1
            if accepted:
                self.metrics["proposals_accepted"] += 1
                if message["kind"] == "JOIN":
                    members = frozenset({message["sender"], message["recipient"]})
                    self.coalition = {"members": members, "accepted": True}
                    self.join_accepted = True
                    self.agreements.append({
                        "type": "JOIN", "members": members, "accepted": True, "fulfilled": False,
                    })
                else:
                    self.agreements.append({
                        "type": "TRANSFER",
                        "from": message["from"],
                        "to": message["to"],
                        "items": frozenset(message["items"]),
                        "fulfilled": False,
                        "request": is_request,
                    })
            else:
                self.metrics["proposals_rejected"] += 1
        self.pending_messages = []

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
                matching = [
                    agreement for agreement in self.agreements
                    if agreement["type"] == "TRANSFER"
                    and not agreement["fulfilled"]
                    and agreement["from"] == agent
                    and agreement["to"] == action["to"]
                    and agreement["items"] == action["items"]
                ]
                if not matching:
                    raise SynchronousActionError("GIVE must match an accepted transfer agreement")
                if not action["items"].issubset(snapshot["holdings"][agent]):
                    raise SynchronousActionError("giver does not hold every transferred item")
                if consumed[agent] & set(action["items"]):
                    raise SynchronousActionError("the same item cannot be transferred twice in one round")
                consumed[agent].update(action["items"])
                transfer_actions.append((agent, action))

        outgoing: list[dict[str, Any]] = []
        committing = {agent for agent, action in commits.items() if action is not None}
        for agent, actions in parsed.items():
            for action in actions:
                if action["kind"] not in {"QUERY", "INFORM", "TRANSFER", "JOIN"}:
                    continue
                if action.get("recipient") in committing or agent in committing:
                    self.metrics["messages_dropped_due_to_commit"] += 1
                    continue
                if action["kind"] in {"TRANSFER", "JOIN", "QUERY"}:
                    outgoing.append(self._new_message(action))
                    if action["kind"] == "QUERY":
                        self.metrics["queries_sent"] += 1
                    else:
                        self.metrics["proposals_sent"] += 1
                        if (
                            self.subtype == "respond_to_give_request"
                            and action["kind"] == "TRANSFER"
                            and action["from"] == "P0"
                            and action["to"] != "P0"
                            and action["sender"] != "P0"
                        ):
                            self.metrics["request_proposed"] += 1
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
            self.holdings[agent] -= set(action["items"])
            self.holdings[action["to"]].update(action["items"])
            for agreement in self.agreements:
                if (
                    agreement["type"] == "TRANSFER"
                    and not agreement["fulfilled"]
                    and agreement["from"] == agent
                    and agreement["to"] == action["to"]
                    and agreement["items"] == action["items"]
                ):
                    agreement["fulfilled"] = True
                    break
            self.transfers.append({"round": self.round_index, "from": agent, **action})
            self.metrics["transfers"] += 1
            self.inboxes[action["to"]].append({
                "round": self.round_index,
                "text": f"{agent}: GIVE {_format_set(action['items'])} TO {action['to']}",
                "from": agent,
            })
            if (
                self.subtype == "respond_to_give_request"
                and agent == "P0"
                and action["to"] != "P0"
                and any(
                    agreement.get("request")
                    and agreement["type"] == "TRANSFER"
                    and agreement["from"] == agent
                    and agreement["to"] == action["to"]
                    and agreement["items"] == action["items"]
                    for agreement in self.agreements
                )
            ):
                self.metrics["safe_give_correct"] += int(self.instance.request_case == "safe")

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
        if not all(agreement["fulfilled"] for agreement in self.agreements if agreement["type"] == "TRANSFER"):
            return False
        if self.subtype == "collaboration":
            return self.coalition_success()
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
            "agreements_fulfilled": float(all(
                agreement["fulfilled"] for agreement in self.agreements if agreement["type"] == "TRANSFER"
            )),
            "join_accepted": float(self.join_accepted),
            "request_proposed": float(self.metrics["request_proposed"] > 0),
            "request_responded": float(self.metrics["request_responded"] > 0),
            "safe_give_correct": float(self.metrics["safe_give_correct"]),
            "harmful_give_refused": float(self.metrics["harmful_give_refused"]),
            "terminal_success": float(self.done and self.scenario_objective_success()),
            "invalid_actions": float(self.metrics["invalid_actions"]),
        }
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


def _parse_response_output(response: str) -> dict[int, str]:
    answer = _answer_text(response)
    parsed: dict[int, str] = {}
    for line in answer.splitlines():
        line = _normalize(line.lstrip("- "))
        if not line:
            continue
        match = re.fullmatch(r"RESPOND #(\d+): (.+)", line)
        if match is None:
            raise SynchronousActionError("response must use RESPOND #<id>: <response>")
        message_id = int(match.group(1))
        if message_id in parsed:
            raise SynchronousActionError("a message received more than one response")
        parsed[message_id] = line
    return parsed


def _parse_decision_output(response: str) -> dict[str, Any]:
    answer = _answer_text(response)
    lines = [line.rstrip() for line in answer.splitlines() if line.strip()]
    message_line = next((line for line in lines if line.strip().upper().startswith("MESSAGE:")), None)
    actions_index = next((index for index, line in enumerate(lines) if line.strip().upper().startswith("ACTIONS:")), None)
    if message_line is None or actions_index is None:
        raise SynchronousActionError("decision must contain MESSAGE: and ACTIONS:")
    message = _normalize(message_line.split(":", 1)[1])
    actions: list[str] = []
    actions_header = lines[actions_index].split(":", 1)[1].strip()
    action_lines = lines[actions_index + 1:]
    if actions_header and actions_header.upper() not in {"NONE", "- NONE"}:
        action_lines.insert(0, actions_header)
    for line in action_lines:
        line = line.strip()
        if line.upper() in {"NONE", "- NONE"}:
            continue
        if not line.startswith("-"):
            raise SynchronousActionError("each ACTIONS entry must start with '-'")
        actions.append(_normalize(line[1:]))
    return {"message": message, "actions": tuple(actions)}


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
        self, *, agent: str, observation: str, legal: Sequence[str], phase: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        raw = str(self.policy.generate(
            agent=agent,
            observation=observation,
            legal_actions=legal,
            context=tuple(self.contexts[agent]),
        ))
        record = {
            "agent": agent,
            "phase": phase,
            "observation": observation,
            "legal_actions": list(legal),
            "reason": _parse_reason(raw),
            "raw_response": raw,
            "answer": _answer_text(raw),
            "valid": True,
        }
        self.contexts[agent].extend((
            {"role": "user", "content": observation},
            {"role": "assistant", "content": raw},
        ))
        return raw, {}, record

    def run_episode(self, seed: int) -> SynchronousEpisodeResult:
        instance = self.instance_factory(seed, self.config)
        game = SynchronousItemGame(instance, self.config)
        self.contexts = {agent: [] for agent in game.players}
        rounds: list[dict[str, Any]] = []

        while not game.done:
            round_record: dict[str, Any] = {"round": game.round_index, "responses": [], "decisions": []}
            response_snapshot = game.build_response_snapshot()
            requests = game.response_requests()
            responses: dict[int, str] = {}
            by_recipient: dict[str, list[dict[str, Any]]] = {}
            for request in requests:
                by_recipient.setdefault(str(request["recipient"]), []).append(request)
            for agent, agent_requests in by_recipient.items():
                observation = game.get_response_observation(agent_requests, response_snapshot)
                legal = tuple(action for request in agent_requests for action in game.response_actions(request))
                raw, _, record = self._call_policy(agent=agent, observation=observation, legal=legal, phase="response")
                try:
                    parsed = _parse_response_output(raw)
                    expected = {message["id"] for message in agent_requests}
                    if set(parsed) != expected:
                        raise SynchronousActionError("response must cover every incoming message exactly once")
                    for message in agent_requests:
                        if parsed[message["id"]] not in game.response_actions(message):
                            raise SynchronousActionError("response is not legal for its message")
                    responses.update(parsed)
                except SynchronousActionError as exc:
                    record["valid"] = False
                    record["error"] = str(exc)
                    round_record["responses"].append(record)
                    game.finish_invalid("invalid_response")
                    break
                round_record["responses"].append(record)
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
                observation = game.get_observation(agent, decision_snapshot)
                legal = game.get_legal_actions(agent, decision_snapshot)
                raw, _, record = self._call_policy(agent=agent, observation=observation, legal=legal, phase="decision")
                try:
                    decision = _parse_decision_output(raw)
                    game._parse_decision(agent, decision, decision_snapshot)
                    decisions[agent] = decision
                except SynchronousActionError as exc:
                    record["valid"] = False
                    record["error"] = str(exc)
                    decisions[agent] = {"message": "NO MESSAGE", "actions": ()}
                round_record["decisions"].append(record)
            invalid = next((record for record in round_record["decisions"] if not record["valid"]), None)
            if invalid is not None:
                game.finish_invalid("invalid_action")
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
            "previous-round message exactly once using RESPOND #<id>: ..., and take no new action. "
            "In DECISION PHASE, all previous mandatory responses are complete. Do not output "
            "ACCEPT, REJECT, or response-only TELL actions. Output exactly MESSAGE: ... and "
            "ACTIONS: with zero or more dash-prefixed actions. MESSAGE is at most one ASK, TELL, "
            "PROPOSE, or NO MESSAGE; ACTIONS are state-changing actions only. COMMIT is exclusive. "
            "Keep reasoning private. Return <reason>...</reason> and exactly one <answer>...</answer>."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(dict(message) for message in context)
        messages.append({
            "role": "user",
            "content": observation + "\n\nLegal actions:\n" + "\n".join(legal_actions),
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
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=840000)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--subtype", choices=("all", *SynchronousItemGame.SUPPORTED_SUBTYPES), default="all")
    parser.add_argument("--output", type=Path, default=Path("item_game_synchronous_self_play.jsonl"))
    args = parser.parse_args()
    policy = HuggingFaceSynchronousSelfPlayPolicy(args.model, max_new_tokens=args.max_new_tokens)
    subtypes = list(SynchronousItemGame.SUPPORTED_SUBTYPES) if args.subtype == "all" else [args.subtype]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for subtype_index, subtype in enumerate(subtypes):
            config = _build_config(subtype, args.max_rounds)
            runner = SynchronousSelfPlayRunner(policy, config)
            for episode in range(args.episodes):
                seed = args.seed + subtype_index * 10000 + episode
                handle.write(json.dumps(runner.run_episode(seed).to_dict(), ensure_ascii=False) + "\n")
    print(f"wrote synchronous self-play results to {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
