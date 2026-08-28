"""Shared sequential item-game transition engine for Item Coalition Game v0.1."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from .config import ItemGameConfig
from .generator import ItemGameInstance


class BaseItemGame:
    """One Ego-centric episode with deterministic, truthful scripted partners.

    The rollout runtime only chooses Ego actions. When a partner must act, the
    scripted action is recorded in ``conversation_history`` and applied
    deterministically as part of the same environment transition. Agreements
    are kept separately from those actions so diagnostics can distinguish
    reaching an agreement from following it through.
    """

    def __init__(self, instance: ItemGameInstance, config: ItemGameConfig):
        self.instance = instance
        self.config = config
        self.goals = {player: set(goal) for player, goal in instance.goals.items()}
        self.holdings = {player: set(items) for player, items in instance.holdings.items()}
        self.known = {"EGO": {"goal": set(self.goals["EGO"]), "holdings": set(self.holdings["EGO"])}}
        self.known.update({player: {} for player in self.players if player != "EGO"})

        self.communication_used = 0
        self.ego_steps = 0
        self.records: list[dict[str, Any]] = []
        self.conversation_history: list[dict[str, str]] = []
        self.agreements: list[dict[str, Any]] = []
        self.done = False
        self.committed: set[str] = set()

        # A JOIN answer is consent for a particular coalition. It is not a
        # commit: every member must later emit the same JOIN_COMMIT action.
        self.join_approved: dict[frozenset[str], set[str]] = {}
        self.member_commit_actions: dict[str, str] = {}

        self.partner_event = (
            f"ASK EGO GIVE {instance.partner_event}" if instance.partner_event else None
        )
        self.pending_partner_request: str | None = self.partner_event
        self.pending_request_partner: str | None = "P1" if self.partner_event else None
        # ``pending_transfer`` is an Ego-to-partner GIVE agreed by a mandatory
        # response. A partner-to-Ego GIVE is scripted after ASK GIVE and does
        # not need an Ego action.
        self.pending_transfer: tuple[str, str] | None = None
        self.pending_transfer_direction: str | None = None
        # An accepted exchange waits for Ego to execute its GIVE leg.
        self.pending_exchange: tuple[str, str, str] | None = None
        # An accepted partner-to-Ego GIVE is executed by the scripted partner
        # before Ego's next decision, without consuming an Ego step/budget.
        self.pending_partner_give: tuple[str, str] | None = None
        self._mandatory_request_answered = False
        self._harmful_transfer_avoided = False

        if self.partner_event:
            self._record_partner(
                "P1",
                self.partner_event,
                "P1 asks EGO to give the requested item.",
            )

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

        # A partner's direct request has priority. This response is always
        # legal, including when the normal communication budget is exhausted.
        if self.pending_partner_request and self.pending_transfer is None:
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
                for give in sorted(self.holdings["EGO"]):
                    for receive in self.items:
                        actions.append(f"ASK {partner} EXCHANGE give={give} receive={receive}")
                for coalition in self._coalitions_containing(partner):
                    actions.append(f"ASK {partner} JOIN {self._format_coalition(coalition)}")
                actions.append(self._profile_action(partner))

        # ACT GIVE is only available after an explicit agreement. An accepted
        # exchange exposes its Ego GIVE leg; a mandatory partner request
        # exposes the direct Ego GIVE leg.
        if self.pending_transfer:
            partner, item = self.pending_transfer
            actions.append(f"ACT GIVE {item} TO {partner}")
        if self.pending_exchange:
            partner, give, _ = self.pending_exchange
            actions.append(f"ACT GIVE {give} TO {partner}")

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
        scripted_message = self._flush_partner_give()
        mandatory_response = self._is_mandatory_response(action)
        if action.startswith(("ASK ", "SAY ")) and not mandatory_response:
            self.communication_used += 1
        self.ego_steps += 1
        self.conversation_history.append({"actor": "EGO", "action": action, "message": ""})
        partner_message = self._apply(action)
        if scripted_message:
            partner_message = f"{scripted_message}\n{partner_message}"

        if action.startswith("ACT JOIN_COMMIT"):
            self.done = True
        elif self.ego_steps >= self.config.max_ego_steps:
            self.done = True

        reward = float(self.ego_success) if self.done else 0.0
        record = {
            "action": action,
            "action_is_ask": float(action.startswith("ASK ")),
            "action_is_say": float(action.startswith("SAY ")),
            "action_is_act": float(action.startswith("ACT ")),
            "communication_used": self.communication_used,
            "ego_step": self.ego_steps,
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
            info.update(
                {
                    "success": True,
                    "ego_success": float(self.ego_success),
                    "player_0_return": reward,
                    "player_1_return": 0.0,
                    "player_0_success": bool(self.ego_success),
                    "player_1_success": False,
                    "winner": 0 if self.ego_success else -1,
                }
            )
        return partner_message, reward, self.done, info

    def _apply(self, action: str) -> str:
        if action.startswith("ASK "):
            return self._ask(action)
        if action.startswith("SAY "):
            return self._say(action)
        if action.startswith("ACT GIVE "):
            match = re.fullmatch(r"ACT GIVE (\S+) TO (P\d+)", action)
            if match is None:
                raise ValueError(f"invalid GIVE action {action!r}")
            item, partner = match.groups()
            if self.pending_transfer == (partner, item):
                if item not in self.holdings["EGO"]:
                    raise ValueError(f"EGO does not hold {item!r}")
                self.holdings["EGO"].remove(item)
                self.holdings[partner].add(item)
                self.pending_transfer = None
                self.pending_transfer_direction = None
                self.pending_partner_request = None
                self.pending_request_partner = None
                self.partner_event = None
                self._mark_followed(
                    "give", partner=partner, item=item, direction="ego_to_partner"
                )
                return f"EGO ACT GIVE {item} TO {partner}."

            if self.pending_exchange and self.pending_exchange[0] == partner:
                _, give, receive = self.pending_exchange
                if item != give:
                    raise ValueError("GIVE item does not match the approved exchange")
                if not self._exchange_acceptable(partner, give, receive):
                    raise ValueError("approved exchange is no longer feasible")
                self.holdings["EGO"].remove(give)
                self.holdings[partner].remove(receive)
                self.holdings[partner].add(give)
                self.holdings["EGO"].add(receive)
                self.pending_exchange = None
                self._mark_followed(
                    "exchange", partner=partner, give=give, receive=receive
                )
                partner_action = f"ACT GIVE {receive} TO EGO"
                self._record_partner(partner, partner_action, "Partner follows through on the exchange.")
                return f"EGO ACT GIVE {give} TO {partner}.\n{partner} {partner_action}."
            raise ValueError("no approved GIVE is pending")

        if action == "ACT JOIN_COMMIT {EGO}":
            self.committed = {"EGO"}
            self.member_commit_actions = {"EGO": action}
            return "EGO commits its current holdings."

        match = re.fullmatch(r"ACT JOIN_COMMIT (\{EGO(?:,P\d+)+\})", action)
        if match:
            coalition = self._parse_coalition(match.group(1))
            if not self._coalition_is_approved(coalition):
                raise ValueError("all coalition partners must consent before commit")
            self.member_commit_actions = {
                member: action for member in self._ordered_members(coalition)
            }
            self.committed = set(coalition)
            for agreement in self.agreements:
                if agreement.get("type") == "join" and agreement.get("coalition") == match.group(1):
                    agreement["followed_through"] = True
            for member in self._ordered_members(coalition):
                if member != "EGO":
                    self._record_partner(member, action, "Partner emits the exact same JOIN_COMMIT.")
            members = " and ".join(self._ordered_members(coalition))
            return f"{members} output the same JOIN_COMMIT and commit the pooled holdings."

        raise ValueError(f"unsupported item-game action {action!r}")

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
            if (
                partner in coalition
                and "EGO" in coalition
                and all(self.goals[member] == self.goals["EGO"] for member in coalition)
                and self.goals["EGO"].issubset(
                    set().union(*(self.holdings[member] for member in coalition))
                )
            ):
                self.join_approved.setdefault(coalition, set()).add(partner)
                self._new_agreement("join", partner=partner, coalition=parts[3])
                message = f"{partner} says AGREE_JOIN {parts[3]}."
                return self._reply(partner, f"SAY {partner} AGREE_JOIN {parts[3]}", message)
            return self._reply(partner, f"SAY {partner} CANNOT_JOIN {parts[3]}", f"{partner} says CANNOT_JOIN {parts[3]}.")
        if parts[2] == "GIVE":
            item = parts[3]
            if item not in self.holdings[partner] or not self.goals[partner].issubset(
                self.holdings[partner] - {item}
            ):
                return self._reply(partner, f"SAY {partner} CANNOT_GIVE {item}", f"{partner} says CANNOT_GIVE {item}.")

            agreement = self._new_agreement(
                "give", partner=partner, item=item, direction="partner_to_ego"
            )
            # This agreement is deliberately not executed in this ASK
            # transition. The scripted partner acts before Ego's next turn.
            self.pending_partner_give = (partner, item)
            first = f"{partner} says CAN_GIVE {item}."
            self._reply(partner, f"SAY {partner} CAN_GIVE {item}", first)
            return f"{first}\nPending scripted action: ACT GIVE {item} TO EGO."
        if parts[2] == "EXCHANGE":
            match = re.fullmatch(r"ASK (P\d+) EXCHANGE give=(\S+) receive=(\S+)", action)
            if match is None:
                raise ValueError(f"invalid EXCHANGE request {action!r}")
            _, give, receive = match.groups()
            if not self._exchange_acceptable(partner, give, receive):
                return self._reply(partner, f"SAY {partner} CANNOT_EXCHANGE", f"{partner} says CANNOT_EXCHANGE.")
            self.pending_exchange = (partner, give, receive)
            self._new_agreement("exchange", partner=partner, give=give, receive=receive)
            message = f"{partner} says AGREE_EXCHANGE give={give} receive={receive}."
            return self._reply(
                partner,
                f"SAY {partner} AGREE_EXCHANGE give={give} receive={receive}",
                message,
            )
        raise ValueError(f"unsupported ASK action {action!r}")

    def _say(self, action: str) -> str:
        profile = re.fullmatch(r"SAY (P\d+) PROFILE goal=(\{[^}]*\}) holdings=(\{[^}]*\})", action)
        if profile is not None:
            partner = profile.group(1)
            self.known[partner] = {
                "goal": set(self.goals["EGO"]),
                "holdings": set(self.holdings["EGO"]),
            }
            return self._reply(partner, action, f"{partner} receives EGO's PROFILE.")

        match = re.fullmatch(r"SAY (P\d+) (CAN_GIVE|CANNOT_GIVE) (\S+)", action)
        if match is None or self.pending_partner_request is None:
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
            self.pending_transfer = (partner, item)
            self.pending_transfer_direction = "ego_to_partner"
            self._new_agreement("give", partner=partner, item=item, direction="ego_to_partner")
            return self._reply(partner, f"SAY {partner} AGREE_GIVE {item}", f"{partner} records AGREE_GIVE {item}.")

        if item in self.goals["EGO"]:
            self._harmful_transfer_avoided = True
        self.pending_partner_request = None
        self.pending_request_partner = None
        self.partner_event = None
        self.pending_transfer = None
        self.pending_transfer_direction = None
        return self._reply(partner, action, f"{partner} records CANNOT_GIVE {item}.")

    def _exchange_acceptable(self, partner: str, give: str, receive: str) -> bool:
        if give not in self.holdings["EGO"] or receive not in self.holdings[partner]:
            return False
        before = len(self.goals[partner] & self.holdings[partner])
        after_holdings = (self.holdings[partner] - {receive}) | {give}
        after = len(self.goals[partner] & after_holdings)
        return self.goals[partner].issubset(after_holdings) or after > before

    def _new_agreement(self, agreement_type: str, **fields: Any) -> dict[str, Any]:
        agreement = {"type": agreement_type, "followed_through": False, **fields}
        self.agreements.append(agreement)
        return agreement

    def _mark_followed(self, agreement_type: str, **fields: Any) -> None:
        for agreement in reversed(self.agreements):
            if agreement.get("type") != agreement_type or agreement.get("followed_through"):
                continue
            if all(agreement.get(key) == value for key, value in fields.items()):
                agreement["followed_through"] = True
                return

    def _reply(self, partner: str, action: str, message: str) -> str:
        self._record_partner(partner, action, message)
        return message

    def _flush_partner_give(self) -> str:
        if self.pending_partner_give is None:
            return ""
        partner, item = self.pending_partner_give
        if item not in self.holdings[partner]:
            raise ValueError("pending partner GIVE item is no longer available")
        self.holdings[partner].remove(item)
        self.holdings["EGO"].add(item)
        self.pending_partner_give = None
        self._mark_followed(
            "give", partner=partner, item=item, direction="partner_to_ego"
        )
        partner_action = f"ACT GIVE {item} TO EGO"
        self._record_partner(partner, partner_action, "Partner follows through on the GIVE agreement.")
        return f"{partner} {partner_action}."

    def _profile_action(self, partner: str) -> str:
        return (
            f"SAY {partner} PROFILE goal={self._format_set(self.goals['EGO'])} "
            f"holdings={self._format_set(self.holdings['EGO'])}"
        )

    def _record_partner(self, partner: str, action: str, message: str) -> None:
        self.conversation_history.append({"actor": partner, "action": action, "message": message})

    def _is_mandatory_response(self, action: str) -> bool:
        return bool(
            self.pending_partner_request
            and re.fullmatch(r"SAY P\d+ (?:CAN_GIVE|CANNOT_GIVE) \S+", action)
        )

    def _coalitions(self) -> tuple[frozenset[str], ...]:
        partners = tuple(player for player in self.players if player != "EGO")
        return tuple(
            frozenset(("EGO", *members))
            for size in range(len(partners) + 1)
            for members in combinations(partners, size)
        )

    def _coalitions_containing(self, partner: str) -> tuple[frozenset[str], ...]:
        return tuple(coalition for coalition in self._coalitions() if partner in coalition)

    def _coalition_is_approved(self, coalition: frozenset[str]) -> bool:
        approved = self.join_approved.get(coalition, set())
        return (
            approved == set(coalition) - {"EGO"}
            and all(self.goals[member] == self.goals["EGO"] for member in coalition)
            and self.goals["EGO"].issubset(
                set().union(*(self.holdings[member] for member in coalition))
            )
        )

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
        if (
            not members
            or len(coalition) != len(members)
            or "EGO" not in coalition
            or not coalition.issubset(set(self.players))
            or self._format_coalition(coalition) != raw
        ):
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
        pool = set().union(*(self.holdings[player] for player in self.committed)) if self.committed else set()
        return "EGO" in self.committed and self.goals["EGO"].issubset(pool)

    def diagnostics(self) -> dict[str, float]:
        actions = [record["action"] for record in self.records]
        partner_messages = [str(record.get("partner_message", "")) for record in self.records]
        asked_goal = any(action.startswith("ASK ") and action.endswith(" GOAL") for action in actions)
        asked_holdings = any(action.startswith("ASK ") and action.endswith(" HOLDINGS") for action in actions)
        disclosed = any(action.startswith("SAY ") and " PROFILE" in action for action in actions)
        asked_join = any(action.startswith("ASK ") and " JOIN " in action for action in actions)
        asked_give = any(action.startswith("ASK ") and " GIVE " in action for action in actions)
        accepted_cannot = any("CANNOT" in message for message in partner_messages)
        rerouted = False
        saw_cannot = False
        for record in self.records:
            partner_message = str(record.get("partner_message", ""))
            if "CANNOT GIVE" in partner_message or "CANNOT_GIVE" in partner_message:
                saw_cannot = True
            if saw_cannot and record["action"].startswith("ASK P2 GIVE "):
                rerouted = True
        followed_exchange = any(
            agreement.get("type") == "exchange" and agreement.get("followed_through")
            for agreement in self.agreements
        )
        return {
            # v0.1 diagnostics.
            "agreement_formed": float(bool(self.agreements)),
            "agreement_followed_through": float(
                any(agreement.get("followed_through") for agreement in self.agreements)
            ),
            "correct_join_commit": float(
                len(self.committed) > 1
                and bool(self.member_commit_actions)
                and len(set(self.member_commit_actions.values())) == 1
            ),
            "rerouted_after_cannot": float(rerouted),
            "harmful_transfer_avoided": float(self._harmful_transfer_avoided),
            "useful_give_request": float(
                any(
                    agreement.get("type") == "give"
                    and agreement.get("direction") == "partner_to_ego"
                    and agreement.get("followed_through")
                    for agreement in self.agreements
                )
            ),
            "useful_exchange_proposed": float(
                any(agreement.get("type") == "exchange" for agreement in self.agreements)
            ),
            "mandatory_request_answered": float(self._mandatory_request_answered),
            # Compatibility and general protocol diagnostics.
            "asked_goal": float(asked_goal),
            "asked_holdings": float(asked_holdings),
            "disclosed_own_state": float(disclosed),
            "proposed_join": float(asked_join),
            "successful_joint_commit": float(len(self.committed) > 1 and self.ego_success),
            "identified_complementary_exchange": float(any("EXCHANGE" in action for action in actions)),
            "executed_exchange": float(followed_exchange),
            "coalition_commit_exact": float(
                bool(self.member_commit_actions)
                and len(set(self.member_commit_actions.values())) == 1
            ),
            "coalition_members_committed": float(len(self.committed)),
            "asked_give": float(asked_give),
            "refused_critical_item": float(self._harmful_transfer_avoided),
            "accepted_cannot": float(accepted_cannot),
            "success": float(self.ego_success if self.done else False),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
        }

    def get_prompt(self, mode="prefix", think=True, player_id=0):
        del player_id
        if mode != "prefix":
            raise ValueError(f"invalid prompt mode {mode!r}")
        if think:
            output_format = (
                "Reason briefly inside <reason>...</reason>, then emit exactly one listed action "
                "inside <answer>...</answer>."
            )
        else:
            output_format = "Emit exactly one listed action inside <answer>...</answer>, with no reasoning text."
        system = (
            "You are the EGO in a sequential Item Coalition Game. Use only the listed structured actions. "
            "ASK and ordinary SAY consume communication budget; a mandatory response to a partner request does not. "
            "Only ACT actions change Ego-controlled state. Terminal reward is 1 exactly when Ego's committed pool satisfies its goal."
        )
        user = (
            "At every turn choose exactly one legal action. The available protocol is:\n"
            "ASK <partner> GOAL | ASK <partner> HOLDINGS | ASK <partner> GIVE <item> | "
            "ASK <partner> EXCHANGE give=<item> receive=<item> | ASK <partner> JOIN <coalition>\n"
            "SAY <partner> CAN_GIVE <item> | SAY <partner> CANNOT_GIVE <item> | "
            "SAY <partner> PROFILE goal=<...> holdings=<...>\n"
            "ACT GIVE <item> TO <partner> | ACT JOIN_COMMIT <coalition>\n\n"
            "ASK GIVE forms an agreement; a truthful partner then performs its scripted ACT GIVE to EGO. "
            "ASK EXCHANGE only forms an agreement. Execute an accepted exchange with ACT GIVE for your item; "
            "the partner then gives the agreed receive item; do not use a separate ACT form for exchange. "
            "If a partner asks EGO to GIVE an item, the next decision must be SAY CAN_GIVE or SAY CANNOT_GIVE. "
            "CAN_GIVE does not transfer the item; follow it with ACT GIVE. "
            "A JOIN agreement is not a commit: every listed partner must agree, then output the exact same "
            "ACT JOIN_COMMIT coalition. The episode ends at JOIN_COMMIT or after the step limit.\n\n"
            + output_format
        )
        return {"system": system, "user": user}
