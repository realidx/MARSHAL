"""ROLL adapter for the dependency-free Pivotal Query game."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..base import BaseDiscreteActionEnv
from .config import PivotalQueryConfig
from .game import PivotalQueryGame
from .generator import generate_instance


class PivotalQueryEnv(BaseDiscreteActionEnv):
    def __init__(self, config: Optional[PivotalQueryConfig] = None):
        self.config = config or PivotalQueryConfig()
        self.render_mode = self.config.render_mode
        self.built_in_opponent = self.config.built_in_opponent
        self.opponent_player = self.config.opponent_player
        self.include_opponent_turn = self.config.include_opponent_turn
        if self.built_in_opponent != "oracle":
            raise ValueError("Pivotal Query v1 requires built_in_opponent='oracle'")
        if self.opponent_player != 1:
            raise ValueError("Pivotal Query v1 requires opponent_player=1")
        if self.config.max_queries < 3:
            raise ValueError("Pivotal Query v1 requires max_queries >= 3 for exact planning")
        self.game: Optional[PivotalQueryGame] = None
        self.episode_seed: Optional[int] = None
        super().__init__()

    @property
    def current_player(self) -> int:
        return 0

    def reset(self, seed: Optional[int] = 0):
        self.episode_seed = int(0 if seed is None else seed) + int(self.config.seed_offset)
        instance = generate_instance(
            self.episode_seed,
            self.config.condition,
            self.config,
        )
        self.game = PivotalQueryGame(instance, max_queries=self.config.max_queries)
        return {
            "observation": self.render(),
            "legal_actions": self.get_all_actions(),
        }, []

    def step(self, action):
        if self.game is None:
            raise RuntimeError("reset Pivotal Query before stepping")
        action_text = self._action_to_string(action) if isinstance(action, int) else action.strip()
        partner_message, reward, done, info = self.game.step(action_text)
        if done:
            info.update(self._terminal_protocol_info())
        observation = f"{partner_message}\n\n{self.render()}"
        return [
            {
                "current_player": 0,
                "action": action_text,
                "rewards": [reward, 0.0],
                "done": done,
                "info": info,
                "next_player": None if done else 0,
                "observation": observation,
                "legal_actions": None if done else self.get_all_actions(),
            }
        ]

    def get_all_actions(self) -> Dict[int, str]:
        if self.game is None:
            return {}
        canonical = tuple(
            [f"ASK {partner} {fact}" for partner, fact in self.game.instance.all_queries()]
            + [f"ACT {option}" for option in self.game.instance.option_names]
        )
        legal = set(self.game.legal_actions())
        return {index: action for index, action in enumerate(canonical) if action in legal}

    def _action_to_string(self, action: int) -> str:
        try:
            return self.get_all_actions()[action]
        except KeyError as exc:
            raise ValueError(f"illegal Pivotal Query action id {action!r}") from exc

    def _string_to_action(self, action: str) -> int:
        for action_id, text in self.get_all_actions().items():
            if action.strip() == text:
                return action_id
        raise ValueError(f"illegal Pivotal Query action {action!r}")

    def recover_action(self, response: str, legal_actions: Dict[int, str]) -> Optional[str]:
        match = re.fullmatch(
            r"\s*(?:<reason>.*?</reason>\s*)?<answer>\s*((?:ASK\s+[A-Za-z][A-Za-z0-9_-]*\s+[A-Za-z][A-Za-z0-9_-]*|ACT\s+[A-Za-z][A-Za-z0-9_-]*))\s*</answer>\s*",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            return None
        candidate = " ".join(match.group(1).split())
        canonical = {action.lower(): action for action in legal_actions.values()}
        return canonical.get(candidate.lower())

    def get_prompt(self, mode="prefix", think=True, player_id=0):
        del think, player_id
        if mode != "prefix":
            raise ValueError(f"invalid prompt mode {mode!r}")
        decision_hint = (
            " Unknown information need not be worth acquiring: ask only when its "
            "expected decision value exceeds its cost."
            if self.config.decision_rule_hint
            else ""
        )
        return {
            "system": "You make decisions under uncertainty in the Pivotal Query Game.",
            "user": (
                "Your objective is to maximize expected total payoff. At every turn, "
                "choose exactly one legal action. ACT selects a final option and ends "
                "the episode. ASK names one partner and one fact. Every partner is "
                "cooperative and truthful, but each knows only the facts listed in their "
                "profile; a partner asked about another fact replies that they do not know. "
                "The listed communication cost is deducted immediately, and you may then "
                f"decide again.{decision_hint}\n\n"
                "Output exactly:\n"
                "<answer>ASK PARTNER FACT</answer>\n"
                "or\n"
                "<answer>ACT OPTION</answer>\n\n"
                "Do not output anything else. A malformed or illegal response ends the episode."
            ),
        }

    def format_turn_prompt(self, state, legal_actions, player_id=0):
        del player_id
        return f"\n\n{state}\n\nLegal actions: {', '.join((legal_actions or {}).values())}"

    def render(self, mode: str = "text"):
        if self.game is None:
            return "Pivotal Query game is not initialized."
        if mode not in ("text", "rgb_array"):
            raise ValueError(f"invalid render mode {mode!r}")
        instance = self.game.instance
        known = ", ".join(f"{fact}={value}" for fact, value in self.game.known.items()) or "none"
        costs = (
            ", ".join(
                f"ASK {partner} {fact}: {instance.query_cost(partner, fact):g}"
                for partner, fact in self.game.available_queries()
            )
            or "no remaining queries"
        )
        profiles = ", ".join(
            f"{partner} knows {', '.join(knowledge)}"
            for partner, knowledge in zip(instance.partner_names, instance.partner_knowledge)
        )
        header = " | ".join([*instance.fact_names, "probability", *instance.option_names])
        rows = []
        for world in instance.worlds:
            rows.append(
                " | ".join(
                    [
                        *world.values,
                        f"{world.probability:g}",
                        *(f"{payoff:g}" for payoff in world.payoffs),
                    ]
                )
            )
        return (
            f"Known facts: {known}\n"
            f"Partner knowledge profiles: {profiles}.\n"
            f"Query costs: {costs}\n\n"
            f"Payoff and prior table:\n{header}\n" + "\n".join(rows)
        )

    def get_retry_state(self, player_id: int = 0, hit_token_limit: bool = False):
        correction = (
            "Your previous response reached the generation limit."
            if hit_token_limit
            else "Your previous response did not contain exactly one legal action."
        )
        return [
            {
                "current_player": player_id,
                "action": "",
                "rewards": [0.0, 0.0],
                "done": False,
                "info": {"retry_attempt": 1.0, "game_transition": 0.0},
                "next_player": player_id,
                "observation": f"{correction} The state has not changed.\n\n{self.render()}",
                "legal_actions": self.get_all_actions(),
            }
        ]

    def get_losing_state(
        self,
        player_id: int = 0,
        overlong_response: bool = False,
        overlong_sequence: bool = False,
    ):
        info: Dict[str, Any] = {
            "success": False,
            "artificial_truncation": 1.0,
            "game_transition": 0.0,
            "player_0_return": self.game.total_reward if self.game else 0.0,
            "player_1_return": 0.0,
            "winner": -1,
            "player_0_success": False,
            "player_1_success": False,
            "draw": False,
            "player_0_lose_for_wrong_format": int(player_id == 0),
            "player_1_lose_for_wrong_format": int(player_id == 1),
            "player_0_lose_for_overlong_response": int(player_id == 0 and overlong_response),
            "player_1_lose_for_overlong_response": int(player_id == 1 and overlong_response),
            "player_0_lose_for_overlong_sequence": int(player_id == 0 and overlong_sequence),
            "player_1_lose_for_overlong_sequence": int(player_id == 1 and overlong_sequence),
        }
        return [
            {
                "current_player": player_id,
                "action": "",
                "rewards": [0.0, 0.0],
                "done": True,
                "info": info,
                "next_player": None,
                "observation": None,
                "legal_actions": None,
            }
        ]

    def _terminal_protocol_info(self) -> Dict[str, Any]:
        assert self.game is not None
        optimal = bool(self.game.records and self.game.records[-1]["optimal_action"])
        return {
            "player_0_return": self.game.total_reward,
            "player_1_return": 0.0,
            "winner": 0 if optimal else -1,
            "player_0_success": optimal,
            "player_1_success": False,
            "draw": False,
            "player_0_lose_for_wrong_format": 0,
            "player_1_lose_for_wrong_format": 0,
            "player_0_lose_for_overlong_response": 0,
            "player_1_lose_for_overlong_response": 0,
            "player_0_lose_for_overlong_sequence": 0,
            "player_1_lose_for_overlong_sequence": 0,
        }

    def close(self):
        return None
