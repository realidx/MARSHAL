"""Shared sequential item-game transition engine."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from .config import ItemGameConfig
from .generator import ItemGameInstance


class BaseItemGame:
    """One ego-centric episode with deterministic truthful partners."""

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
        self.done = False
        self.committed: set[str] = set()
        # A JOIN answer is consent for a particular coalition.  It is not a
        # commit: every member must later emit the same JOIN_COMMIT action.
        self.join_approved: dict[frozenset[str], set[str]] = {}
        self.member_commit_actions: dict[str, str] = {}
        self.partner_event = (
            f"ASK EGO GIVE {instance.partner_event}" if instance.partner_event else None
        )
        self.pending_partner_request: str | None = self.partner_event
        self.pending_transfer: tuple[str, str] | None = None
        self.pending_transfer_direction: str | None = None
        self.pending_exchange: tuple[str, str, str] | None = None

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
            if self.pending_partner_request:
                item = self._requested_item(self.pending_partner_request)
                if item is not None:
                    actions.append(f"SAY P1 CANNOT_GIVE {item}")
                    if item in self.holdings["EGO"]:
                        actions.append(f"SAY P1 CAN_GIVE {item}")
        for partner in partners:
            actions.extend(f"ACT TRANSFER {partner} {item}" for item in sorted(self.holdings["EGO"]))
            if self.pending_exchange and self.pending_exchange[0] == partner:
                _, give, receive = self.pending_exchange
                actions.append(f"ACT EXCHANGE {partner} give={give} receive={receive}")
        actions.append("ACT JOIN_COMMIT {EGO}")
        for coalition in self._coalitions():
            if len(coalition) > 1 and self._coalition_is_approved(coalition):
                actions.append(f"ACT JOIN_COMMIT {self._format_coalition(coalition)}")
        return tuple(dict.fromkeys(actions))

    def step(self, action: str):
        if self.done:
            raise RuntimeError("cannot act in a finished item game")
        action = self._normalize_action(" ".join(str(action).strip().split()))
        if action not in self.legal_actions():
            raise ValueError(f"illegal item-game action {action!r}")
        before = self._snapshot()
        is_comm = action.startswith(("ASK ", "SAY "))
        if is_comm:
            self.communication_used += 1
        self.ego_steps += 1
        partner_message = self._apply(action)
        if action.startswith("ACT JOIN_COMMIT"):
            self.done = True
        elif self.ego_steps >= self.config.max_ego_steps:
            self.done = True
        reward = 0.0
        if self.done:
            reward = float(self.ego_success)
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
        # The benchmark has one reward only: Ego's terminal goal satisfaction.
        # The second slot is retained for the two-player rollout interface but
        # is always zero because scripted partners are not rewarded.
        info.update({"game_transition": 1.0, "canonical_reward_player_0": reward, "canonical_reward_player_1": 0.0})
        if self.done:
            # ``success`` means that the environment reached a valid terminal
            # state.  The binary game outcome is kept separate so a legal loss
            # is not mistaken for runner truncation by generic preflight code.
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

    def _normalize_action(self, action: str) -> str:
        """Accept the two equivalent spellings used in the v0 design notes."""
        if action == "SAY P1 PROFILE":
            return self._profile_action("P1")
        match = re.fullmatch(r"ACT TRANSFER_EXCHANGE\((P\d+),\s*(\S+)\s*[↔<->]+\s*(\S+)\)", action)
        if match:
            return f"ACT EXCHANGE {match.group(1)} give={match.group(2)} receive={match.group(3)}"
        # Keep the pre-v0 spelling readable for old recorded trajectories, but
        # expose and record only the canonical ACT EXCHANGE form.
        if action.startswith("ACT TRANSFER_EXCHANGE "):
            return "ACT EXCHANGE " + action.removeprefix("ACT TRANSFER_EXCHANGE ")
        return action

    def _apply(self, action: str) -> str:
        if action.startswith("ASK "):
            return self._ask(action)
        if action.startswith("SAY "):
            return self._say(action)
        if action.startswith("ACT EXCHANGE "):
            match = re.fullmatch(r"ACT EXCHANGE (P\d+) give=(\S+) receive=(\S+)", action)
            assert match
            partner, give, receive = match.group(1), match.group(2), match.group(3)
            if self.pending_exchange != (partner, give, receive):
                raise ValueError("no partner-approved exchange is pending")
            return self._exchange(partner, give, receive)
        if action.startswith("ACT TRANSFER "):
            _, _, partner, item = action.split()
            if item not in self.holdings["EGO"]:
                raise ValueError(f"EGO does not hold {item!r}")
            self.holdings["EGO"].remove(item)
            self.holdings[partner].add(item)
            if self.pending_transfer == (partner, item):
                self.pending_transfer = None
                self.pending_transfer_direction = None
            if self.pending_partner_request and self._requested_item(self.pending_partner_request) == item:
                self.pending_partner_request = None
                self.partner_event = None
            return f"EGO transfers {item} to {partner}."
        if action == "ACT JOIN_COMMIT {EGO}":
            self.committed = {"EGO"}
            self.member_commit_actions = {"EGO": action}
            return "EGO commits its current holdings."
        match = re.fullmatch(r"ACT JOIN_COMMIT (\{EGO(?:,P\d+)+\})", action)
        if match:
            coalition = self._parse_coalition(match.group(1))
            if not self._coalition_is_approved(coalition):
                raise ValueError("all coalition partners must consent before commit")
            # Scripted partners emit precisely the same commit action without
            # consuming an Ego step.  This makes the exact-action coalition
            # rule explicit in state and diagnostics.
            self.member_commit_actions = {
                member: action for member in self._ordered_members(coalition)
            }
            self.committed = set(coalition)
            members = " and ".join(self._ordered_members(coalition))
            return f"{members} output the same JOIN_COMMIT and commit the pooled holdings."
        raise ValueError(f"unsupported action {action!r}")

    def _ask(self, action: str) -> str:
        parts = action.split()
        partner = parts[1]
        if parts[2] == "GOAL":
            self.known[partner]["goal"] = set(self.goals[partner])
            return f"{partner} answers GOAL {self._format_set(self.goals[partner])}."
        if parts[2] == "HOLDINGS":
            self.known[partner]["holdings"] = set(self.holdings[partner])
            return f"{partner} answers HOLDINGS {self._format_set(self.holdings[partner])}."
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
                return f"{partner} answers YES to JOIN {self._format_coalition(coalition)}."
            return f"{partner} answers CANNOT to JOIN."
        if parts[2] == "GIVE":
            item = parts[3]
            if item not in self.holdings[partner]:
                return f"{partner} answers CANNOT GIVE {item}."
            if self.goals[partner].issubset(self.holdings[partner] - {item}):
                self.holdings[partner].remove(item)
                self.holdings["EGO"].add(item)
                return f"{partner} answers YES and transfers {item} to EGO."
            return f"{partner} answers CANNOT GIVE {item}."
        if parts[2] == "EXCHANGE":
            match = re.fullmatch(r"ASK (P\d+) EXCHANGE give=(\S+) receive=(\S+)", action)
            assert match
            give, receive = match.group(2), match.group(3)
            if self._exchange_acceptable(partner, give, receive):
                self.pending_exchange = (partner, give, receive)
                return f"{partner} answers YES and exchanges {receive} for {give}."
            return f"{partner} answers CANNOT to EXCHANGE."
        raise ValueError(f"unsupported ASK action {action!r}")

    def _say(self, action: str) -> str:
        profile = re.fullmatch(r"SAY (P\d+) PROFILE goal=\{[^}]*\} holdings=\{[^}]*\}", action)
        if profile is not None:
            partner = profile.group(1)
            self.known[partner] = {"goal": set(self.goals["EGO"]), "holdings": set(self.holdings["EGO"])}
            return f"{partner} receives PROFILE goal={self._format_set(self.goals['EGO'])} holdings={self._format_set(self.holdings['EGO'])}."
        match = re.fullmatch(r"SAY P1 (CAN_GIVE|CANNOT_GIVE) (\S+)", action)
        if match is None or self.pending_partner_request is None:
            raise ValueError("SAY GIVE response requires a pending partner request")
        item = match.group(2)
        can_give = match.group(1) == "CAN_GIVE"
        if can_give:
            if item not in self.holdings["EGO"]:
                raise ValueError(f"EGO does not hold {item!r}")
            self.pending_transfer = ("P1", item)
            self.pending_transfer_direction = "ego_to_partner"
            return f"P1 records that EGO can give {item}."
        self.pending_partner_request = None
        self.partner_event = None
        self.pending_transfer = None
        self.pending_transfer_direction = None
        return f"P1 records that EGO cannot give {item}."

    def _exchange_acceptable(self, partner: str, give: str, receive: str) -> bool:
        if give not in self.holdings["EGO"] or receive not in self.holdings[partner]:
            return False
        before = len(self.goals[partner] & self.holdings[partner])
        after = len(self.goals[partner] & ((self.holdings[partner] - {receive}) | {give}))
        return self.goals[partner].issubset((self.holdings[partner] - {receive}) | {give}) or after > before

    def _exchange(self, partner: str, give: str, receive: str) -> str:
        if not self._exchange_acceptable(partner, give, receive):
            raise ValueError("partner rejects this exchange")
        self.holdings["EGO"].remove(give)
        self.holdings[partner].remove(receive)
        self.holdings["EGO"].add(receive)
        self.holdings[partner].add(give)
        self.pending_exchange = None
        return f"EGO and {partner} exchange {give} for {receive}."

    def _profile_action(self, partner: str) -> str:
        return f"SAY {partner} PROFILE goal={self._format_set(self.goals['EGO'])} holdings={self._format_set(self.holdings['EGO'])}"

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
        asked_goal = any(action.startswith("ASK ") and action.endswith(" GOAL") for action in actions)
        asked_holdings = any(action.startswith("ASK ") and action.endswith(" HOLDINGS") for action in actions)
        disclosed = any(action.startswith("SAY ") and " PROFILE" in action for action in actions)
        asked_join = any(action.startswith("ASK ") and " JOIN " in action for action in actions)
        asked_give = any(action.startswith("ASK ") and " GIVE " in action for action in actions)
        refused_critical = any(action.startswith("SAY ") and " CANNOT_GIVE " in action for action in actions)
        rerouted = any(action.startswith("ASK P2 GIVE ") for action in actions)
        return {
            "asked_goal": float(asked_goal),
            "asked_holdings": float(asked_holdings),
            "disclosed_own_state": float(disclosed),
            "proposed_join": float(asked_join),
            "successful_joint_commit": float(len(self.committed) > 1 and self.ego_success),
            "identified_complementary_exchange": float(any("EXCHANGE" in action for action in actions)),
            "executed_exchange": float(any(action.startswith("ACT EXCHANGE ") for action in actions)),
            "coalition_commit_exact": float(
                bool(self.member_commit_actions)
                and len(set(self.member_commit_actions.values())) == 1
            ),
            "coalition_members_committed": float(len(self.committed)),
            "asked_give": float(asked_give),
            "refused_critical_item": float(refused_critical),
            "accepted_cannot": float(any("CANNOT" in record.get("partner_message", "") for record in self.records)),
            "rerouted_after_cannot": float(rerouted),
            "success": float(self.ego_success if self.done else False),
            "communication_budget_used": float(self.communication_used),
            "ego_steps": float(self.ego_steps),
        }
