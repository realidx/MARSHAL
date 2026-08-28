"""Shared sequential transition engine for Item Coalition Game v0.2.

Each Ego decision has explicit phases: an optional mandatory response, one
autonomous Ego action, a scripted partner response/action, and state update.
ASK can create an agreement, but cannot itself transfer an item or commit a
coalition. Terminal success requires the goal and every accepted agreement to
be satisfied.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from .config import ItemGameConfig
from .generator import ItemGameInstance


class BaseItemGame:
    """One Ego-centric episode with truthful, deterministic partners."""

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
        # These partner actions run after the next autonomous Ego action.
        self.pending_partner_gives: list[tuple[str, str]] = []
        self.pending_partner_give: tuple[str, str] | None = None  # compatibility view
        self.pending_exchange: tuple[str, str, str] | None = None
        self.pending_transfer: tuple[str, str] | None = None  # compatibility view
        self._mandatory_request_answered = False
        self._harmful_transfer_avoided = False

        if self.partner_event:
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

    def step(self, action: str):
        if self.done:
            raise RuntimeError("cannot act in a finished item game")
        action = " ".join(str(action).strip().split())
        if action not in self.legal_actions():
            raise ValueError(f"illegal item-game action {action!r}")

        before = self._snapshot()
        mandatory_response = self._is_mandatory_response(action)
        if action.startswith(("ASK ", "SAY ")) and not mandatory_response:
            self.communication_used += 1
        self.ego_steps += 1
        phase = "mandatory_response" if mandatory_response else "ego_action"
        self.conversation_history.append({
            "turn": self.turn_index, "actor": "EGO", "phase": phase, "action": action, "message": ""
        })

        # _apply_ego only creates an operation. Holdings and commitments are
        # updated in _run_partner_phase after the scripted partner acts.
        scheduled_partner_gives = list(self.pending_partner_gives)
        self.pending_partner_gives.clear()
        self.pending_partner_give = None
        ego_message, operation = self._apply_ego(action)
        partner_messages = self._run_partner_phase(operation, scheduled_partner_gives)

        if action.startswith("ACT JOIN_COMMIT"):
            self.done = True
        elif self.ego_steps >= self.config.max_ego_steps:
            self.done = True
        self.turn_phase = "terminal" if self.done else "ego_action"
        self.turn_index += 1
        partner_message = "\n".join(m for m in [ego_message, *partner_messages] if m)
        reward = float(self.ego_success) if self.done else 0.0
        record = {
            "action": action,
            "action_is_ask": float(action.startswith("ASK ")),
            "action_is_say": float(action.startswith("SAY ")),
            "action_is_act": float(action.startswith("ACT ")),
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

    def _apply_ego(self, action: str) -> tuple[str, dict[str, Any] | None]:
        if action.startswith("ASK "):
            return self._ask(action), None
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
        match = re.fullmatch(r"ACT JOIN_COMMIT (\{EGO(?:,P\d+)+\})", action)
        if match:
            coalition = self._parse_coalition(match.group(1))
            if not self._coalition_is_approved(coalition):
                raise ValueError("all coalition partners must consent before commit")
            return "", {"type": "join", "coalition": coalition, "action": action}
        raise ValueError(f"unsupported item-game action {action!r}")

    def _run_partner_phase(
        self,
        operation: dict[str, Any] | None,
        scheduled_partner_gives: list[tuple[str, str]],
    ) -> list[str]:
        messages: list[str] = []
        # Fulfill earlier partner-to-Ego GIVE commitments only after this Ego
        # action. This is a partner scripted action, not an Ego action.
        for partner, item in scheduled_partner_gives:
            if item not in self.holdings[partner]:
                raise RuntimeError(f"partner {partner} violated accepted GIVE commitment for {item!r}")
            self.holdings[partner].remove(item)
            self.holdings["EGO"].add(item)
            self._mark_fulfilled("give", partner=partner, item=item, direction="partner_to_ego")
            self._record_partner(partner, f"ACT GIVE {item} TO EGO", f"{partner} fulfills GIVE {item} to EGO.", "scripted_action")
            messages.append(f"{partner} ACT GIVE {item} TO EGO.")
        self.pending_partner_give = self.pending_partner_gives[-1] if self.pending_partner_gives else None

        if operation is None:
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

    def _ask(self, action: str) -> str:
        parts = action.split()
        partner = parts[1]
        if parts[2] == "GOAL":
            self.known[partner]["goal"] = set(self.goals[partner])
            return self._reply(partner, f"SAY {partner} GOAL", f"{partner} answers GOAL {self._format_set(self.goals[partner])}.")
        if parts[2] == "HOLDINGS":
            self.known[partner]["holdings"] = set(self.holdings[partner])
            return self._reply(partner, f"SAY {partner} HOLDINGS", f"{partner} answers HOLDINGS {self._format_set(self.holdings[partner])}.")
        if parts[2] == "JOIN":
            coalition = self._parse_coalition(parts[3])
            if self._partner_accepts_join(partner, coalition):
                self.join_approved.setdefault(coalition, set()).add(partner)
                self._new_agreement("join", partner=partner, coalition=coalition)
                return self._reply(partner, f"SAY {partner} AGREE_JOIN {parts[3]}", f"{partner} says AGREE_JOIN {parts[3]}.")
            return self._reply(partner, f"SAY {partner} CANNOT_JOIN {parts[3]}", f"{partner} says CANNOT_JOIN {parts[3]}.")
        if parts[2] == "GIVE":
            item = parts[3]
            if not self._partner_accepts_give(partner, item):
                return self._reply(partner, f"SAY {partner} CANNOT_GIVE {item}", f"{partner} says CANNOT_GIVE {item}.")
            self._new_agreement("give", partner=partner, item=item, direction="partner_to_ego")
            self.pending_partner_gives.append((partner, item))
            self.pending_partner_give = (partner, item)
            return self._reply(partner, f"SAY {partner} AGREE_GIVE {item}", f"{partner} says AGREE_GIVE {item}. Agreement formed; partner ACT GIVE occurs after Ego's next action.")
        if parts[2] == "EXCHANGE":
            match = re.fullmatch(r"ASK (P\d+) EXCHANGE give=(\S+) receive=(\S+)", action)
            if match is None:
                raise ValueError(f"invalid EXCHANGE request {action!r}")
            _, give, receive = match.groups()
            if not self._partner_accepts_exchange(partner, give, receive):
                return self._reply(partner, f"SAY {partner} CANNOT_EXCHANGE", f"{partner} says CANNOT_EXCHANGE.")
            self._new_agreement("exchange", partner=partner, give=give, receive=receive)
            self.pending_exchange = (partner, give, receive)
            return self._reply(partner, f"SAY {partner} AGREE_EXCHANGE give={give} receive={receive}", f"{partner} says AGREE_EXCHANGE give={give} receive={receive}. Agreement formed; Ego must ACT GIVE {give} TO {partner}.")
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
        members = tuple(member for member in raw[1:-1].split(",") if member)
        coalition = frozenset(members)
        if not members or len(coalition) != len(members) or "EGO" not in coalition or not coalition.issubset(set(self.players)) or self._format_coalition(coalition) != raw:
            raise ValueError(f"invalid coalition {raw!r}")
        return coalition

    @staticmethod
    def _requested_item(request: str) -> str | None:
        match = re.search(r"GIVE (\S+)$", request)
        return match.group(1) if match else None

    @staticmethod
    def _format_set(items: set[str] | frozenset[str]) -> str:
        return "{" + ",".join(sorted(items)) + "}"

    def _snapshot(self) -> dict[str, tuple[str, ...]]:
        return {player: tuple(sorted(items)) for player, items in self.holdings.items()}

    @property
    def ego_success(self) -> bool:
        if "EGO" not in self.committed or not all(agreement["fulfilled"] for agreement in self.agreements):
            return False
        return self._committed_goal_satisfied()

    def diagnostics(self) -> dict[str, float]:
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

    def _committed_goal_satisfied(self) -> bool:
        if not self.committed:
            return False
        pool = set().union(*(self.holdings[player] for player in self.committed))
        return self.goals["EGO"].issubset(pool)

    def _coalition_valid(self) -> bool:
        if self.committed == {"EGO"}:
            return True
        return bool(
            self.committed
            and self.member_commit_actions
            and len(set(self.member_commit_actions.values())) == 1
            and all(self.goals[member] == self.goals["EGO"] for member in self.committed)
        )

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
            "ASK JOIN, ASK GIVE, and ASK EXCHANGE create an agreement only after AGREE. They do not transfer items or commit a coalition in that turn.\n"
            "ASK GIVE: the partner's ACT GIVE to EGO executes after Ego's next action. Do not output the partner's action.\n"
            "ASK EXCHANGE: after AGREE_EXCHANGE, Ego must output ACT GIVE <give> TO <partner>; the partner then gives the receive item.\n"
            "ASK JOIN: after every member agrees, Ego must output the exact ACT JOIN_COMMIT coalition; partners then output the same commit.\n"
            "An accepted but unfulfilled agreement makes terminal reward 0.\n\n"
            "Protocol:\n"
            "ASK <partner> GOAL | ASK <partner> HOLDINGS | ASK <partner> GIVE <item> | ASK <partner> EXCHANGE give=<item> receive=<item> | ASK <partner> JOIN <coalition>\n"
            "SAY <partner> CAN_GIVE <item> | SAY <partner> CANNOT_GIVE <item> | SAY <partner> PROFILE goal=<...> holdings=<...>\n"
            "ACT GIVE <item> TO <partner> | ACT JOIN_COMMIT <coalition>\n\n" + output_format
        )
        return {"system": system, "user": user}
