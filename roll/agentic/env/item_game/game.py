"""Shared transition engine for the structured Item Coalition Game.

Each Ego decision has explicit phases: an optional mandatory response, one
autonomous Ego action, a scripted partner response/action, and state update.
The five legacy subtypes use ASK/SAY/ACT: ASK can create an agreement, a
partner that agrees to GIVE immediately performs that scripted action in the
same transition, and Ego-side commitments still require a later Ego action.
Collaboration uses its separate QUERY/INFORM/PROPOSE/COMMIT protocol. Terminal
success requires the relevant goal and commitments to be satisfied.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from .config import ItemGameConfig
from .generator import ItemGameInstance


class BaseItemGame:
    """One Ego-centric episode with truthful, deterministic partners."""

    _COLLAB_REDUNDANT_PENALTY = 0.01
    _COLLAB_COMMUNICATION_BONUS = 0.01
    _COLLAB_INVALID_ACTION_PENALTY = -0.05

    def __init__(self, instance: ItemGameInstance, config: ItemGameConfig):
        self.instance = instance
        self.config = config
        self.goals = {player: set(goal) for player, goal in instance.goals.items()}
        self.holdings = {player: set(items) for player, items in instance.holdings.items()}
        self.known = {"EGO": {"goal": set(self.goals["EGO"]), "holdings": set(self.holdings["EGO"])} }
        self.known.update({player: {} for player in self.players if player != "EGO"})
        self.communication_used = 0
        self.ego_steps = 0
        self.turn_index = 0
        self.respond_to_give_request = instance.subtype == "respond_to_give_request"
        self.turn_phase = "mandatory_response" if instance.partner_event else "ego_action"
        self.records: list[dict[str, Any]] = []
        self.conversation_history: list[dict[str, Any]] = []
        self.agreements: list[dict[str, Any]] = []
        self.done = False
        self.committed: set[str] = set()

        # Partner consent is distinct from a later exact JOIN_COMMIT.
        self.join_approved: dict[frozenset[str], set[str]] = {}
        self.member_commit_actions: dict[str, str] = {}

        self.partner_event = (
            f"ASK EGO GIVE {instance.partner_event}" if instance.partner_event else None
        )
        self.pending_partner_request: str | None = self.partner_event
        self.pending_request_partner: str | None = "P1" if self.partner_event else None
        self.pending_exchange: tuple[str, str, str] | None = None
        self.pending_transfer: tuple[str, str] | None = None  # compatibility view
        self._mandatory_request_answered = False
        self._harmful_transfer_avoided = False

        self.give_request_proposal: dict[str, Any] | None = None
        self.give_request_accepted = False
        self.give_request_accepted_items: frozenset[str] = frozenset()
        self.give_request_rejected = False
        self.give_request_fulfilled = False
        self.give_request_ego_commit: set[str] | None = None
        if self.respond_to_give_request:
            partner = instance.active_partner
            if partner is None or instance.partner_event is None:
                raise ValueError("respond_to_give_request instance is missing its active proposal")
            self.pending_partner_request = None
            self.pending_request_partner = None
            self.turn_phase = "proposal_response"
            self.give_request_proposal = {
                "giver": "EGO",
                "receiver": partner,
                "items": frozenset({instance.partner_event}),
            }

        # Collaboration v2 has a separate decentralized protocol. The other
        # subtypes continue to use the legacy v0.3 state below.
        self.collaboration = instance.subtype == "collaboration"
        self.reroute = instance.subtype == "request_surplus_reroute"
        self.p1_known = (
            {
                "own_goal": set(self.goals["P1"]),
                "own_holdings": set(self.holdings["P1"]),
                "ego_goal": None,
                "ego_holdings": None,
            }
            if self.collaboration
            else None
        )
        self.pending_proposal: dict[str, Any] | None = None
        self.pending_partner_query: str | None = None
        self.collaboration_coalition: frozenset[str] | None = None
        self.collaboration_ego_commit: set[str] | None = None
        self.collaboration_p1_commit: set[str] | None = None
        self.collaboration_proposal_count = 0
        self.collaboration_accept_count = 0
        self.collaboration_reject_count = 0
        self.collaboration_redundant_commit_count = 0

        self.reroute_status: dict[str, str] = {}
        self.reroute_received_item: str | None = None
        self.reroute_received_turn_index: int | None = None
        self.reroute_ego_commit: set[str] | None = None
        self.reroute_proposal_count = 0
        self.reroute_accept_count = 0
        self.reroute_reject_count = 0
        self.reroute_first_partner: str | None = None
        self.reroute_after_rejection_count = 0

        if self.respond_to_give_request:
            partner = str(instance.active_partner)
            item = str(instance.partner_event)
            action = self._format_give_request_proposal(partner, item)
            self._record_partner(partner, action, f"{partner} proposes GIVE {item} to EGO.", "proposal")
        elif self.partner_event:
            self._record_partner("P1", self.partner_event, "P1 asks EGO to give the requested item.", "request")

    @property
    def players(self) -> tuple[str, ...]:
        return tuple(self.instance.goals)

    @property
    def items(self) -> tuple[str, ...]:
        return self.instance.items

    @property
    def communication_left(self) -> int:
        return max(0, self.config.communication_budget - self.communication_used)

    def legal_actions(self) -> tuple[str, ...]:
        if self.done:
            return ()
        if self.collaboration:
            return self._collaboration_legal_actions()
        if self.reroute:
            return self._reroute_legal_actions()
        if self.respond_to_give_request:
            return self._give_request_legal_actions()
        # A partner request creates a response-only Ego turn.
        if self.pending_partner_request:
            partner = self.pending_request_partner or "P1"
            item = self._requested_item(self.pending_partner_request)
            if item is None:
                return ()
            actions = [f"SAY {partner} CANNOT_GIVE {item}"]
            if item in self.holdings["EGO"]:
                actions.append(f"SAY {partner} CAN_GIVE {item}")
            return tuple(actions)

        actions: list[str] = []
        partners = [player for player in self.players if player != "EGO"]
        if self.communication_left:
            for partner in partners:
                actions.extend((f"ASK {partner} GOAL", f"ASK {partner} HOLDINGS"))
                actions.extend(f"ASK {partner} GIVE {item}" for item in self.items)
                for give in sorted(self._available_holdings("EGO")):
                    for receive in self.items:
                        actions.append(f"ASK {partner} EXCHANGE give={give} receive={receive}")
                for coalition in self._coalitions_containing(partner):
                    actions.append(f"ASK {partner} JOIN {self._format_coalition(coalition)}")
                actions.append(self._profile_action(partner))

        # Only Ego's own fulfillment actions are exposed. Partner scripted
        # actions are never presented as Ego legal actions.
        for agreement in self.agreements:
            if agreement["fulfilled"]:
                continue
            if agreement["type"] == "give" and agreement["direction"] == "ego_to_partner":
                actions.append(f"ACT GIVE {agreement['item']} TO {agreement['partner']}")
            elif agreement["type"] == "exchange":
                actions.append(f"ACT GIVE {agreement['give']} TO {agreement['partner']}")
        actions.append("ACT JOIN_COMMIT {EGO}")
        for coalition in self._coalitions():
            if len(coalition) > 1 and self._coalition_is_approved(coalition):
                actions.append(f"ACT JOIN_COMMIT {self._format_coalition(coalition)}")
        return tuple(dict.fromkeys(actions))

    def _give_request_legal_actions(self) -> tuple[str, ...]:
        if self.give_request_proposal is not None:
            return ("ACT ACCEPT", "ACT REJECT")
        if self.give_request_accepted and not self.give_request_fulfilled:
            item = next(iter(self.give_request_accepted_items))
            return (f"ACT GIVE {self._format_set({item})}",)
        if self.goals["EGO"].issubset(self.holdings["EGO"]):
            return tuple(
                f"ACT COMMIT {self._format_set(committed)}"
                for committed in self._item_subsets(self.holdings["EGO"])
            )
        return ()

    def _collaboration_legal_actions(self) -> tuple[str, ...]:
        if self.pending_partner_query:
            if self.pending_partner_query == "GOAL":
                return (f"INFORM P1 GOAL {self._format_set(self.goals['EGO'])}",)
            if self.pending_partner_query == "HOLDINGS":
                return (f"INFORM P1 HOLDINGS {self._format_set(self.holdings['EGO'])}",)
            return ()

        actions: list[str] = []
        if self.communication_left:
            actions.extend(("QUERY P1 GOAL", "QUERY P1 HOLDINGS"))
            actions.extend((
                f"INFORM P1 GOAL {self._format_set(self.goals['EGO'])}",
                f"INFORM P1 HOLDINGS {self._format_set(self.holdings['EGO'])}",
            ))
            if self.collaboration_coalition is None and self.pending_proposal is None:
                actions.append("PROPOSE JOIN {EGO,P1}")

        if self.collaboration_coalition is not None:
            for committed in self._item_subsets(self.holdings["EGO"]):
                actions.append(f"ACT COMMIT {self._format_set(committed)}")
        return tuple(dict.fromkeys(actions))

    def _reroute_legal_actions(self) -> tuple[str, ...]:
        actions: list[str] = []
        partners = [player for player in self.players if player != "EGO"]
        target = self._reroute_target_item()
        if self.communication_left:
            for partner in partners:
                actions.extend((f"QUERY {partner} GOAL", f"QUERY {partner} HOLDINGS"))
                actions.extend((
                    f"INFORM {partner} GOAL {self._format_set(self.goals['EGO'])}",
                    f"INFORM {partner} HOLDINGS {self._format_set(self.holdings['EGO'])}",
                ))
                if target is not None and self.reroute_status.get(partner) is None:
                    actions.append(self._format_give_proposal(partner, target))

        if self.goals["EGO"].issubset(self.holdings["EGO"]):
            for committed in self._item_subsets(self.holdings["EGO"]):
                actions.append(f"ACT COMMIT {self._format_set(committed)}")
        return tuple(dict.fromkeys(actions))

    @staticmethod
    def _item_subsets(items: set[str]) -> tuple[frozenset[str], ...]:
        ordered = tuple(sorted(items))
        subsets: list[frozenset[str]] = []
        for mask in range(1 << len(ordered)):
            subsets.append(frozenset(item for index, item in enumerate(ordered) if mask & (1 << index)))
        return tuple(subsets)

    def step(self, action: str):
        if self.done:
            raise RuntimeError("cannot act in a finished item game")
        action = " ".join(str(action).strip().split())
        action = self._normalize_set_spacing(action)
        if action not in self.legal_actions():
            raise ValueError(f"illegal item-game action {action!r}")

        before = self._snapshot()
        mandatory_response = self._is_mandatory_response(action)
        if (self.collaboration or self.reroute) and action.startswith(("QUERY ", "INFORM ", "PROPOSE ")):
            self.communication_used += 1
        elif action.startswith(("ASK ", "SAY ")) and not mandatory_response:
            self.communication_used += 1
        self.ego_steps += 1
        phase = "mandatory_response" if mandatory_response else "ego_action"
        self.conversation_history.append({
            "turn": self.turn_index, "actor": "EGO", "phase": phase, "action": action, "message": ""
        })

        # _apply_ego creates an operation. Holdings and commitments are
        # updated in _run_partner_phase after the scripted partner acts.
        ego_message, operation = self._apply_ego(action)
        partner_messages = self._run_partner_phase(operation)

        if (self.collaboration or self.reroute or self.respond_to_give_request) and action.startswith("ACT COMMIT "):
            self.done = True
        elif action.startswith("ACT JOIN_COMMIT"):
            self.done = True
        elif self.ego_steps >= self.config.max_ego_steps:
            self.done = True
        self.turn_phase = "terminal" if self.done else (
            "mandatory_response" if self.pending_partner_query else "ego_action"
        )
        self.turn_index += 1
        partner_message = "\n".join(m for m in [ego_message, *partner_messages] if m)
        reward = self._terminal_reward() if self.done else 0.0
        record = {
            "action": action,
            "action_is_ask": float(action.startswith("ASK ")),
            "action_is_say": float(action.startswith("SAY ")),
            "action_is_act": float(action.startswith("ACT ")),
            "action_is_query": float(action.startswith("QUERY ")),
            "action_is_inform": float(action.startswith("INFORM ")),
            "action_is_propose": float(action.startswith("PROPOSE ")),
            "communication_used": self.communication_used,
            "ego_step": self.ego_steps,
            "turn_index": self.turn_index - 1,
            "turn_phase": phase,
            "before": before,
            "partner_message": partner_message,
            "step_reward": reward,
            "game_transition": 1.0,
        }
        self.records.append(record)
        info = dict(record)
        info.update(self.diagnostics())
        info.update({"game_transition": 1.0, "canonical_reward_player_0": reward, "canonical_reward_player_1": 0.0})
        if self.done:
            info.update({
                "success": True,
                "ego_success": float(self.ego_success),
                "player_0_return": reward,
                "player_1_return": 0.0,
                "player_0_success": bool(self.ego_success),
                "player_1_success": False,
                "winner": 0 if self.ego_success else -1,
            })
        return partner_message, reward, self.done, info

    def _terminal_reward(self) -> float:
        if not self.collaboration and not self.reroute and not self.respond_to_give_request:
            return float(self.ego_success)
        if not self.ego_success:
            return 0.0
        if self.collaboration:
            redundant = self.collaboration_redundant_commit_count
        elif self.reroute:
            redundant = max(0, len(self.reroute_ego_commit or set()) - len(self.goals["EGO"]))
        else:
            redundant = max(0, len(self.give_request_ego_commit or set()) - len(self.goals["EGO"]))
        bonus = self.communication_left * self._COLLAB_COMMUNICATION_BONUS
        penalty = redundant * self._COLLAB_REDUNDANT_PENALTY
        return 1.0 + bonus - penalty

    def _apply_ego(self, action: str) -> tuple[str, dict[str, Any] | None]:
        if self.collaboration:
            return self._apply_collaboration_ego(action)
        if self.reroute:
            return self._apply_reroute_ego(action)
        if self.respond_to_give_request:
            return self._apply_give_request_ego(action)
        if action.startswith("ASK "):
            return self._ask(action)
        if action.startswith("SAY "):
            return self._say(action), None
        if action.startswith("ACT GIVE "):
            match = re.fullmatch(r"ACT GIVE (\S+) TO (P\d+)", action)
            if match is None:
                raise ValueError(f"invalid GIVE action {action!r}")
            item, partner = match.groups()
            for agreement in self.agreements:
                if agreement["fulfilled"] or agreement["partner"] != partner:
                    continue
                if agreement["type"] == "give" and agreement["direction"] == "ego_to_partner" and agreement["item"] == item:
                    return "", {"type": "ego_give", "agreement": agreement}
                if agreement["type"] == "exchange" and agreement["give"] == item:
                    return "", {"type": "exchange", "agreement": agreement}
            raise ValueError("ACT GIVE does not fulfill an accepted Ego commitment")
        if action == "ACT JOIN_COMMIT {EGO}":
            return "", {"type": "join", "coalition": frozenset({"EGO"}), "action": action}
        match = re.fullmatch(r"ACT JOIN_COMMIT (\{[^}]*\})", action)
        if match:
            coalition = self._parse_coalition(match.group(1))
            if not self._coalition_is_approved(coalition):
                raise ValueError("all coalition partners must consent before commit")
            return "", {"type": "join", "coalition": coalition, "action": action}
        raise ValueError(f"unsupported item-game action {action!r}")

    def _apply_collaboration_ego(self, action: str) -> tuple[str, dict[str, Any] | None]:
        if action.startswith("QUERY "):
            match = re.fullmatch(r"QUERY P1 (GOAL|HOLDINGS)", action)
            if match is None:
                raise ValueError(f"invalid collaboration QUERY {action!r}")
            return "", {"type": "collab_query_p1", "field": match.group(1)}

        match = re.fullmatch(r"INFORM P1 (GOAL|HOLDINGS) (\{[^}]*\})", action)
        if match is not None:
            field, raw_items = match.groups()
            items = self._parse_item_set(raw_items)
            expected = self.goals["EGO"] if field == "GOAL" else self.holdings["EGO"]
            if items != expected:
                raise ValueError("EGO must truthfully INFORM its own state")
            return "", {"type": "collab_inform", "field": field, "items": items}

        match = re.fullmatch(r"PROPOSE JOIN (\{[^}]*\})", action)
        if match is not None:
            if self.collaboration_coalition is not None or self.pending_proposal is not None:
                raise ValueError("a collaboration JOIN proposal is already resolved or pending")
            coalition = frozenset(("EGO", "P1"))
            self.pending_proposal = {"type": "JOIN", "coalition": coalition}
            self.collaboration_proposal_count += 1
            return "", {"type": "collab_process_proposal"}

        match = re.fullmatch(r"ACT COMMIT (\{[^}]*\})", action)
        if match is not None:
            if self.collaboration_coalition is None:
                raise ValueError("ACT COMMIT requires an accepted JOIN coalition")
            committed = self._parse_item_set(match.group(1))
            if not committed.issubset(self.holdings["EGO"]):
                raise ValueError("EGO can only commit items it holds")
            return "", {"type": "collab_commit", "items": committed}

        raise ValueError(f"unsupported collaboration action {action!r}")

    def _apply_reroute_ego(self, action: str) -> tuple[str, dict[str, Any] | None]:
        match = re.fullmatch(r"QUERY (P[12]) (GOAL|HOLDINGS)", action)
        if match is not None:
            partner, field = match.groups()
            return "", {"type": "reroute_query_partner", "partner": partner, "field": field}

        match = re.fullmatch(r"INFORM (P[12]) (GOAL|HOLDINGS) (\{[^}]*\})", action)
        if match is not None:
            partner, field, raw_items = match.groups()
            items = self._parse_item_set(raw_items)
            expected = self.goals["EGO"] if field == "GOAL" else self.holdings["EGO"]
            if items != expected:
                raise ValueError("EGO must truthfully INFORM its own state")
            return "", {"type": "reroute_inform_partner", "partner": partner, "field": field}

        match = re.fullmatch(
            r"PROPOSE GIVE \{giver=(P[12]),receiver=EGO,items=(\{[^}]*\})\}", action
        )
        if match is not None:
            partner, raw_items = match.groups()
            items = self._parse_item_set(raw_items)
            target = self._reroute_target_item()
            if len(items) != 1 or target is None or items != {target}:
                raise ValueError("reroute GIVE proposal must request the single missing Ego goal item")
            if self.reroute_status.get(partner) is not None:
                raise ValueError("this partner's GIVE proposal has already been resolved")
            if self.reroute_first_partner is None:
                self.reroute_first_partner = partner
            elif any(status == "rejected" for status in self.reroute_status.values()):
                self.reroute_after_rejection_count += 1
            self.reroute_status[partner] = "pending"
            self.reroute_proposal_count += 1
            return "", {"type": "reroute_process_give", "partner": partner, "item": target}

        match = re.fullmatch(r"ACT COMMIT (\{[^}]*\})", action)
        if match is not None:
            if not self.goals["EGO"].issubset(self.holdings["EGO"]):
                raise ValueError("ACT COMMIT requires Ego to have received the missing goal item")
            committed = self._parse_item_set(match.group(1))
            if not committed.issubset(self.holdings["EGO"]):
                raise ValueError("EGO can only commit items it holds")
            return "", {"type": "reroute_commit", "items": set(committed)}

        raise ValueError(f"unsupported reroute action {action!r}")

    def _apply_give_request_ego(self, action: str) -> tuple[str, dict[str, Any] | None]:
        if self.give_request_proposal is not None:
            if action == "ACT ACCEPT":
                return "", {"type": "give_request_accept"}
            if action == "ACT REJECT":
                return "", {"type": "give_request_reject"}
            raise ValueError("Ego must accept or reject the pending GIVE proposal")

        if self.give_request_accepted and not self.give_request_fulfilled:
            match = re.fullmatch(r"ACT GIVE (\{[^}]*\})", action)
            if match is None:
                raise ValueError("accepted GIVE proposal requires an exact ACT GIVE item set")
            items = self._parse_item_set(match.group(1))
            if items != self.give_request_accepted_items:
                raise ValueError("ACT GIVE items must exactly match the accepted proposal")
            return "", {"type": "give_request_transfer", "items": items}

        match = re.fullmatch(r"ACT COMMIT (\{[^}]*\})", action)
        if match is not None:
            committed = self._parse_item_set(match.group(1))
            if not committed.issubset(self.holdings["EGO"]):
                raise ValueError("EGO can only commit items it holds")
            return "", {"type": "give_request_commit", "items": set(committed)}

        raise ValueError(f"unsupported give-request action {action!r}")

    def _run_partner_phase(self, operation: dict[str, Any] | None) -> list[str]:
        messages: list[str] = []
        if operation is None:
            return messages

        if self.collaboration:
            return self._run_collaboration_partner_phase(operation)
        if self.reroute:
            return self._run_reroute_partner_phase(operation)
        if self.respond_to_give_request:
            return self._run_give_request_partner_phase(operation)

        if operation["type"] == "partner_give":
            agreement = operation["agreement"]
            partner, item = agreement["partner"], agreement["item"]
            if item not in self.holdings[partner]:
                raise RuntimeError(f"partner {partner} violated accepted GIVE commitment for {item!r}")
            self.holdings[partner].remove(item)
            self.holdings["EGO"].add(item)
            self._mark_fulfilled("give", partner=partner, item=item, direction="partner_to_ego")
            self._record_partner(partner, f"ACT GIVE {item} TO EGO", f"{partner} fulfills GIVE {item} to EGO.", "scripted_action")
            messages.append(f"{partner} ACT GIVE {item} TO EGO.")
            return messages

        if operation["type"] == "ego_give":
            agreement = operation["agreement"]
            item, partner = agreement["item"], agreement["partner"]
            if item not in self.holdings["EGO"]:
                raise ValueError(f"EGO no longer holds committed item {item!r}")
            self.holdings["EGO"].remove(item)
            self.holdings[partner].add(item)
            self._mark_fulfilled("give", partner=partner, item=item, direction="ego_to_partner")
            self.pending_transfer = None
            self._clear_partner_request()
            self._record_partner(partner, f"SAY {partner} AGREE_GIVE {item}", f"{partner} accepts GIVE {item}.", "response")
            messages.append(f"{partner} accepts GIVE {item}.")
        elif operation["type"] == "exchange":
            agreement = operation["agreement"]
            partner, give, receive = agreement["partner"], agreement["give"], agreement["receive"]
            if not self._exchange_still_feasible(agreement):
                raise ValueError("accepted exchange is no longer feasible")
            self.holdings["EGO"].remove(give)
            self.holdings[partner].remove(receive)
            self.holdings[partner].add(give)
            self.holdings["EGO"].add(receive)
            self._mark_fulfilled("exchange", partner=partner, give=give, receive=receive)
            self.pending_exchange = None
            partner_action = f"ACT GIVE {receive} TO EGO"
            self._record_partner(partner, partner_action, f"{partner} fulfills exchange leg GIVE {receive} to EGO.", "scripted_action")
            messages.append(f"EGO ACT GIVE {give} TO {partner}.\n{partner} {partner_action}.")
        elif operation["type"] == "join":
            coalition, action = operation["coalition"], operation["action"]
            self.committed = set(coalition)
            for agreement in self.agreements:
                if agreement["type"] == "join" and agreement["coalition"] == coalition:
                    agreement["fulfilled"] = True
            self.member_commit_actions = {member: action for member in self._ordered_members(coalition)}
            for member in self._ordered_members(coalition):
                if member != "EGO":
                    self._record_partner(member, action, f"{member} emits the exact same JOIN_COMMIT.", "scripted_action")
                    messages.append(f"{member} {action}.")
        return messages

    def _run_collaboration_partner_phase(self, operation: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        if operation["type"] == "collab_query_p1":
            field = operation["field"]
            values = self.goals["P1"] if field == "GOAL" else self.holdings["P1"]
            action = f"INFORM EGO {field} {self._format_set(values)}"
            self._record_partner("P1", action, f"P1 informs EGO {field}.", "response")
            messages.append(action)
            self.known["P1"][field.lower()] = set(values)
            return messages

        if operation["type"] == "collab_inform":
            field = operation["field"]
            self.p1_known[f"ego_{field.lower()}"] = set(operation["items"])
            self._clear_collaboration_partner_query()
            messages.append(f"P1 receives EGO {field}.")
            if self.pending_proposal is not None:
                messages.extend(self._process_collaboration_proposal())
            return messages

        if operation["type"] == "collab_process_proposal":
            messages.extend(self._process_collaboration_proposal())
            return messages

        if operation["type"] == "collab_commit":
            ego_items = set(operation["items"])
            p1_items = self._collaboration_partner_commit(ego_items)
            self.collaboration_ego_commit = ego_items
            self.collaboration_p1_commit = p1_items
            self.member_commit_actions = {
                "EGO": f"ACT COMMIT {self._format_set(ego_items)}",
                "P1": f"ACT COMMIT {self._format_set(p1_items)}",
            }
            self.collaboration_redundant_commit_count = max(
                0,
                len(ego_items) + len(p1_items) - len(self.goals["EGO"]),
            )
            action = f"ACT COMMIT {self._format_set(p1_items)}"
            self._record_partner("P1", action, "P1 commits its own items.", "scripted_action")
            messages.append(f"P1 {action}.")
            return messages

        raise ValueError(f"unsupported collaboration partner operation {operation['type']!r}")

    def _run_give_request_partner_phase(self, operation: dict[str, Any]) -> list[str]:
        partner = str(self.instance.active_partner)
        item = str(self.instance.partner_event)
        if operation["type"] == "give_request_accept":
            if self.give_request_proposal is None:
                raise RuntimeError("cannot accept a resolved GIVE proposal")
            self.give_request_accepted = True
            self.give_request_accepted_items = frozenset(self.give_request_proposal["items"])
            self.give_request_proposal = None
            self._record_partner(partner, "ACT ACCEPT", f"EGO accepts GIVE {item}.", "binding_action")
            return ["EGO ACT ACCEPT."]

        if operation["type"] == "give_request_reject":
            if self.give_request_proposal is None:
                raise RuntimeError("cannot reject a resolved GIVE proposal")
            self.give_request_rejected = True
            self.give_request_proposal = None
            self._record_partner(partner, "ACT REJECT", f"EGO rejects GIVE {item}.", "binding_action")
            return ["EGO ACT REJECT."]

        if operation["type"] == "give_request_transfer":
            if not self.give_request_accepted or self.give_request_fulfilled:
                raise RuntimeError("GIVE transfer requires an accepted unresolved proposal")
            if item not in self.give_request_accepted_items:
                raise RuntimeError("GIVE transfer item differs from accepted proposal")
            if item not in self.holdings["EGO"]:
                raise ValueError(f"EGO no longer holds committed item {item!r}")
            self.holdings["EGO"].remove(item)
            self.holdings[partner].add(item)
            self.give_request_fulfilled = True
            self._record_partner(partner, f"ACT GIVE {self._format_set({item})}", f"EGO gives {item} to {partner}.", "binding_action")
            return [f"EGO ACT GIVE {self._format_set({item})} TO {partner}."]

        if operation["type"] == "give_request_commit":
            self.give_request_ego_commit = set(operation["items"])
            return []

        raise ValueError(f"unsupported give-request operation {operation['type']!r}")

    def _run_reroute_partner_phase(self, operation: dict[str, Any]) -> list[str]:
        if operation["type"] == "reroute_query_partner":
            partner, field = operation["partner"], operation["field"]
            values = self.goals[partner] if field == "GOAL" else self.holdings[partner]
            action = f"INFORM EGO {field} {self._format_set(values)}"
            self.known[partner][field.lower()] = set(values)
            self._record_partner(partner, action, f"{partner} informs EGO {field}.", "response")
            return [action]

        if operation["type"] == "reroute_inform_partner":
            partner, field = operation["partner"], operation["field"]
            self._record_partner(
                partner,
                f"INFORM {partner} {field}",
                f"EGO informs {partner} {field}.",
                "message",
            )
            return [f"{partner} receives EGO {field}."]

        if operation["type"] == "reroute_process_give":
            partner, item = operation["partner"], operation["item"]
            can_give = item in self.holdings[partner] and self.goals[partner].issubset(
                set(self.holdings[partner]) - {item}
            )
            policy = self.instance.partner_policies.get(partner, "HELPFUL")
            accepts = can_give and policy == "HELPFUL"
            if not accepts:
                self.reroute_status[partner] = "rejected"
                self.reroute_reject_count += 1
                action = f"ACT REJECT GIVE {item}"
                self._record_partner(partner, action, f"{partner} rejects the GIVE proposal.", "scripted_action")
                return [f"{partner} {action}."]

            self.reroute_status[partner] = "accepted"
            self.reroute_accept_count += 1
            accept_action = "ACT ACCEPT"
            give_action = f"ACT GIVE {item} TO EGO"
            self._record_partner(partner, accept_action, f"{partner} accepts the GIVE proposal.", "scripted_action")
            if item not in self.holdings[partner]:
                raise RuntimeError(f"partner {partner} violated accepted GIVE commitment for {item!r}")
            self.holdings[partner].remove(item)
            self.holdings["EGO"].add(item)
            self.reroute_received_item = item
            self.reroute_received_turn_index = self.turn_index
            self._record_partner(partner, give_action, f"{partner} fulfills GIVE {item} to EGO.", "scripted_action")
            return [f"{partner} {accept_action}.", f"{partner} {give_action}."]

        if operation["type"] == "reroute_commit":
            self.reroute_ego_commit = set(operation["items"])
            return []

        raise ValueError(f"unsupported reroute partner operation {operation['type']!r}")

    def _process_collaboration_proposal(self) -> list[str]:
        if self.pending_proposal is None:
            return []
        if self.p1_known["ego_goal"] is None:
            self.pending_partner_query = "GOAL"
            self.turn_phase = "mandatory_response"
            action = "QUERY EGO GOAL"
            self._record_partner("P1", action, "P1 needs EGO's goal before deciding on JOIN.", "request")
            return [action]
        if self.p1_known["ego_holdings"] is None:
            self.pending_partner_query = "HOLDINGS"
            self.turn_phase = "mandatory_response"
            action = "QUERY EGO HOLDINGS"
            self._record_partner("P1", action, "P1 needs EGO's holdings before deciding on JOIN.", "request")
            return [action]

        coalition = self.pending_proposal["coalition"]
        aligned = self.p1_known["ego_goal"] == self.p1_known["own_goal"]
        pooled = set(self.p1_known["ego_holdings"]) | set(self.p1_known["own_holdings"])
        feasible = set(self.p1_known["own_goal"]).issubset(pooled)
        if aligned and feasible and coalition == frozenset(("EGO", "P1")):
            self.collaboration_coalition = coalition
            self.committed = set(coalition)
            self.collaboration_accept_count += 1
            action = "ACT ACCEPT"
            self._record_partner("P1", action, "P1 accepts the JOIN proposal.", "scripted_action")
            self.pending_proposal = None
            self.pending_partner_query = None
            self.turn_phase = "ego_action"
            return [f"P1 {action}.", "Coalition {EGO,P1} is formed."]

        self.collaboration_reject_count += 1
        action = "ACT REJECT"
        self._record_partner("P1", action, "P1 rejects the JOIN proposal.", "scripted_action")
        self.pending_proposal = None
        self.pending_partner_query = None
        self.turn_phase = "ego_action"
        return [f"P1 {action}."]

    def _collaboration_partner_commit(self, ego_items: set[str]) -> set[str]:
        needed = set(self.p1_known["own_goal"]) - ego_items
        return needed & set(self.p1_known["own_holdings"])

    def _clear_collaboration_partner_query(self) -> None:
        self.pending_partner_query = None

    def _ask(self, action: str) -> tuple[str, dict[str, Any] | None]:
        parts = action.split()
        partner = parts[1]
        if parts[2] == "GOAL":
            self.known[partner]["goal"] = set(self.goals[partner])
            return self._reply(partner, f"SAY {partner} GOAL", f"{partner} answers GOAL {self._format_set(self.goals[partner])}."), None
        if parts[2] == "HOLDINGS":
            self.known[partner]["holdings"] = set(self.holdings[partner])
            return self._reply(partner, f"SAY {partner} HOLDINGS", f"{partner} answers HOLDINGS {self._format_set(self.holdings[partner])}."), None
        if parts[2] == "JOIN":
            coalition = self._parse_coalition(parts[3])
            if self._partner_accepts_join(partner, coalition):
                self.join_approved.setdefault(coalition, set()).add(partner)
                self._new_agreement("join", partner=partner, coalition=coalition)
                return self._reply(partner, f"SAY {partner} AGREE_JOIN {parts[3]}", f"{partner} says AGREE_JOIN {parts[3]}."), None
            return self._reply(partner, f"SAY {partner} CANNOT_JOIN {parts[3]}", f"{partner} says CANNOT_JOIN {parts[3]}.") , None
        if parts[2] == "GIVE":
            item = parts[3]
            if not self._partner_accepts_give(partner, item):
                return self._reply(partner, f"SAY {partner} CANNOT_GIVE {item}", f"{partner} says CANNOT_GIVE {item}."), None
            agreement = self._new_agreement("give", partner=partner, item=item, direction="partner_to_ego")
            return self._reply(partner, f"SAY {partner} AGREE_GIVE {item}", f"{partner} says AGREE_GIVE {item}. Agreement formed; partner ACT GIVE follows immediately."), {"type": "partner_give", "agreement": agreement}
        if parts[2] == "EXCHANGE":
            match = re.fullmatch(r"ASK (P\d+) EXCHANGE give=(\S+) receive=(\S+)", action)
            if match is None:
                raise ValueError(f"invalid EXCHANGE request {action!r}")
            _, give, receive = match.groups()
            if not self._partner_accepts_exchange(partner, give, receive):
                return self._reply(partner, f"SAY {partner} CANNOT_EXCHANGE", f"{partner} says CANNOT_EXCHANGE."), None
            self._new_agreement("exchange", partner=partner, give=give, receive=receive)
            self.pending_exchange = (partner, give, receive)
            return self._reply(partner, f"SAY {partner} AGREE_EXCHANGE give={give} receive={receive}", f"{partner} says AGREE_EXCHANGE give={give} receive={receive}. Agreement formed; Ego must ACT GIVE {give} TO {partner}."), None
        raise ValueError(f"unsupported ASK action {action!r}")

    def _say(self, action: str) -> str:
        profile = re.fullmatch(r"SAY (P\d+) PROFILE goal=(\{[^}]*\}) holdings=(\{[^}]*\})", action)
        if profile is not None:
            partner = profile.group(1)
            self.known[partner] = {"goal": set(self.goals["EGO"]), "holdings": set(self.holdings["EGO"])}
            return self._reply(partner, action, f"{partner} receives EGO's PROFILE.")
        match = re.fullmatch(r"SAY (P\d+) (CAN_GIVE|CANNOT_GIVE) (\S+)", action)
        if match is None or not self.pending_partner_request:
            raise ValueError("mandatory GIVE response requires a pending partner request")
        partner, response, item = match.groups()
        requested_partner = self.pending_request_partner or "P1"
        requested_item = self._requested_item(self.pending_partner_request)
        if partner != requested_partner or item != requested_item:
            raise ValueError("mandatory response does not match the partner request")
        self._mandatory_request_answered = True
        if response == "CAN_GIVE":
            if item not in self.holdings["EGO"]:
                raise ValueError(f"EGO does not hold {item!r}")
            self._new_agreement("give", partner=partner, item=item, direction="ego_to_partner")
            self.pending_transfer = (partner, item)
            # The mandatory response phase is over; the accepted
            # Ego-to-partner commitment remains pending until ACT GIVE.
            self.pending_partner_request = None
            self.pending_request_partner = None
            self.partner_event = None
            return self._reply(partner, f"SAY {partner} AGREE_GIVE {item}", f"{partner} agrees to the GIVE commitment for {item}.")
        if item in self.goals["EGO"]:
            self._harmful_transfer_avoided = True
        self._clear_partner_request()
        return self._reply(partner, action, f"{partner} records CANNOT_GIVE {item}.")

    def _partner_accepts_give(self, partner: str, item: str) -> bool:
        available = self._available_holdings(partner)
        return item in available and self.goals[partner].issubset(available - {item})

    def _partner_accepts_exchange(self, partner: str, give: str, receive: str) -> bool:
        if give not in self._available_holdings("EGO"):
            return False
        partner_available = self._available_holdings(partner)
        if receive not in partner_available:
            return False
        before = len(self.goals[partner] & partner_available)
        after = (partner_available - {receive}) | {give}
        return self.goals[partner].issubset(after) or len(self.goals[partner] & after) > before

    def _exchange_still_feasible(self, agreement: dict[str, Any]) -> bool:
        partner = agreement["partner"]
        ego_available = self._available_holdings("EGO", exclude=agreement)
        partner_available = self._available_holdings(partner, exclude=agreement)
        if agreement["give"] not in ego_available or agreement["receive"] not in partner_available:
            return False
        before = len(self.goals[partner] & partner_available)
        after = (partner_available - {agreement["receive"]}) | {agreement["give"]}
        return self.goals[partner].issubset(after) or len(self.goals[partner] & after) > before

    def _partner_accepts_join(self, partner: str, coalition: frozenset[str]) -> bool:
        return (
            partner in coalition
            and "EGO" in coalition
            and all(self.goals[member] == self.goals["EGO"] for member in coalition)
            and self.goals["EGO"].issubset(set().union(*(self._available_holdings(member) for member in coalition)))
        )

    def _available_holdings(self, player: str, exclude: dict[str, Any] | None = None) -> set[str]:
        available = set(self.holdings[player])
        for agreement in self.agreements:
            if agreement is exclude:
                continue
            if agreement["fulfilled"] or agreement.get("partner") != player:
                continue
            if agreement["type"] == "give" and agreement["direction"] == "partner_to_ego":
                available.discard(agreement["item"])
            elif agreement["type"] == "exchange":
                available.discard(agreement["receive"])
        return available

    def _profile_action(self, partner: str) -> str:
        return (
            f"SAY {partner} PROFILE goal={self._format_set(self.goals['EGO'])} "
            f"holdings={self._format_set(self.holdings['EGO'])}"
        )

    def _new_agreement(self, agreement_type: str, **fields: Any) -> dict[str, Any]:
        agreement = {"type": agreement_type, "fulfilled": False, **fields}
        self.agreements.append(agreement)
        return agreement

    def _mark_fulfilled(self, agreement_type: str, **fields: Any) -> None:
        for agreement in reversed(self.agreements):
            if agreement["type"] != agreement_type or agreement["fulfilled"]:
                continue
            if all(agreement.get(key) == value for key, value in fields.items()):
                agreement["fulfilled"] = True
                return

    def _clear_partner_request(self) -> None:
        self.pending_partner_request = None
        self.pending_request_partner = None
        self.partner_event = None
        self.pending_transfer = None

    def _reply(self, partner: str, action: str, message: str) -> str:
        self._record_partner(partner, action, message, "response")
        return message

    def _record_partner(self, partner: str, action: str, message: str, phase: str = "response") -> None:
        self.conversation_history.append({"turn": self.turn_index, "actor": partner, "phase": phase, "action": action, "message": message})

    def _is_mandatory_response(self, action: str) -> bool:
        if self.collaboration:
            return bool(
                self.pending_partner_query
                and re.fullmatch(r"INFORM P1 (?:GOAL|HOLDINGS) \{[^}]*\}", action)
            )
        if self.respond_to_give_request:
            return self.give_request_proposal is not None and action in {"ACT ACCEPT", "ACT REJECT"}
        return bool(self.pending_partner_request and re.fullmatch(r"SAY P\d+ (?:CAN_GIVE|CANNOT_GIVE) \S+", action))

    def _coalitions(self) -> tuple[frozenset[str], ...]:
        partners = tuple(player for player in self.players if player != "EGO")
        return tuple(frozenset(("EGO", *members)) for size in range(len(partners) + 1) for members in combinations(partners, size))

    def _coalitions_containing(self, partner: str) -> tuple[frozenset[str], ...]:
        return tuple(coalition for coalition in self._coalitions() if partner in coalition)

    def _coalition_is_approved(self, coalition: frozenset[str]) -> bool:
        return self.join_approved.get(coalition, set()) == set(coalition) - {"EGO"} and all(self.goals[member] == self.goals["EGO"] for member in coalition)

    @staticmethod
    def _ordered_members(coalition: frozenset[str]) -> tuple[str, ...]:
        return ("EGO", *sorted(member for member in coalition if member != "EGO"))

    @classmethod
    def _format_coalition(cls, coalition: frozenset[str]) -> str:
        return "{" + ",".join(cls._ordered_members(coalition)) + "}"

    def _parse_coalition(self, raw: str) -> frozenset[str]:
        if not (raw.startswith("{") and raw.endswith("}")):
            raise ValueError(f"invalid coalition {raw!r}")
        members = tuple(member.strip() for member in raw[1:-1].split(",") if member.strip())
        coalition = frozenset(members)
        if not members or len(coalition) != len(members) or "EGO" not in coalition or not coalition.issubset(set(self.players)):
            raise ValueError(f"invalid coalition {raw!r}")
        return coalition

    def _parse_item_set(self, raw: str) -> frozenset[str]:
        if not (raw.startswith("{") and raw.endswith("}")):
            raise ValueError(f"invalid item set {raw!r}")
        values = tuple(item.strip() for item in raw[1:-1].split(",") if item.strip())
        items = frozenset(values)
        if (
            len(items) != len(values)
            or not items.issubset(set(self.items))
        ):
            raise ValueError(f"invalid item set {raw!r}")
        return items

    @staticmethod
    def _requested_item(request: str) -> str | None:
        match = re.search(r"GIVE (\S+)$", request)
        return match.group(1) if match else None

    @staticmethod
    def _format_set(items: set[str] | frozenset[str]) -> str:
        return "{" + ",".join(sorted(items)) + "}"

    @staticmethod
    def _normalize_set_spacing(action: str) -> str:
        """Treat whitespace around comma-separated set members as formatting."""

        def normalize(match: re.Match[str]) -> str:
            values = [value.strip() for value in match.group(1).split(",") if value.strip()]
            return "{" + ",".join(values) + "}"

        return re.sub(r"\{([^{}]*)\}", normalize, action)

    def _reroute_target_item(self) -> str | None:
        missing = sorted(set(self.goals["EGO"]) - set(self.holdings["EGO"]))
        return missing[0] if len(missing) == 1 else None

    @classmethod
    def _format_give_proposal(cls, partner: str, item: str) -> str:
        return f"PROPOSE GIVE {{giver={partner},receiver=EGO,items={cls._format_set({item})}}}"

    def _snapshot(self) -> dict[str, tuple[str, ...]]:
        return {player: tuple(sorted(items)) for player, items in self.holdings.items()}

    @property
    def ego_success(self) -> bool:
        if self.collaboration:
            return bool(
                self.collaboration_coalition == frozenset(("EGO", "P1"))
                and self.collaboration_ego_commit is not None
                and self.collaboration_p1_commit is not None
                and self.collaboration_ego_commit.issubset(self.holdings["EGO"])
                and self.collaboration_p1_commit.issubset(self.holdings["P1"])
                and self._committed_goal_satisfied()
            )
        if self.reroute:
            return bool(
                self.reroute_received_item is not None
                and self.reroute_ego_commit is not None
                and self.reroute_ego_commit.issubset(self.holdings["EGO"])
                and self._committed_goal_satisfied()
            )
        if self.respond_to_give_request:
            accepted_commitment_fulfilled = not self.give_request_accepted or self.give_request_fulfilled
            return bool(
                self.give_request_ego_commit is not None
                and self.give_request_ego_commit.issubset(self.holdings["EGO"])
                and self._committed_goal_satisfied()
                and accepted_commitment_fulfilled
            )
        if "EGO" not in self.committed or not all(agreement["fulfilled"] for agreement in self.agreements):
            return False
        return self._committed_goal_satisfied()

    def diagnostics(self) -> dict[str, float]:
        if self.collaboration:
            return self._collaboration_diagnostics()
        if self.reroute:
            return self._reroute_diagnostics()
        if self.respond_to_give_request:
            return self._give_request_diagnostics()
        actions = [record["action"] for record in self.records]
        partner_messages = [str(record.get("partner_message", "")) for record in self.records]
        asked_goal = any(action.startswith("ASK ") and action.endswith(" GOAL") for action in actions)
        asked_holdings = any(action.startswith("ASK ") and action.endswith(" HOLDINGS") for action in actions)
        disclosed = any(action.startswith("SAY ") and " PROFILE" in action for action in actions)
        asked_join = any(action.startswith("ASK ") and " JOIN " in action for action in actions)
        asked_give = any(action.startswith("ASK ") and " GIVE " in action for action in actions)
        accepted_cannot = any("CANNOT" in message for message in partner_messages)
        saw_cannot = False
        rerouted = False
        for record in self.records:
            if "CANNOT" in str(record.get("partner_message", "")):
                saw_cannot = True
            if saw_cannot and record["action"].startswith("ASK P2 GIVE "):
                rerouted = True
        all_fulfilled = bool(self.agreements) and all(agreement["fulfilled"] for agreement in self.agreements)
        return {
            "agreement_formed": float(bool(self.agreements)),
            "agreement_followed_through": float(all_fulfilled),
            "agreement_fulfilled": float(all_fulfilled),
            "goal_satisfied": float(self._committed_goal_satisfied()),
            "coalition_valid": float(self._coalition_valid()),
            "correct_join_commit": float(len(self.committed) > 1 and bool(self.member_commit_actions) and len(set(self.member_commit_actions.values())) == 1),
            "rerouted_after_cannot": float(rerouted),
            "rerouted_after_unavailability": float(rerouted),
            "harmful_transfer_avoided": float(self._harmful_transfer_avoided),
            "harmful_give_avoided": float(self._harmful_transfer_avoided),
            "useful_give_request": float(any(a["type"] == "give" and a["direction"] == "partner_to_ego" and a["fulfilled"] for a in self.agreements)),
            "useful_exchange_proposed": float(any(a["type"] == "exchange" for a in self.agreements)),
            "mandatory_request_answered": float(self._mandatory_request_answered),
            "asked_goal": float(asked_goal),
            "asked_holdings": float(asked_holdings),
            "disclosed_own_state": float(disclosed),
            "proposed_join": float(asked_join),
            "successful_joint_commit": float(len(self.committed) > 1 and self.ego_success),
            "identified_complementary_exchange": float(any("EXCHANGE" in action for action in actions)),
            "executed_exchange": float(any(a["type"] == "exchange" and a["fulfilled"] for a in self.agreements)),
            "coalition_commit_exact": float(bool(self.member_commit_actions) and len(set(self.member_commit_actions.values())) == 1),
            "coalition_members_committed": float(len(self.committed)),
            "asked_give": float(asked_give),
            "refused_critical_item": float(self._harmful_transfer_avoided),
            "accepted_cannot": float(accepted_cannot),
            "success": float(self.ego_success if self.done else False),
            "terminal_success": float(self.done and self.ego_success),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
            "unfulfilled_agreements": float(sum(not a["fulfilled"] for a in self.agreements)),
        }

    def _reroute_diagnostics(self) -> dict[str, float]:
        actions = [record["action"] for record in self.records]
        partner_roles = self.instance.partner_roles
        helper = next((partner for partner, role in partner_roles.items() if role == "HELPER"), None)
        blocker = next((partner for partner, role in partner_roles.items() if role != "HELPER"), None)
        blocker_role = partner_roles.get(blocker or "", "")
        commit_valid = bool(
            self.reroute_ego_commit is not None
            and self.reroute_ego_commit.issubset(self.holdings["EGO"])
        )
        success = self.ego_success
        proposal_partners = [
            partner for partner in ("P1", "P2")
            if any(action.startswith(f"PROPOSE GIVE {{giver={partner},") for action in actions)
        ]
        explored_after_success = bool(
            self.reroute_received_turn_index is not None
            and any(
                record["turn_index"] > self.reroute_received_turn_index
                and record["action"].startswith(("QUERY ", "INFORM ", "PROPOSE "))
                for record in self.records
            )
        )
        first_rejected = bool(
            self.reroute_first_partner is not None
            and self.reroute_status.get(self.reroute_first_partner) == "rejected"
        )
        return {
            "agreement_formed": float(self.reroute_accept_count > 0),
            "agreement_followed_through": float(self.reroute_received_item is not None),
            "agreement_fulfilled": float(self.reroute_received_item is not None),
            "goal_satisfied": float(self._committed_goal_satisfied()),
            "coalition_valid": 0.0,
            "correct_join_commit": 0.0,
            "rerouted_after_cannot": float(self.reroute_after_rejection_count > 0),
            "rerouted_after_unavailability": float(self.reroute_after_rejection_count > 0),
            "harmful_transfer_avoided": 0.0,
            "harmful_give_avoided": 0.0,
            "useful_give_request": float(self.reroute_received_item is not None),
            "useful_exchange_proposed": 0.0,
            "mandatory_request_answered": 0.0,
            "asked_goal": float(any(action.startswith("QUERY ") and action.endswith(" GOAL") for action in actions)),
            "asked_holdings": float(any(action.startswith("QUERY ") and action.endswith(" HOLDINGS") for action in actions)),
            "disclosed_own_state": float(any(action.startswith("INFORM ") for action in actions)),
            "proposed_join": 0.0,
            "successful_joint_commit": 0.0,
            "identified_complementary_exchange": 0.0,
            "executed_exchange": 0.0,
            "coalition_commit_exact": 0.0,
            "coalition_members_committed": 0.0,
            "asked_give": float(self.reroute_proposal_count > 0),
            "refused_critical_item": 0.0,
            "accepted_cannot": float(self.reroute_reject_count > 0),
            "success": float(success if self.done else False),
            "terminal_success": float(self.done and success),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
            "unfulfilled_agreements": 0.0,
            "proposal_accepted": float(self.reroute_accept_count > 0),
            "proposal_rejected": float(self.reroute_reject_count > 0),
            "coalition_formed": 0.0,
            "commit_valid": float(commit_valid),
            "ego_commit_item_count": float(len(self.reroute_ego_commit or set())),
            "p1_commit_item_count": 0.0,
            "redundant_commit_count": float(
                max(0, len(self.reroute_ego_commit or set()) - len(self.goals["EGO"]))
            ),
            "communication_efficiency_bonus": float(
                self.communication_left * self._COLLAB_COMMUNICATION_BONUS if success else 0.0
            ),
            "reroute_blocker_inferable": float(blocker_role == "BLOCKER_INFERABLE"),
            "reroute_blocker_hidden_unwilling": float(blocker_role == "BLOCKER_HIDDEN_UNWILLING"),
            "reroute_first_partner_is_helper": float(self.reroute_first_partner == helper),
            "reroute_first_partner_is_blocker": float(self.reroute_first_partner == blocker),
            "reroute_first_proposal_rejected": float(first_rejected),
            "rerouted_after_rejection": float(self.reroute_after_rejection_count > 0),
            "reroute_helper_reached": float(self.reroute_status.get(helper) == "accepted"),
            "reroute_unnecessary_exploration_after_success": float(explored_after_success),
            "reroute_proposal_count": float(self.reroute_proposal_count),
            "reroute_rejection_count": float(self.reroute_reject_count),
            "reroute_proposal_partner_count": float(len(proposal_partners)),
        }

    def _give_request_diagnostics(self) -> dict[str, float]:
        actions = [record["action"] for record in self.records]
        case = self.instance.request_case
        success = self.ego_success
        accepted = self.give_request_accepted
        rejected = self.give_request_rejected
        fulfilled = self.give_request_fulfilled
        return {
            "agreement_formed": float(accepted),
            "agreement_followed_through": float(fulfilled),
            "agreement_fulfilled": float(fulfilled),
            "goal_satisfied": float(self._committed_goal_satisfied()),
            "coalition_valid": 0.0,
            "correct_join_commit": 0.0,
            "rerouted_after_cannot": 0.0,
            "rerouted_after_unavailability": 0.0,
            "harmful_transfer_avoided": float(case == "harmful" and rejected),
            "harmful_give_avoided": float(case == "harmful" and rejected),
            "useful_give_request": float(accepted and fulfilled),
            "useful_exchange_proposed": 0.0,
            "mandatory_request_answered": float(accepted or rejected),
            "asked_goal": 0.0,
            "asked_holdings": 0.0,
            "disclosed_own_state": 0.0,
            "proposed_join": 0.0,
            "successful_joint_commit": 0.0,
            "identified_complementary_exchange": 0.0,
            "executed_exchange": 0.0,
            "coalition_commit_exact": 0.0,
            "coalition_members_committed": 1.0 if self.give_request_ego_commit is not None else 0.0,
            "asked_give": 0.0,
            "refused_critical_item": float(case == "harmful" and rejected),
            "accepted_cannot": 0.0,
            "success": float(success if self.done else False),
            "terminal_success": float(self.done and success),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
            "unfulfilled_agreements": float(accepted and not fulfilled),
            "proposal_accepted": float(accepted),
            "proposal_rejected": float(rejected),
            "coalition_formed": 0.0,
            "commit_valid": float(
                self.give_request_ego_commit is not None
                and self.give_request_ego_commit.issubset(self.holdings["EGO"])
            ),
            "ego_commit_item_count": float(len(self.give_request_ego_commit or set())),
            "p1_commit_item_count": 0.0,
            "redundant_commit_count": float(
                max(0, len(self.give_request_ego_commit or set()) - len(self.goals["EGO"]))
            ),
            "communication_efficiency_bonus": float(
                self.communication_left * self._COLLAB_COMMUNICATION_BONUS if success else 0.0
            ),
            "respond_request_safe": float(case == "safe"),
            "respond_request_harmful": float(case == "harmful"),
            "respond_partner_p1": float(self.instance.active_partner == "P1"),
            "respond_partner_p2": float(self.instance.active_partner == "P2"),
            "respond_partner_p3": float(self.instance.active_partner == "P3"),
            "respond_accept": float(accepted),
            "respond_reject": float(rejected),
            "respond_give_fulfilled": float(fulfilled),
            "respond_exact_give": float(
                any(action.startswith("ACT GIVE {") for action in actions) and fulfilled
            ),
            "respond_safe_correct": float(case == "safe" and accepted and fulfilled and success),
            "respond_harmful_correct": float(case == "harmful" and rejected and success),
            "respond_harmful_transfer": float(case == "harmful" and fulfilled),
        }

    def _collaboration_diagnostics(self) -> dict[str, float]:
        goal_satisfied = self._committed_goal_satisfied()
        commit_valid = bool(
            self.collaboration_ego_commit is not None
            and self.collaboration_p1_commit is not None
            and self.collaboration_ego_commit.issubset(self.holdings["EGO"])
            and self.collaboration_p1_commit.issubset(self.holdings["P1"])
        )
        success = self.ego_success
        return {
            "agreement_formed": 0.0,
            "agreement_followed_through": 0.0,
            "agreement_fulfilled": 0.0,
            "goal_satisfied": float(goal_satisfied),
            "coalition_valid": float(self.collaboration_coalition is not None),
            "correct_join_commit": 0.0,
            "rerouted_after_cannot": 0.0,
            "rerouted_after_unavailability": 0.0,
            "harmful_transfer_avoided": 0.0,
            "harmful_give_avoided": 0.0,
            "useful_give_request": 0.0,
            "useful_exchange_proposed": 0.0,
            "mandatory_request_answered": float(any(
                r["turn_phase"] == "mandatory_response" and r["action"].startswith("INFORM P1 ")
                for r in self.records
            )),
            "asked_goal": float(any(r["action"] == "QUERY P1 GOAL" for r in self.records)),
            "asked_holdings": float(any(r["action"] == "QUERY P1 HOLDINGS" for r in self.records)),
            "disclosed_own_state": float(any(r["action"].startswith("INFORM P1 ") for r in self.records)),
            "proposed_join": float(self.collaboration_proposal_count > 0),
            "successful_joint_commit": float(success),
            "identified_complementary_exchange": 0.0,
            "executed_exchange": 0.0,
            "coalition_commit_exact": float(commit_valid),
            "coalition_members_committed": float(
                2 if self.collaboration_ego_commit is not None and self.collaboration_p1_commit is not None else 0
            ),
            "asked_give": 0.0,
            "refused_critical_item": 0.0,
            "accepted_cannot": 0.0,
            "success": float(success if self.done else False),
            "terminal_success": float(self.done and success),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
            "unfulfilled_agreements": 0.0,
            "proposal_accepted": float(self.collaboration_accept_count > 0),
            "proposal_rejected": float(self.collaboration_reject_count > 0),
            "coalition_formed": float(self.collaboration_coalition is not None),
            "commit_valid": float(commit_valid),
            "ego_commit_item_count": float(len(self.collaboration_ego_commit or set())),
            "p1_commit_item_count": float(len(self.collaboration_p1_commit or set())),
            "redundant_commit_count": float(self.collaboration_redundant_commit_count),
            "communication_efficiency_bonus": float(
                self.communication_left * self._COLLAB_COMMUNICATION_BONUS if success else 0.0
            ),
        }

    def _committed_goal_satisfied(self) -> bool:
        if self.collaboration:
            if self.collaboration_ego_commit is None or self.collaboration_p1_commit is None:
                return False
            pool = set(self.collaboration_ego_commit) | set(self.collaboration_p1_commit)
            return self.goals["EGO"].issubset(pool)
        if self.reroute:
            return bool(
                self.reroute_ego_commit is not None
                and self.goals["EGO"].issubset(self.reroute_ego_commit)
            )
        if self.respond_to_give_request:
            return bool(
                self.give_request_ego_commit is not None
                and self.goals["EGO"].issubset(self.give_request_ego_commit)
            )
        if not self.committed:
            return False
        pool = set().union(*(self.holdings[player] for player in self.committed))
        return self.goals["EGO"].issubset(pool)

    def _coalition_valid(self) -> bool:
        if self.collaboration:
            return self.collaboration_coalition == frozenset(("EGO", "P1"))
        if self.reroute:
            return False
        if self.committed == {"EGO"}:
            return True
        return bool(
            self.committed
            and self.member_commit_actions
            and len(set(self.member_commit_actions.values())) == 1
            and all(self.goals[member] == self.goals["EGO"] for member in self.committed)
        )

    def _format_give_request_proposal(self, partner: str, item: str) -> str:
        return f"PROPOSE GIVE {{giver: EGO,receiver: {partner},items: {self._format_set({item})}}}"

    def get_prompt(self, mode="prefix", think=True, player_id=0):
        del player_id
        if mode != "prefix":
            raise ValueError(f"invalid prompt mode {mode!r}")
        output_format = (
            "Reason briefly inside <reason>...</reason>, then emit exactly one listed action inside <answer>...</answer>."
            if think else "Emit exactly one listed action inside <answer>...</answer>, with no reasoning text."
        )
        system = (
            "You are EGO in a sequential Item Coalition Game. Use only listed structured actions. "
            "Terminal reward is 1 only if EGO's goal is satisfied and every accepted agreement is fulfilled."
        )
        user = (
            "Turn lifecycle:\n"
            "(1) If Partner initiated an event is shown, this turn is response-only: output exactly SAY CAN_GIVE or SAY CANNOT_GIVE; ACT is illegal.\n"
            "(2) Otherwise EGO chooses exactly one autonomous ASK, SAY, or ACT.\n"
            "(3) The scripted partner emits its truthful response/action.\n"
            "(4) Only after that partner phase are holdings and commitments updated.\n\n"
            "ASK JOIN, ASK GIVE, and ASK EXCHANGE create an agreement only after AGREE. ASK GIVE then immediately runs the partner's ACT GIVE to EGO in the same transition; do not output the partner's action.\n"
            "ASK EXCHANGE: after AGREE_EXCHANGE, Ego must output ACT GIVE <give> TO <partner>; the partner then gives the receive item.\n"
            "ASK JOIN: after every member agrees, Ego must output the exact ACT JOIN_COMMIT coalition; partners then output the same commit.\n"
            "An accepted but unfulfilled agreement makes terminal reward 0.\n\n"
            "Protocol:\n"
            "ASK <partner> GOAL | ASK <partner> HOLDINGS | ASK <partner> GIVE <item> | ASK <partner> EXCHANGE give=<item> receive=<item> | ASK <partner> JOIN <coalition>\n"
            "SAY <partner> CAN_GIVE <item> | SAY <partner> CANNOT_GIVE <item> | SAY <partner> PROFILE goal=<...> holdings=<...>\n"
            "ACT GIVE <item> TO <partner> | ACT JOIN_COMMIT <coalition>\n\n" + output_format
        )
        return {"system": system, "user": user}
