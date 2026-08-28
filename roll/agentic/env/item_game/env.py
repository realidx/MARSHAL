"""ROLL adapter for the ego-centric sequential Item Coalition Game."""

from __future__ import annotations

import re
from typing import Optional

from ..base import BaseLanguageBasedEnv
from .config import ItemGameConfig
from .game import BaseItemGame
from .generator import generate_instance


class ItemGameEnv(BaseLanguageBasedEnv):
    def __init__(self, config: Optional[ItemGameConfig] = None):
        self.config = config or ItemGameConfig()
        self.render_mode = self.config.render_mode
        self.built_in_opponent = self.config.built_in_opponent
        self.opponent_player = self.config.opponent_player
        self.include_opponent_turn = self.config.include_opponent_turn
        if self.config.built_in_opponent != "oracle":
            raise ValueError("Item Game requires built_in_opponent='oracle'")
        if self.config.opponent_player != 1:
            raise ValueError("Item Game requires opponent_player=1")
        self.game: BaseItemGame | None = None
        self.episode_seed: int | None = None
        super().__init__()

    @property
    def current_player(self) -> int:
        return 0

    def reset(self, seed: Optional[int] = 0):
        self.episode_seed = int(0 if seed is None else seed) + self.config.seed_offset
        instance = generate_instance(self.episode_seed, config=self.config)
        self.game = BaseItemGame(instance, self.config)
        initial = {"observation": self.render(), "legal_actions": self.get_all_actions()}
        return initial, []

    def step(self, action):
        if self.game is None:
            raise RuntimeError("reset Item Game before stepping")
        action_text = self._action_to_string(action) if isinstance(action, int) else str(action).strip()
        partner_message, reward, done, info = self.game.step(action_text)
        info.update({"generator": self.game.instance.generator, "subtype": self.game.instance.subtype})
        if done:
            info.update(self._terminal_protocol_info())
        return [{
            "current_player": 0,
            "action": action_text,
            # Keep the two-player container expected by the rollout runtime;
            # only Ego has a benchmark reward in this environment.
            "rewards": [reward, 0.0],
            "done": done,
            "info": info,
            "next_player": None if done else 0,
            "observation": f"{partner_message}\n\n{self.render()}",
            "legal_actions": None if done else self.get_all_actions(),
        }]

    def get_all_actions(self) -> dict[int, str]:
        if self.game is None:
            return {}
        return {index: action for index, action in enumerate(self.game.legal_actions())}

    def _action_to_string(self, action: int) -> str:
        try:
            return self.get_all_actions()[action]
        except KeyError as exc:
            raise ValueError(f"illegal Item Game action id {action!r}") from exc

    def recover_action(self, response: str, legal_actions: dict[int, str]) -> str | None:
        match = re.search(r"<answer>\s*(.*?)\s*(?:</answer>|$)", response, re.DOTALL | re.IGNORECASE)
        if match is None:
            return None
        candidate = " ".join(match.group(1).split())
        candidate = self._normalize_set_spacing(candidate)
        canonical = {action.lower(): action for action in legal_actions.values()}
        return canonical.get(candidate.lower())

    def validate_response(self, response: str, legal_actions: dict[int, str]) -> bool:
        match = re.search(
            r"\s*(?:<reason>.*?</reason>\s*)?<answer>\s*(.*?)\s*</answer>\s*$",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            return False
        candidate = " ".join(match.group(1).split()).lower()
        candidate = self._normalize_set_spacing(candidate)
        return candidate in {action.lower() for action in legal_actions.values()}

    @staticmethod
    def _normalize_set_spacing(action: str) -> str:
        """Normalize optional whitespace in flat brace-delimited sets.

        The environment emits canonical sets such as ``{item_K,item_M}``,
        but models commonly return ``{item_K, item_M}``.  This is a formatting
        difference, not a different structured action, so normalize it before
        comparing a response with the legal-action table.
        """

        def normalize(match: re.Match[str]) -> str:
            values = [value.strip() for value in match.group(1).split(",") if value.strip()]
            return "{" + ",".join(values) + "}"

        return re.sub(r"\{([^{}]*)\}", normalize, action)

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
        if self.config.generator == "pure_collaboration" or self.config.subtype == "collaboration":
            return self._collaboration_prompt(output_format)
        if self.config.subtype == "respond_to_give_request":
            return self._give_request_prompt(output_format)
        if self.config.subtype == "request_surplus_reroute":
            return self._reroute_prompt(output_format)
        system = (
            "You are the EGO in a sequential Item Coalition Game. Use only the listed structured actions. "
            "ASK and ordinary SAY consume communication budget; a mandatory response to a partner request does not. "
            "ASK creates agreements; a partner that agrees to GIVE immediately performs that scripted transfer, while "
            "Ego-side GIVE still requires a later ACT. Terminal reward is 1 only when your committed pool "
            "satisfies your goal and every accepted agreement is fulfilled. "
        )
        user = (
            "Turn lifecycle:\n"
            "(1) If Partner initiated an event is shown, this is a response-only turn: output exactly SAY CAN_GIVE or SAY CANNOT_GIVE; ACT is illegal.\n"
            "(2) Otherwise EGO chooses exactly one autonomous ASK, SAY, or ACT action.\n"
            "(3) The scripted partner emits its truthful response/action.\n"
            "(4) Only after that partner phase are holdings and commitments updated.\n\n"
            "At every turn choose exactly one legal action. The available structured protocol is:\n"
            "ASK <partner> GOAL | ASK <partner> HOLDINGS | ASK <partner> GIVE <item> | "
            "ASK <partner> EXCHANGE give=<item> receive=<item> | ASK <partner> JOIN <coalition>\n"
            "SAY <partner> CAN_GIVE <item> | SAY <partner> CANNOT_GIVE <item> | "
            "SAY <partner> PROFILE goal=<...> holdings=<...>\n"
            "ACT GIVE <item> TO <partner> | ACT JOIN_COMMIT <coalition>\n\n"
            "ASK GIVE, ASK EXCHANGE, and ASK JOIN form agreements only after AGREE; ASK GIVE then immediately "
            "runs the partner's scripted ACT GIVE in the same transition. Do not output the partner's action. "
            "ASK EXCHANGE: execute it with ACT GIVE "
            "for your item, after which the partner gives the agreed receive item. "
            "If a partner asks EGO to GIVE an item, the current turn is response-only: SAY CAN_GIVE or SAY CANNOT_GIVE. "
            "CAN_GIVE forms an agreement but does not transfer the item; follow it on a later turn with ACT GIVE. "
            "A JOIN agreement is not a commit: every listed partner must agree, then output the exact same "
            "ACT JOIN_COMMIT coalition. An accepted but unfulfilled agreement makes terminal reward 0. "
            "The episode ends at JOIN_COMMIT or after eight Ego steps.\n\n"
            + output_format
        )
        return {"system": system, "user": user}

    @staticmethod
    def _collaboration_prompt(output_format: str) -> dict[str, str]:
        return {
            "system": (
                "You are EGO in a decentralized Collaboration game. Use only the listed structured actions. "
                "You initially know only your own goal and holdings; P1's goal, holdings, and alignment are unknown. "
                "QUERY, INFORM, and PROPOSE consume communication budget. ACCEPT, REJECT, and COMMIT are scripted "
                "or binding actions and do not consume communication budget."
            ),
            "user": (
                "At every turn choose exactly one legal action. If P1 asks for your GOAL or HOLDINGS, this is a "
                "mandatory response-only turn: output exactly the matching INFORM P1 action. Otherwise choose one "
                "QUERY, INFORM, PROPOSE, or (after P1 accepts JOIN) ACT COMMIT action.\n\n"
                "Protocol:\n"
                "QUERY P1 GOAL | QUERY P1 HOLDINGS\n"
                "INFORM P1 GOAL {<your goal>} | INFORM P1 HOLDINGS {<your holdings>}\n"
                "PROPOSE JOIN {EGO,P1}\n"
                "ACT COMMIT {<items from your holdings>}\n\n"
                "P1 processes a JOIN proposal immediately. If P1 lacks your goal or holdings, P1 asks you for the "
                "missing information; answer with the corresponding INFORM action. P1 then emits ACT ACCEPT or "
                "ACT REJECT. ACCEPT forms the coalition but does not commit items and does not end the episode. "
                "After acceptance, commit only items you actually hold. P1 then commits its own items. The coalition "
                "succeeds when the union of committed items covers the shared goal. Extra committed items are allowed "
                "but receive a small efficiency penalty.\n\n"
                + output_format
            ),
        }

    @staticmethod
    def _reroute_prompt(output_format: str) -> dict[str, str]:
        return {
            "system": (
                "You are EGO in a three-agent mixed-incentive rerouting game. Use only the listed structured actions. "
                "You initially know only your own goal and holdings; P1 and P2 roles, goals, holdings, and willingness "
                "to help are unknown. QUERY, INFORM, and PROPOSE consume communication budget. ACCEPT, REJECT, GIVE, "
                "and COMMIT are scripted or binding actions and do not consume communication budget."
            ),
            "user": (
                "At every turn choose exactly one legal action. QUERY a partner's GOAL or HOLDINGS to learn only that "
                "partner's publicly available state. You may propose a GIVE to either partner. The partner immediately "
                "responds with ACT ACCEPT or ACT REJECT; after ACCEPT, that same partner immediately performs ACT GIVE. "
                "A rejection is new information: continue with the other partner rather than treating the episode as over.\n\n"
                "Protocol:\n"
                "QUERY P1 GOAL | QUERY P1 HOLDINGS | QUERY P2 GOAL | QUERY P2 HOLDINGS\n"
                "INFORM P1 GOAL {...} | INFORM P1 HOLDINGS {...} | INFORM P2 GOAL {...} | INFORM P2 HOLDINGS {...}\n"
                "PROPOSE GIVE {giver=P1,receiver=EGO,items={...}} | PROPOSE GIVE {giver=P2,receiver=EGO,items={...}}\n"
                "ACT COMMIT {...}\n\n"
                "There is exactly one missing Ego goal item. Use a partner's disclosed goal and holdings to determine "
                "whether giving that item would prevent the partner from satisfying its own goal. If the partner rejects "
                "a proposal, update your strategy and query or propose to the other partner. After receiving the missing "
                "item, commit your own held items that cover your goal. Extra committed items remain valid but receive "
                "a small efficiency penalty.\n\n"
                + output_format
            ),
        }

    @staticmethod
    def _give_request_prompt(output_format: str) -> dict[str, str]:
        return {
            "system": (
                "You are EGO in a two-agent Give Request game. Use only the listed structured actions. "
                "The active partner has requested one item from your holdings. You must decide whether giving it "
                "would preserve or damage your own goal. ACCEPT and REJECT are binding decisions; ACCEPT does not "
                "transfer the item."
            ),
            "user": (
                "Turn lifecycle:\n"
                "(1) The active partner first emits one GIVE proposal.\n"
                "(2) On the next Ego turn, output exactly ACT ACCEPT or ACT REJECT.\n"
                "(3) ACCEPT records an agreement but does not change holdings; on the following turn you must output "
                "the exact ACT GIVE item set from that proposal.\n"
                "(4) REJECT clears the proposal and does not change holdings.\n"
                "(5) After the interaction is resolved, output ACT COMMIT with items you still hold.\n\n"
                "The partner proposal is shown in the form PROPOSE GIVE {giver: EGO, receiver: <partner>, "
                "items: {<item>}}. The requested item is a partner goal item.\n\n"
                "Protocol:\n"
                "ACT ACCEPT | ACT REJECT | ACT GIVE {<exact requested item>} | ACT COMMIT {<items from your holdings>}\n\n"
                "The requested item is critical to the partner's goal. If it is surplus for your own goal, the safe "
                "response is ACCEPT followed by the exact ACT GIVE. If it is critical to your own goal, REJECT and "
                "keep it. There is no reciprocity or exchange mechanism in this environment. An accepted proposal "
                "that is not fulfilled is not a completed interaction and cannot receive terminal success. The main "
                "reward is based on whether your committed holdings satisfy your own goal.\n\n"
                + output_format
            ),
        }

    def format_turn_prompt(self, state, legal_actions, player_id=0):
        del player_id
        return f"\n\n{state}\n\nLegal actions: {', '.join((legal_actions or {}).values())}"

    def render(self, mode: str = "text"):
        if self.game is None:
            return "Item Game is not initialized."
        if mode not in ("text", "rgb_array"):
            raise ValueError(f"invalid render mode {mode!r}")
        g = self.game
        if g.respond_to_give_request:
            lines = [
                f"Generator: {g.instance.generator}/respond_to_give_request",
                f"EGO goal: {g._format_set(g.goals['EGO'])}",
                f"EGO holdings: {g._format_set(g.holdings['EGO'])}",
                f"Turn phase: {g.turn_phase}",
                f"Ego steps: {g.ego_steps}/{g.config.max_ego_steps}",
            ]
            if g.conversation_history:
                lines.append("Interaction history:")
                lines.extend(
                    f"- {entry['actor']} [{entry['phase']}]: {entry['action']}"
                    for entry in g.conversation_history
                )
            if g.give_request_proposal is not None:
                partner = g.give_request_proposal["receiver"]
                item = g._format_set(g.give_request_proposal["items"])
                lines.append(f"Pending proposal: PROPOSE GIVE {{giver: EGO,receiver: {partner},items: {item}}}")
            if g.give_request_accepted and not g.give_request_fulfilled:
                lines.append(
                    f"Accepted proposal: ACT GIVE {g._format_set(g.give_request_accepted_items)} is required."
                )
            if g.give_request_ego_commit is not None:
                lines.append(f"EGO committed: {g._format_set(g.give_request_ego_commit)}")
            return "\n".join(lines)
        if g.reroute:
            lines = [
                "Generator: mixed_incentive/request_surplus_reroute",
                f"EGO goal: {g._format_set(g.goals['EGO'])}",
                f"EGO holdings: {g._format_set(g.holdings['EGO'])}",
                f"Turn phase: {g.turn_phase}",
                f"Communication: {g.communication_used}/{g.config.communication_budget}; Ego steps: {g.ego_steps}/{g.config.max_ego_steps}",
                "P1/P2 roles, goals, holdings, and willingness are initially unknown to EGO.",
            ]
            if g.conversation_history:
                lines.append("Interaction history:")
                lines.extend(
                    f"- {entry['actor']} [{entry['phase']}]: {entry['action']}"
                    for entry in g.conversation_history
                )
            if g.reroute_received_item is not None:
                lines.append(f"Received item from partner: {g.reroute_received_item}")
            if g.reroute_ego_commit is not None:
                lines.append(f"EGO committed: {g._format_set(g.reroute_ego_commit)}")
            return "\n".join(lines)
        if g.collaboration:
            lines = [
                "Generator: pure_collaboration/collaboration",
                f"EGO goal: {g._format_set(g.goals['EGO'])}",
                f"EGO holdings: {g._format_set(g.holdings['EGO'])}",
                f"Turn phase: {g.turn_phase}",
                f"Communication: {g.communication_used}/{g.config.communication_budget}; Ego steps: {g.ego_steps}/{g.config.max_ego_steps}",
                "P1 goal/holdings/alignment are initially unknown to EGO.",
            ]
            if g.conversation_history:
                lines.append("Interaction history:")
                lines.extend(
                    f"- {entry['actor']} [{entry['phase']}]: {entry['action']}"
                    for entry in g.conversation_history
                )
            if g.pending_proposal is not None:
                lines.append("Pending proposal: PROPOSE JOIN {EGO,P1}")
            if g.collaboration_coalition is not None:
                lines.append("Coalition: {EGO,P1} (formed)")
            if g.collaboration_ego_commit is not None:
                lines.append(f"EGO committed: {g._format_set(g.collaboration_ego_commit)}")
            if g.collaboration_p1_commit is not None:
                lines.append(f"P1 committed: {g._format_set(g.collaboration_p1_commit)}")
            return "\n".join(lines)
        lines = [
            f"Generator: {g.instance.generator}/{g.instance.subtype}",
            f"EGO goal: {g._format_set(g.goals['EGO'])}",
            f"EGO holdings: {g._format_set(g.holdings['EGO'])}",
            f"Turn phase: {g.turn_phase}",
            f"Communication: {g.communication_used}/{g.config.communication_budget}; Ego steps: {g.ego_steps}/{g.config.max_ego_steps}",
        ]
        if g.partner_event:
            lines.append(f"Partner initiated event: {g.partner_event}")
        if g.pending_transfer:
            partner, item = g.pending_transfer
            lines.append(f"Accepted GIVE agreement: EGO must ACT GIVE {item} TO {partner}.")
        if g.pending_exchange:
            partner, give, receive = g.pending_exchange
            lines.append(
                f"Accepted exchange agreement: EGO must ACT GIVE {give} TO {partner}; "
                f"then {partner} will ACT GIVE {receive} TO EGO."
            )
        if g.agreements:
            active = []
            for agreement in g.agreements:
                if agreement.get("type") == "join":
                    label = f"JOIN {agreement['coalition']}"
                elif agreement.get("type") == "exchange":
                    label = f"EXCHANGE give={agreement['give']} receive={agreement['receive']}"
                else:
                    label = f"GIVE {agreement['item']} ({agreement['direction']})"
                status = "fulfilled" if agreement.get("fulfilled") else "accepted_unfulfilled"
                active.append(f"{label}:{status}")
            lines.append("Agreements: " + "; ".join(active))
        known_facts = {
            player: {
                key: g._format_set(value) if isinstance(value, set) else value
                for key, value in facts.items()
            }
            for player, facts in g.known.items()
            if player != "EGO"
        }
        lines.append("Known partner facts: " + repr(known_facts))
        lines.append("Partner holdings are hidden until truthfully revealed by ASK HOLDINGS.")
        return "\n".join(lines)

    def _terminal_protocol_info(self):
        """Expose the standard terminal fields without rewarding the partner."""
        assert self.game is not None
        success = bool(self.game.ego_success)
        terminal_return = self.game._terminal_reward() if success else 0.0
        return {
            "player_0_return": terminal_return,
            "player_1_return": 0.0,
            "player_0_success": success,
            "player_1_success": False,
            "winner": 0 if success else -1,
            "draw": False,
            "player_0_lose_for_wrong_format": 0,
            "player_1_lose_for_wrong_format": 0,
            "player_0_lose_for_overlong_response": 0,
            "player_1_lose_for_overlong_response": 0,
            "player_0_lose_for_overlong_sequence": 0,
            "player_1_lose_for_overlong_sequence": 0,
        }

    def get_retry_state(self, player_id: int = 0, hit_token_limit: bool = False):
        correction = "Your previous response reached the generation limit." if hit_token_limit else "Your previous response was not one listed action."
        return [{"current_player": player_id, "action": "", "rewards": [0.0, 0.0], "done": False, "info": {"retry_attempt": 1.0, "game_transition": 0.0}, "next_player": player_id, "observation": f"{correction}\n\n{self.render()}", "legal_actions": self.get_all_actions()}]

    def get_losing_state(
        self,
        player_id: int = 0,
        overlong_response: bool = False,
        overlong_sequence: bool = False,
    ):
        """Close an invalid model response; Collaboration applies its small invalid-action penalty."""
        invalid_reward = (
            BaseItemGame._COLLAB_INVALID_ACTION_PENALTY
            if self.game is not None and (
                self.game.collaboration or self.game.reroute or self.game.respond_to_give_request
            )
            else 0.0
        )
        info = {
            "success": False,
            "artificial_truncation": 1.0,
            "game_transition": 0.0,
            "canonical_reward_player_0": invalid_reward,
            "canonical_reward_player_1": 0.0,
            "player_0_return": invalid_reward,
            "player_1_return": 0.0,
            "player_0_success": False,
            "player_1_success": False,
            "winner": -1,
            "draw": False,
            "player_0_lose_for_wrong_format": int(player_id == 0),
            "player_1_lose_for_wrong_format": int(player_id == 1),
            "player_0_lose_for_overlong_response": int(player_id == 0 and overlong_response),
            "player_1_lose_for_overlong_response": int(player_id == 1 and overlong_response),
            "player_0_lose_for_overlong_sequence": int(player_id == 0 and overlong_sequence),
            "player_1_lose_for_overlong_sequence": int(player_id == 1 and overlong_sequence),
        }
        return [{
            "current_player": player_id,
            "action": "",
            "rewards": [invalid_reward, 0.0],
            "done": True,
            "info": info,
            "next_player": None,
            "observation": None,
            "legal_actions": None,
        }]
