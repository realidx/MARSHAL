"""ROLL adapter for the strict one-query Hidden Choice game."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..base import BaseDiscreteActionEnv
from .config import HiddenChoiceConfig
from .game import HiddenChoiceGame
from .generator import generate_instance
from .observation import generate_observation


class HiddenChoiceEnv(BaseDiscreteActionEnv):
    def __init__(self, config: Optional[HiddenChoiceConfig] = None):
        self.config = config or HiddenChoiceConfig()
        self.render_mode = self.config.render_mode
        self.built_in_opponent = self.config.built_in_opponent
        self.opponent_player = self.config.opponent_player
        self.include_opponent_turn = self.config.include_opponent_turn
        if self.built_in_opponent != "oracle":
            raise ValueError("Hidden Choice requires built_in_opponent='oracle'")
        if self.opponent_player != 1:
            raise ValueError("Hidden Choice requires opponent_player=1")
        self.game: Optional[HiddenChoiceGame] = None
        self.episode_seed: Optional[int] = None
        super().__init__()

    @property
    def current_player(self) -> int:
        return 0

    def reset(self, seed: Optional[int] = 0):
        self.episode_seed = int(0 if seed is None else seed) + int(self.config.seed_offset)
        instance = generate_instance(self.episode_seed, self.config.condition, self.config)
        self.game = HiddenChoiceGame(instance, full_information=self.config.full_information)
        return {"observation": self.render(), "legal_actions": self.get_all_actions()}, []

    def step(self, action):
        if self.game is None:
            raise RuntimeError("reset Hidden Choice before stepping")
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
        legal = set(self.game.legal_actions())
        return {
            index: action
            for index, action in enumerate(self.game.instance.action_order)
            if action in legal
        }

    def _action_to_string(self, action: int) -> str:
        try:
            return self.get_all_actions()[action]
        except KeyError as exc:
            raise ValueError(f"illegal Hidden Choice action id {action!r}") from exc

    def _string_to_action(self, action: str) -> int:
        for action_id, text in self.get_all_actions().items():
            if action.strip() == text:
                return action_id
        raise ValueError(f"illegal Hidden Choice action {action!r}")

    def recover_action(self, response: str, legal_actions: Dict[int, str]) -> Optional[str]:
        # Diagnostic protocol: the model must emit `<answer>` followed by one
        # action.  A closing `</answer>` is optional; strict envelope validity
        # is tracked separately by the rollout/preflight layer.
        match = re.search(
            r"<answer>\s*((?:ASK|ACT)\s+[A-Za-z][A-Za-z0-9_-]*)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            return None
        candidate = " ".join(match.group(1).split())
        canonical = {action.lower(): action for action in legal_actions.values()}
        return canonical.get(candidate.lower())

    def validate_response(self, response: str, legal_actions: Dict[int, str]) -> bool:
        """Validate the current protocol without requiring `</answer>`."""
        match = re.search(
            r"<answer>\s*((?:ASK|ACT)\s+[A-Za-z][A-Za-z0-9_-]*)"
            r"(?:</answer>)?\s*$",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            return False
        candidate = " ".join(match.group(1).split()).lower()
        return candidate in {action.lower() for action in legal_actions.values()}

    def get_prompt(self, mode="prefix", think=True, player_id=0):
        del think, player_id
        if mode != "prefix":
            raise ValueError(f"invalid prompt mode {mode!r}")
        return {
            "system": "You are playing a decision-making game with another agent.",
            "user": (
                "At each decision point, choose exactly one listed legal action.\n\n"
                "ACT <option> chooses that option as the final action and ends the episode.\n"
                "ASK <fact> asks the truthful partner to reveal that fact. ASK incurs the "
                "listed communication cost. After receiving the answer, you will make one "
                "final ACT decision.\n\n"
                "Your objective is to maximize expected total utility, including communication cost.\n\n"
                "Reason carefully, then finish with <answer> followed immediately by "
                "exactly one listed legal action, such as <answer>ACT X."
            ),
        }

    def format_turn_prompt(self, state, legal_actions, player_id=0):
        del player_id
        return f"\n\n{state}\n\nLegal actions: {', '.join((legal_actions or {}).values())}"

    def render(self, mode: str = "text"):
        if self.game is None:
            return "Hidden Choice game is not initialized."
        if mode not in ("text", "rgb_array"):
            raise ValueError(f"invalid render mode {mode!r}")
        instance = self.game.instance
        observation = generate_observation(
            instance,
            known=self.game.known,
            allow_questions=not self.game.query_used,
            full_information=self.game.full_information,
        )
        context = ", ".join(f"{name}={value}" for name, value in observation.context)
        known = ", ".join(f"{fact}={value}" for fact, value in observation.known_facts) or "none"
        available_facts = (
            ", ".join(fact for _, fact in observation.available_questions)
            if observation.available_questions
            else "none"
        )
        header = " | ".join([*instance.fact_names, "probability", *instance.option_names])
        rows = [
            " | ".join(
                [
                    *world.hidden_values,
                    f"{world.probability:g}",
                    *(f"{utility:g}" for utility in world.utilities),
                ]
            )
            for world in instance.worlds
        ]
        return (
            f"Observed context: {context}\n"
            f"Known hidden facts: {known}\n"
            f"Askable facts: {available_facts}\n"
            f"Information mode: {'full' if observation.full_information else 'hidden'}\n"
            f"Communication cost: {instance.communication_cost:g}\n\n"
            f"Possible-world utility table:\n{header}\n" + "\n".join(rows)
        )

    def get_retry_state(self, player_id: int = 0, hit_token_limit: bool = False):
        correction = (
            "Your previous response reached the generation limit."
            if hit_token_limit
            else "Your previous response did not contain exactly one listed legal action."
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

    def handle_invalid_response(
        self,
        player_id: int = 0,
        actions=None,
        raw_response: str = "",
        overlong_response: bool = False,
        overlong_sequence: bool = False,
    ):
        del raw_response
        if (
            self.game is None
            or self.game.done
            or not self.game.query_used
            or overlong_response
            or overlong_sequence
        ):
            return None
        parsed_actions = list(actions or ())
        if len(parsed_actions) != 1:
            return None
        attempted_action = " ".join(str(parsed_actions[0]).split())
        if re.fullmatch(r"ASK\s+[A-Za-z][A-Za-z0-9_-]*", attempted_action, re.IGNORECASE) is None:
            return None
        if any(action.startswith("ASK ") for action in self.game.legal_actions()):
            return None

        info = self.game.terminal_metrics(stopping_failure=True)
        info.update(
            {
                "administrative_terminal": 1.0,
                "policy_failure": 1.0,
                "ask_after_single_query": 1.0,
                "game_transition": 1.0,
                **self._protocol_outcome(benchmark_success=False),
            }
        )
        self.game.done = True
        return [
            {
                "current_player": player_id,
                "action": attempted_action,
                "rewards": [0.0, 0.0],
                "done": True,
                "info": info,
                "next_player": None,
                "observation": None,
                "legal_actions": None,
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

    def _protocol_outcome(self, benchmark_success: bool) -> Dict[str, Any]:
        assert self.game is not None
        return {
            "player_0_return": self.game.total_reward,
            "player_1_return": 0.0,
            "winner": 0 if benchmark_success else -1,
            "player_0_success": benchmark_success,
            "player_1_success": False,
            "draw": False,
            "player_0_lose_for_wrong_format": 0,
            "player_1_lose_for_wrong_format": 0,
            "player_0_lose_for_overlong_response": 0,
            "player_1_lose_for_overlong_response": 0,
            "player_0_lose_for_overlong_sequence": 0,
            "player_1_lose_for_overlong_sequence": 0,
        }

    def _terminal_protocol_info(self) -> Dict[str, Any]:
        assert self.game is not None
        return self._protocol_outcome(
            benchmark_success=bool(self.game.terminal_metrics()["benchmark_success"])
        )

    def close(self):
        return None
