"""Synchronous, symmetric test-only self-play for the new ItemGame suite.

This module deliberately does not reuse the sequential Ego/partner runner.
Every active player receives one decision per round from the same immutable
round snapshot.  Communications are delivered in the following round's
response phase; state-changing actions are resolved atomically.
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
    """A model action/bundle is not legal in the supplied snapshot."""


def _format_set(items: set[str] | frozenset[str]) -> str:
    return "{" + ",".join(sorted(items)) + "}"


def _normalize_atom(action: str) -> str:
    action = " ".join(str(action).strip().split())
    action = re.sub(r"\s*=\s*", "=", action)
    action = re.sub(r"\s*,\s*", ",", action)
    return action


def _parse_bundle(response: str) -> tuple[str, ...]:
    answer = response
    match = re.search(r"<answer>\s*(.*?)\s*</answer>\s*$", response, re.DOTALL | re.IGNORECASE)
    if match is not None:
        answer = match.group(1)
    answer = answer.strip()
    if not answer:
        return ()
    return tuple(_normalize_atom(part) for part in answer.split(";") if part.strip())


def _parse_reason(response: str) -> str:
    match = re.search(r"<reason>\s*(.*?)\s*</reason>", response, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _remap_instance(instance: ItemGameInstance) -> dict[str, Any]:
    """Rename only the engine-facing player ids; scenario state is unchanged."""

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
    """Pure transition engine for symmetric P0/P1/P2 self-play."""

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
        self.player_success = {agent: False for agent in self.players}
        self.round_index = 0
        self.done = False
        self.terminal_reason: str | None = None
        self.pending_messages: list[dict[str, Any]] = []
        self.agreements: list[dict[str, Any]] = []
        self.join_accepted = False
        self.committed: dict[str, set[str]] = {}
        self.known: dict[str, dict[str, dict[str, set[str]]]] = {
            agent: {} for agent in self.players
        }
        self.inboxes: dict[str, list[dict[str, Any]]] = {
            agent: [] for agent in self.players
        }
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
        }

    @property
    def focal_player(self) -> str:
        return self.config.focal_player

    @property
    def active_players(self) -> tuple[str, ...]:
        return tuple(agent for agent in self.players if agent in self.active)

    def _goal_satisfied(self, agent: str, items: set[str] | None = None) -> bool:
        return self.goals[agent].issubset(self.holdings[agent] if items is None else items)

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
        }

    def build_round_snapshot(self) -> dict[str, Any]:
        return self._snapshot()

    def build_response_snapshot(self) -> dict[str, Any]:
        return self._snapshot()

    def _format_inbox(self, agent: str) -> list[str]:
        lines = []
        for message in self.inboxes[agent]:
            lines.append(f"- round {message['round']}: {message['text']}")
        return lines

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
        lines.append(
            "Known private information: "
            + (str({other: {field: _format_set(set(values)) for field, values in fields.items()}
                    for other, fields in known.items()}) if known else "none")
        )
        inbox = self._format_inbox(agent)
        lines.append("Direct messages:")
        lines.extend(inbox or ["- none"])
        lines.append("Public commit events:")
        if snap["public_events"]:
            lines.extend(f"- {dict(event)}" for event in snap["public_events"])
        else:
            lines.append("- none")
        lines.append("Decision bundle format: atom1 ; atom2 ; ... (at most one communication atom).")
        lines.append("Legal decision atoms:")
        lines.extend(f"- {action}" for action in self.get_legal_actions(agent, snap))
        return "\n".join(lines)

    def get_response_observation(
        self, request: Mapping[str, Any], snapshot: Mapping[str, Any] | None = None
    ) -> str:
        agent = str(request["recipient"])
        lines = [
            "You are in the response phase of a synchronous Item Coalition Game.",
            f"Your identity: {agent}",
            f"Your goal: {_format_set(self.goals[agent])}",
            f"Your holdings: {_format_set(self.holdings[agent])}",
            f"Round: {self.round_index}/{self.config.max_rounds}",
            "Respond to this direct message. This response does not use the proactive communication slot.",
            f"Incoming message: {request['text']}",
            "Legal response actions:",
        ]
        lines.extend(f"- {action}" for action in self.response_actions(request))
        return "\n".join(lines)

    def response_requests(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.pending_messages)

    def response_actions(self, request: Mapping[str, Any]) -> tuple[str, ...]:
        if request["kind"] == "QUERY":
            return (request["response"],)
        return ("ACT ACCEPT", "ACT REJECT")

    def _proposal_atoms(self, agent: str, snapshot: Mapping[str, Any]) -> list[str]:
        actions = []
        active = set(snapshot["active"])
        for other in self.players:
            if other == agent or other not in active:
                continue
            for item in self.items:
                item_set = _format_set({item})
                actions.append(
                    f"PROPOSE TRANSFER {{from={agent},to={other},items={item_set}}}"
                )
                actions.append(
                    f"PROPOSE TRANSFER {{from={other},to={agent},items={item_set}}}"
                )
        return actions

    def get_legal_actions(
        self, agent: str, snapshot: Mapping[str, Any] | None = None
    ) -> tuple[str, ...]:
        snap = snapshot or self._snapshot()
        if agent not in snap["active"]:
            return ()
        actions = ["PASS"]
        active = set(snap["active"])
        for other in self.players:
            if other == agent or other not in active:
                continue
            actions.extend((f"QUERY {other} GOAL", f"QUERY {other} HOLDINGS"))
            actions.extend((
                f"INFORM {other} GOAL {_format_set(set(snap['goals'][agent]))}",
                f"INFORM {other} HOLDINGS {_format_set(set(snap['holdings'][agent]))}",
            ))
        actions.extend(self._proposal_atoms(agent, snap))
        if self.subtype == "collaboration" and set(self.players) == {"P0", "P1"}:
            actions.append("PROPOSE JOIN {P0,P1}")

        for agreement in snap["agreements"]:
            if (
                agreement["type"] == "TRANSFER"
                and not agreement["fulfilled"]
                and agreement["from"] == agent
                and set(agreement["items"]).issubset(set(snap["holdings"][agent]))
            ):
                actions.append(
                    f"ACT GIVE {_format_set(set(agreement['items']))} TO {agreement['to']}"
                )

        can_commit = not any(
            agreement["type"] == "TRANSFER"
            and not agreement["fulfilled"]
            and agreement["from"] == agent
            for agreement in snap["agreements"]
        )
        if self.subtype == "collaboration" and not self.join_accepted:
            can_commit = False
        if can_commit:
            actions.extend(
                f"ACT COMMIT {_format_set(set(subset))}"
                for subset in self._subsets(set(snap["holdings"][agent]))
            )
        return tuple(dict.fromkeys(actions))

    def _parse_set(self, raw: str) -> frozenset[str]:
        if not raw.startswith("{") or not raw.endswith("}"):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        values = tuple(value.strip() for value in raw[1:-1].split(",") if value.strip())
        result = frozenset(values)
        if len(result) != len(values) or not result.issubset(set(self.items)):
            raise SynchronousActionError(f"invalid item set {raw!r}")
        return result

    def _parse_transfer(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(
            r"PROPOSE TRANSFER \{from=(\w+),to=(\w+),items=(\{[^}]*\})\}", action
        )
        if match is None:
            raise SynchronousActionError(f"invalid transfer proposal {action!r}")
        sender, receiver, raw_items = match.groups()
        return {
            "kind": "TRANSFER",
            "from": sender,
            "to": receiver,
            "items": self._parse_set(raw_items),
        }

    def _parse_give(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(r"ACT GIVE (\{[^}]*\}) TO (\w+)", action)
        if match is None:
            raise SynchronousActionError(f"invalid GIVE action {action!r}")
        return {"kind": "GIVE", "items": self._parse_set(match.group(1)), "to": match.group(2)}

    def _parse_commit(self, action: str) -> dict[str, Any]:
        match = re.fullmatch(r"ACT COMMIT (\{[^}]*\})", action)
        if match is None:
            raise SynchronousActionError(f"invalid COMMIT action {action!r}")
        return {"kind": "COMMIT", "items": self._parse_set(match.group(1))}

    def _parse_communication(self, agent: str, action: str, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
        if action == "PASS":
            return {"kind": "PASS"}
        match = re.fullmatch(r"QUERY (\w+) (GOAL|HOLDINGS)", action)
        if match:
            target, field = match.groups()
            if target not in snapshot["active"] or target == agent:
                raise SynchronousActionError(f"invalid QUERY target {target!r}")
            return {"kind": "QUERY", "sender": agent, "recipient": target, "field": field}
        match = re.fullmatch(r"INFORM (\w+) (GOAL|HOLDINGS) (\{[^}]*\})", action)
        if match:
            target, field, raw = match.groups()
            expected = snapshot["goals"][agent] if field == "GOAL" else snapshot["holdings"][agent]
            if target not in snapshot["active"] or target == agent or self._parse_set(raw) != expected:
                raise SynchronousActionError("INFORM must truthfully disclose current state")
            return {"kind": "INFORM", "sender": agent, "recipient": target, "field": field}
        if action.startswith("PROPOSE TRANSFER "):
            proposal = self._parse_transfer(action)
            if (
                proposal["from"] not in snapshot["active"]
                or proposal["to"] not in snapshot["active"]
                or proposal["from"] == proposal["to"]
                or agent not in {proposal["from"], proposal["to"]}
                or not proposal["items"]
            ):
                raise SynchronousActionError("transfer proposal has invalid participants")
            proposal["sender"] = agent
            proposal["recipient"] = proposal["to"] if agent == proposal["from"] else proposal["from"]
            return proposal
        if action == "PROPOSE JOIN {P0,P1}":
            if self.subtype != "collaboration" or set(snapshot["active"]) != {"P0", "P1"}:
                raise SynchronousActionError("JOIN is only available to active Collaboration players")
            return {"kind": "JOIN", "sender": agent, "recipient": "P1" if agent == "P0" else "P0"}
        return None

    def _parse_decision(
        self, agent: str, bundle: Sequence[str], snapshot: Mapping[str, Any]
    ) -> tuple[dict[str, Any], ...]:
        legal = set(self.get_legal_actions(agent, snapshot))
        if not bundle:
            raise SynchronousActionError("empty decision bundle")
        if any(atom not in legal for atom in bundle):
            raise SynchronousActionError("decision contains an action not legal in the round snapshot")
        communication = [
            atom for atom in bundle
            if atom != "PASS" and self._parse_communication(agent, atom, snapshot) is not None
        ]
        if len(communication) > 1:
            raise SynchronousActionError("at most one proactive communication is allowed per round")
        acts = [atom for atom in bundle if atom.startswith("ACT ")]
        if any(atom.startswith("ACT COMMIT ") for atom in acts) and len(acts) != 1:
            raise SynchronousActionError("ACT COMMIT is exclusive within a round")
        parsed = []
        for atom in bundle:
            communication_action = self._parse_communication(agent, atom, snapshot)
            if communication_action is not None:
                parsed.append(communication_action)
            elif atom.startswith("ACT GIVE "):
                parsed.append(self._parse_give(atom))
            elif atom.startswith("ACT COMMIT "):
                parsed.append(self._parse_commit(atom))
            else:
                raise SynchronousActionError(f"unsupported decision atom {atom!r}")
        return tuple(parsed)

    def resolve_responses(
        self, responses: Mapping[int, str], snapshot: Mapping[str, Any] | None = None
    ) -> None:
        if snapshot is None:
            snapshot = self.build_response_snapshot()
        if len(responses) != len(self.pending_messages):
            raise SynchronousActionError("every pending communication needs a response")
        old_messages = list(self.pending_messages)
        for index, message in enumerate(old_messages):
            response = _normalize_atom(responses[index])
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
                    "text": response,
                    "from": responder,
                })
                self.metrics["informs_sent"] += 1
                continue

            proposer = message["sender"]
            recipient = message["recipient"]
            accepted = response == "ACT ACCEPT"
            self.inboxes[proposer].append({
                "round": self.round_index,
                "text": f"{recipient}: {response}",
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
                    self.join_accepted = True
                    self.agreements.append({"type": "JOIN", "fulfilled": False})
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
        decisions: Mapping[str, Sequence[str]],
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        if snapshot is None:
            snapshot = self.build_round_snapshot()
        active = tuple(snapshot["active"])
        if set(decisions) != set(active):
            raise SynchronousActionError("every active player must submit one decision")
        parsed = {
            agent: self._parse_decision(agent, decisions[agent], snapshot)
            for agent in active
        }
        commits = {
            agent: next((action for action in actions if action["kind"] == "COMMIT"), None)
            for agent, actions in parsed.items()
        }
        # Commitments cannot strand an already accepted outgoing transfer.
        for agent, commit in commits.items():
            if commit is not None and any(
                agreement["type"] == "TRANSFER"
                and not agreement["fulfilled"]
                and agreement["from"] == agent
                for agreement in self.agreements
            ):
                raise SynchronousActionError("cannot COMMIT with an unfulfilled outgoing transfer")
            if commit is not None and not commit["items"].issubset(snapshot["holdings"][agent]):
                raise SynchronousActionError("COMMIT contains an item not held in the round snapshot")
            if commit is not None and self.subtype == "collaboration" and not self.join_accepted:
                raise SynchronousActionError("Collaboration COMMIT requires an accepted JOIN")

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
                    raise SynchronousActionError("ACT GIVE must match an accepted transfer agreement")
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
                if action["kind"] in {"QUERY", "INFORM", "TRANSFER", "JOIN"}:
                    if action.get("recipient") in committing:
                        raise SynchronousActionError("cannot send a message to a player committing this round")
                    if action["kind"] in {"TRANSFER", "JOIN"}:
                        message = dict(action)
                        message["round"] = self.round_index
                        message["text"] = self._message_text(action)
                        outgoing.append(message)
                        if (
                            self.subtype == "respond_to_give_request"
                            and action["kind"] == "TRANSFER"
                            and action["from"] == "P0"
                            and action["to"] != "P0"
                            and action["sender"] != "P0"
                        ):
                            self.metrics["request_proposed"] += 1
                    elif action["kind"] == "QUERY":
                        message = dict(action)
                        message["round"] = self.round_index
                        message["text"] = f"{agent} asks for {action['field']}"
                        message["response"] = (
                            f"INFORM {agent} {action['field']} "
                            f"{_format_set(self.goals[action['recipient']] if action['field'] == 'GOAL' else self.holdings[action['recipient']])}"
                        )
                        outgoing.append(message)
                    else:
                        target = action["recipient"]
                        field = action["field"]
                        values = self.goals[agent] if field == "GOAL" else self.holdings[agent]
                        self.known[target].setdefault(agent, {})[field] = set(values)
                        self.inboxes[target].append({
                            "round": self.round_index,
                            "text": f"{agent}: INFORM {target} {field} {_format_set(values)}",
                            "from": agent,
                        })

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
                "text": f"{agent}: ACT GIVE {_format_set(action['items'])} TO {action['to']}",
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
                case = self.instance.request_case
                self.metrics["safe_give_correct"] += int(case == "safe")

        for agent, commit in commits.items():
            if commit is None:
                continue
            self.committed[agent] = set(commit["items"])
            self.player_success[agent] = True
            self.active.remove(agent)
            self.metrics["commits"] += 1
            event = {"round": self.round_index, "agent": agent, "action": f"ACT COMMIT {_format_set(commit['items'])}"}
            self.public_events.append(event)

        if not self.active:
            for agreement in self.agreements:
                if agreement["type"] == "JOIN":
                    agreement["fulfilled"] = True

        self.pending_messages = outgoing
        for agent, actions in parsed.items():
            for action in actions:
                kind = action["kind"]
                if kind == "PASS":
                    self.metrics["passes"] += 1
                elif kind in {"QUERY", "INFORM", "TRANSFER", "JOIN"}:
                    self.metrics["communications_per_player"][agent] += 1
                    if kind == "QUERY":
                        self.metrics["queries_sent"] += 1
                    elif kind == "INFORM":
                        self.metrics["informs_sent"] += 1
                    else:
                        self.metrics["proposals_sent"] += 1

        self.round_index += 1
        if not self.active:
            self._finish("all_players_committed")
        elif self.round_index >= self.config.max_rounds:
            self._finish("max_rounds")

    def _message_text(self, action: Mapping[str, Any]) -> str:
        if action["kind"] == "JOIN":
            return f"{action['sender']}: PROPOSE JOIN {{P0,P1}}"
        return (
            f"{action['sender']}: PROPOSE TRANSFER "
            f"{{from={action['from']},to={action['to']},items={_format_set(action['items'])}}}"
        )

    def scenario_objective_success(self) -> bool:
        if not all(agreement["fulfilled"] for agreement in self.agreements):
            return False
        if self.subtype == "collaboration":
            if not self.join_accepted:
                return False
            if not all(agent in self.committed for agent in self.players):
                return False
            pool = set().union(*(self.committed[agent] for agent in self.players))
            return self.goals["P0"].issubset(pool)
        return "P0" in self.committed and self.goals["P0"].issubset(self.committed["P0"])

    def diagnostics(self) -> dict[str, Any]:
        request_proposed = any(
            message.get("kind") == "TRANSFER"
            and message.get("from") == "P0"
            and message.get("to") != "P0"
            for message in self.pending_messages
        ) or any(
            event.get("kind") == "TRANSFER"
            and event.get("from") == "P0"
            and event.get("to") != "P0"
            for event in self.inboxes.get("P0", [])
        )
        result = {
            "player_success": dict(self.player_success),
            "all_players_success": float(bool(self.players) and all(self.player_success.values())),
            "scenario_objective_success": float(self.scenario_objective_success()),
            "rounds_used": float(self.round_index),
            "agreements_fulfilled": float(all(a["fulfilled"] for a in self.agreements)),
            "join_accepted": float(self.join_accepted),
            "request_proposed": float(request_proposed or self.metrics["request_proposed"] > 0),
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
        self.done = True
        self.terminal_reason = reason


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
    ) -> tuple[str, tuple[str, ...], dict[str, Any]]:
        raw = str(self.policy.generate(
            agent=agent,
            observation=observation,
            legal_actions=legal,
            context=tuple(self.contexts[agent]),
        ))
        reason = _parse_reason(raw)
        bundle = _parse_bundle(raw)
        record = {
            "agent": agent,
            "phase": phase,
            "observation": observation,
            "legal_actions": list(legal),
            "reason": reason,
            "raw_response": raw,
            "answer": "; ".join(bundle),
            "valid": bool(bundle),
        }
        self.contexts[agent].extend((
            {"role": "user", "content": observation},
            {"role": "assistant", "content": raw},
        ))
        return raw, bundle, record

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
            for index, request in enumerate(requests):
                agent = str(request["recipient"])
                observation = game.get_response_observation(request, response_snapshot)
                legal = game.response_actions(request)
                _, bundle, record = self._call_policy(
                    agent=agent, observation=observation, legal=legal, phase="response"
                )
                if len(bundle) != 1 or bundle[0] not in legal:
                    record["valid"] = False
                    round_record["responses"].append(record)
                    game.finish_invalid("invalid_response")
                    break
                responses[index] = bundle[0]
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
            decisions: dict[str, tuple[str, ...]] = {}
            for agent in decision_snapshot["active"]:
                observation = game.get_observation(agent, decision_snapshot)
                legal = game.get_legal_actions(agent, decision_snapshot)
                _, bundle, record = self._call_policy(
                    agent=agent, observation=observation, legal=legal, phase="decision"
                )
                try:
                    game._parse_decision(agent, bundle, decision_snapshot)
                except SynchronousActionError as exc:
                    record["valid"] = False
                    record["error"] = str(exc)
                if not record["valid"]:
                    decisions[agent] = bundle
                else:
                    decisions[agent] = bundle
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
        terminal = {
            "done": game.done,
            "reason": game.terminal_reason,
            "active_players": list(game.active_players),
            "holdings": {agent: sorted(items) for agent, items in game.holdings.items()},
            "committed": {agent: sorted(items) for agent, items in game.committed.items()},
            "player_success": dict(game.player_success),
            "scenario_objective_success": game.scenario_objective_success(),
        }
        return SynchronousEpisodeResult(
            seed=seed,
            subtype=instance.subtype,
            ground_truth={
                "agents": list(game.players),
                "goals": {remap[agent]: sorted(goal) for agent, goal in instance.goals.items()},
                "initial_holdings": {
                    remap[agent]: sorted(items) for agent, items in instance.holdings.items()
                },
                "active_partner": remap.get(instance.active_partner, instance.active_partner),
                "request_case": instance.request_case,
                "partner_roles": {remap.get(agent, agent): role for agent, role in instance.partner_roles.items()},
                "partner_policies": {remap.get(agent, agent): policy for agent, policy in instance.partner_policies.items()},
            },
            rounds=rounds,
            terminal=terminal,
            diagnostics=game.diagnostics(),
        )


class HuggingFaceSynchronousSelfPlayPolicy:
    """One shared HF model used for every P0/P1/P2 decision."""

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

    def generate(self, *, agent: str, observation: str, legal_actions: Sequence[str], context: Sequence[Mapping[str, str]]) -> str:
        system = (
            f"You are {agent}. All players have equal status in a synchronous multi-agent game. "
            "Use only the listed legal action atoms. You may combine atoms with ';', using at most "
            "one proactive communication. Keep reasoning private. Return <reason>...</reason> "
            "and exactly one decision bundle inside <answer>...</answer>."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(dict(message) for message in context)
        messages.append({"role": "user", "content": observation + "\n\nLegal actions:\n" + "\n".join(legal_actions)})
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


if __name__ == "__main__":
    main()
