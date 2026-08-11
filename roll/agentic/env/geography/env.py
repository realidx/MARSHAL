"""MARSHAL adapter for procedural DAG Vertex Geography."""

from __future__ import annotations

import random
import re
from typing import Any, Dict, Optional

from ..base import BaseDiscreteActionEnv

from .config import GeographyConfig
from .graph import (
    GeographyState,
    GraphProperties,
    generate_geography_graph,
)
from .solver import GeographySolution


class GeographyEnv(BaseDiscreteActionEnv):
    def __init__(self, config: GeographyConfig = GeographyConfig()):
        self.config = config
        self.render_mode = config.render_mode
        self.built_in_opponent = config.built_in_opponent
        self.opponent_player = config.opponent_player
        self.include_opponent_turn = config.include_opponent_turn
        self.reward_mode = config.reward_mode
        self.decision_local_reward = self.reward_mode == "counterfactual"
        if self.built_in_opponent not in ("none", "random", "optimal"):
            raise ValueError("built_in_opponent must be 'none', 'random', or 'optimal'")
        if self.opponent_player not in (0, 1):
            raise ValueError("opponent_player must be zero or one")
        if config.starting_player not in (0, 1):
            raise ValueError("starting_player must be zero or one")
        if self.reward_mode not in ("environment", "counterfactual"):
            raise ValueError("reward_mode must be 'environment' or 'counterfactual'")
        if config.game_step_discount != 1.0:
            raise ValueError("Geography v1 requires game_step_discount=1.0")
        self.state: Optional[GeographyState] = None
        self.solution: Optional[GeographySolution] = None
        self.properties: Optional[GraphProperties] = None
        self._rng = random.Random(config.seed)
        super().__init__()

    @property
    def current_player(self) -> int:
        return self.state.current_player() if self.state is not None else 0

    def reset(self, seed: Optional[int] = 0):
        episode_seed = int(0 if seed is None else seed) + int(self.config.seed_offset)
        if self.config.seed_namespace:
            if self.config.seed_namespace < 0 or episode_seed < 0:
                raise ValueError("Geography seed namespaces and episode seeds must be nonnegative")
            episode_seed = (int(self.config.seed_namespace) << 64) | episode_seed
        graph_seed = (
            episode_seed
            if self.config.fixed_graph_seed is None
            else int(self.config.fixed_graph_seed)
        )
        graph, self.solution, self.properties = generate_geography_graph(
            seed=graph_seed,
            num_nodes=self.config.num_nodes,
            min_depth=self.config.min_depth,
            max_depth=self.config.max_depth,
            min_branching=self.config.min_branching,
            max_branching=self.config.max_branching,
            transposition_rate=self.config.transposition_rate,
            target_root_value=self.config.target_root_value,
            target_root_informative=self.config.target_root_informative,
            target_root_optimal_distance=self.config.target_root_optimal_distance,
            target_root_branching=self.config.target_root_branching,
            target_informative_fraction=self.config.target_informative_fraction,
            candidate_count=self.config.generator_candidates,
        )
        if self.config.relabel_seed_offset:
            graph = graph.relabel(graph_seed + int(self.config.relabel_seed_offset))
        self.state = GeographyState(
            graph=graph,
            current_node=graph.start_node,
            player_to_act=self.config.starting_player,
        )
        self._rng = random.Random(episode_seed)
        initial_observation = {
            "observation": self.render(),
            "legal_actions": self.get_all_actions(),
        }
        execute_results = []
        done = self.state.is_terminal()
        while self.built_in_opponent != "none" and self.current_player == self.opponent_player and not done:
            acting_player = self.current_player
            action = self._opponent_step()
            observation, rewards, done, info = self._step(action)
            execute_results.append(
                self._transition_record(acting_player, action, observation, rewards, done, info)
            )
        return initial_observation, execute_results

    def step(self, action):
        if self.state is None:
            raise RuntimeError("Reset Geography before stepping")
        execute_results = []
        acting_player = self.current_player
        action_node = self._string_to_action(action) if isinstance(action, str) else int(action)
        observation, rewards, done, info = self._step(action_node)
        execute_results.append(
            self._transition_record(acting_player, action_node, observation, rewards, done, info)
        )
        while self.built_in_opponent != "none" and self.current_player == self.opponent_player and not done:
            acting_player = self.current_player
            opponent_action = self._opponent_step()
            observation, rewards, done, info = self._step(opponent_action)
            execute_results.append(
                self._transition_record(
                    acting_player, opponent_action, observation, rewards, done, info
                )
            )
        return execute_results

    def _step(self, action: int):
        if self.state is None or self.solution is None or self.properties is None:
            raise RuntimeError("Reset Geography before stepping")
        if self.state.is_terminal():
            raise RuntimeError("Cannot act from a terminal Geography node")

        acting_player = self.current_player
        before_node = self.state.current_node
        action_values = self.solution.action_values(before_node)
        if action not in action_values:
            raise ValueError(f"Illegal Geography action {action!r}")
        baseline = sum(action_values.values()) / len(action_values)
        chosen_q = action_values[action]
        advantage = chosen_q - baseline
        spread = self.solution.decision_spreads[before_node]
        value_loss = self.solution.regret(before_node, action)
        normalized_regret = value_loss / spread if spread > 0 else 0.0

        self.state = self.state.apply_action(action)
        reached_terminal = self.state.is_terminal()
        done = reached_terminal or self.config.root_decision_only
        canonical_rewards = [0.0, 0.0]
        if reached_terminal:
            canonical_rewards[acting_player] = 1.0
            canonical_rewards[1 - acting_player] = -1.0
        elif self.config.root_decision_only:
            # Q(s, a) is the exact game outcome for the acting player when both
            # players continue optimally. It lets a rollout evaluate one root
            # decision without asking the model to play the rest of the game.
            canonical_rewards[acting_player] = float(chosen_q)
            canonical_rewards[1 - acting_player] = float(-chosen_q)
        counterfactual_rewards = [0.0, 0.0]
        counterfactual_rewards[acting_player] = advantage
        rewards = (
            counterfactual_rewards
            if self.reward_mode == "counterfactual"
            else canonical_rewards
        )

        info: Dict[str, Any] = {
            "game_transition": 1.0,
            "canonical_reward_player_0": canonical_rewards[0],
            "canonical_reward_player_1": canonical_rewards[1],
            "counterfactual_reward_player_0": counterfactual_rewards[0],
            "counterfactual_reward_player_1": counterfactual_rewards[1],
            "counterfactual_valid_action": 1.0,
            "counterfactual_state_value": float(self.solution.value(before_node)),
            "counterfactual_chosen_q": float(chosen_q),
            "counterfactual_baseline": float(baseline),
            "counterfactual_advantage": float(advantage),
            "counterfactual_decision_spread": float(spread),
            "counterfactual_regret": float(normalized_regret),
            "counterfactual_value_loss": float(value_loss),
            "counterfactual_optimal_action": float(value_loss == 0),
            "graph_id": self.state.graph.graph_id,
            "graph_seed": str(self.state.graph.episode_seed),
            "graph_node_count": float(self.state.graph.num_nodes),
            "graph_edge_count": float(self.state.graph.num_edges),
            "graph_depth": float(self.properties.longest_depth),
            "graph_transposition_rate": float(self.properties.transposition_rate),
            "graph_mean_branching": float(self.properties.mean_branching),
            "graph_informative_fraction": float(self.properties.informative_fraction),
            "remaining_optimal_distance": float(self.solution.optimal_distances[before_node]),
            "current_out_degree": float(len(action_values)),
            "graph_current_node": self.state.graph.labels[before_node],
            "root_decision_only": float(self.config.root_decision_only),
        }
        # Compatibility aliases let the existing rollout aggregation continue
        # to work while its storage key is migrated to counterfactual records.
        info.update(
            {
                "minimax_valid_action": info["counterfactual_valid_action"],
                "minimax_value_loss": info["counterfactual_value_loss"],
                "minimax_chosen_q": info["counterfactual_chosen_q"],
                "minimax_counterfactual_baseline": info["counterfactual_baseline"],
                "minimax_counterfactual_advantage": info["counterfactual_advantage"],
                "minimax_decision_spread": info["counterfactual_decision_spread"],
                "minimax_normalized_regret": info["counterfactual_regret"],
                "minimax_optimal_action": info["counterfactual_optimal_action"],
            }
        )
        if reached_terminal:
            info.update(self._terminal_info())
        elif self.config.root_decision_only:
            info.update(self._solved_continuation_info(acting_player, chosen_q))
        return self.render(), rewards, done, info

    def _transition_record(self, player, action, observation, rewards, done, info):
        return {
            "current_player": player,
            "action": self._action_to_string(action),
            "rewards": rewards,
            "done": done,
            "info": info,
            "next_player": self.current_player,
            "observation": observation,
            "legal_actions": self.get_all_actions(),
        }

    def _opponent_step(self) -> int:
        legal = tuple(self.get_all_actions())
        if self.built_in_opponent == "random":
            return self._rng.choice(legal)
        if self.built_in_opponent == "optimal":
            assert self.state is not None and self.solution is not None
            return self._rng.choice(self.solution.optimal_actions[self.state.current_node])
        raise ValueError(f"No built-in policy for {self.built_in_opponent!r}")

    def get_all_actions(self) -> Dict[int, str]:
        if self.state is None:
            return {}
        return {
            action: self.state.graph.labels[action]
            for action in self.state.legal_actions()
        }

    def _action_to_string(self, action: int) -> str:
        if self.state is None:
            raise RuntimeError("Reset Geography before formatting actions")
        return self.state.graph.labels[action]

    def _string_to_action(self, action: str) -> int:
        if self.state is None:
            raise RuntimeError("Reset Geography before parsing actions")
        try:
            return self.state.graph.labels.index(action.strip())
        except ValueError as exc:
            raise ValueError(f"Unknown Geography node label {action!r}") from exc

    def recover_action(self, response: str, legal_actions: Dict[int, str]) -> Optional[str]:
        match = re.fullmatch(
            r"\s*<reason>.*?</reason>\s*<answer>\s*([A-Za-z][A-Za-z0-9_-]*)\s*</answer>\s*",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            return None
        candidate = match.group(1)
        return candidate if candidate in legal_actions.values() else None

    def get_prompt(self, mode="prefix", think=True, player_id=0):
        del think, player_id
        if mode != "prefix":
            raise ValueError(f"Invalid prompt mode: {mode}")
        return {
            "system": "You are playing Directed Acyclic Graph Vertex Geography.",
            "user": (
                "The players alternate moving a token along one directed edge. "
                "A player with no legal move loses. Choose one legal destination "
                "that maximizes your final game outcome. Keep your thinking "
                "process concise.\n\n"
                "Output exactly:\n"
                "<reason>your analysis</reason>\n"
                "<answer>NODE</answer>\n\n"
                "Do not output anything else. A response that does not follow "
                "this format results in immediate loss."
            ),
        }

    def format_turn_prompt(self, state, legal_actions, player_id=0):
        return (
            f"\n\nYou are Player {player_id + 1}.\n\n"
            f"{state}\n\n"
            f"Legal moves: {', '.join((legal_actions or {}).values())}"
        )

    def get_retry_state(self, player_id: int = 0, hit_token_limit: bool = False):
        if hit_token_limit:
            correction = (
                "Your previous response reached the generation limit. The graph "
                "has not changed. Choose one legal destination now."
            )
        else:
            correction = (
                "Your previous response did not contain exactly one legal node in "
                "the answer field. The graph has not changed."
            )
        info = self._zero_nontransition_info(retry=True)
        return [
            {
                "current_player": player_id,
                "action": "",
                "rewards": [0.0, 0.0],
                "done": False,
                "info": info,
                "next_player": player_id,
                "observation": f"{correction}\n\n{self.render()}",
                "legal_actions": self.get_all_actions(),
            }
        ]

    def get_losing_state(
        self,
        player_id: int = 0,
        overlong_response: bool = False,
        overlong_sequence: bool = False,
    ):
        info = self._zero_nontransition_info(retry=False)
        info.update(
            {
                "success": False,
                "player_0_return": 0.0,
                "player_1_return": 0.0,
                "winner": -1,
                "player_0_success": False,
                "player_1_success": False,
                "draw": False,
                "artificial_truncation": 1.0,
                "player_0_lose_for_wrong_format": int(player_id == 0),
                "player_1_lose_for_wrong_format": int(player_id == 1),
                "player_0_lose_for_overlong_response": int(
                    player_id == 0 and overlong_response
                ),
                "player_1_lose_for_overlong_response": int(
                    player_id == 1 and overlong_response
                ),
                "player_0_lose_for_overlong_sequence": int(
                    player_id == 0 and overlong_sequence
                ),
                "player_1_lose_for_overlong_sequence": int(
                    player_id == 1 and overlong_sequence
                ),
            }
        )
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

    def _zero_nontransition_info(self, retry: bool) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "retry_attempt": float(retry),
            "game_transition": 0.0,
            "canonical_reward_player_0": 0.0,
            "canonical_reward_player_1": 0.0,
            "counterfactual_reward_player_0": 0.0,
            "counterfactual_reward_player_1": 0.0,
            "counterfactual_valid_action": 0.0,
            "minimax_valid_action": 0.0,
        }
        # Invalid and truncated responses still occurred at a real decision
        # state. Preserve its graph/depth metadata so coverage diagnostics do
        # not silently exclude the hardest failed decisions.
        if self.state is not None and self.solution is not None and self.properties is not None:
            node = self.state.current_node
            info.update(
                {
                    "counterfactual_state_value": float(self.solution.value(node)),
                    "counterfactual_decision_spread": float(
                        self.solution.decision_spreads[node]
                    ),
                    "graph_id": self.state.graph.graph_id,
                    "graph_seed": str(self.state.graph.episode_seed),
                    "graph_node_count": float(self.state.graph.num_nodes),
                    "graph_edge_count": float(self.state.graph.num_edges),
                    "graph_depth": float(self.properties.longest_depth),
                    "graph_transposition_rate": float(
                        self.properties.transposition_rate
                    ),
                    "graph_mean_branching": float(self.properties.mean_branching),
                    "graph_informative_fraction": float(
                        self.properties.informative_fraction
                    ),
                    "remaining_optimal_distance": float(
                        self.solution.optimal_distances[node]
                    ),
                    "current_out_degree": float(
                        len(self.solution.action_values(node))
                    ),
                    "graph_current_node": self.state.graph.labels[node],
                }
            )
        return info

    def _terminal_info(self) -> Dict[str, Any]:
        assert self.state is not None and self.state.is_terminal()
        loser = self.current_player
        winner = 1 - loser
        returns = [0.0, 0.0]
        returns[winner] = 1.0
        returns[loser] = -1.0
        return {
            "success": True,
            "player_0_return": returns[0],
            "player_1_return": returns[1],
            "winner": winner,
            "player_0_success": winner == 0,
            "player_1_success": winner == 1,
            "draw": False,
            "player_0_lose_for_wrong_format": 0,
            "player_1_lose_for_wrong_format": 0,
            "player_0_lose_for_overlong_response": 0,
            "player_1_lose_for_overlong_response": 0,
            "player_0_lose_for_overlong_sequence": 0,
            "player_1_lose_for_overlong_sequence": 0,
        }

    @staticmethod
    def _solved_continuation_info(acting_player: int, chosen_q: int) -> Dict[str, Any]:
        """Terminal metadata for evaluation-only root decisions.

        The episode ends administratively after one model decision, while the
        winner and returns come from exact backward induction on the unplayed
        continuation.
        """
        winner = acting_player if chosen_q == 1 else 1 - acting_player
        returns = [0.0, 0.0]
        returns[acting_player] = float(chosen_q)
        returns[1 - acting_player] = float(-chosen_q)
        return {
            "success": True,
            "solved_continuation": 1.0,
            "player_0_return": returns[0],
            "player_1_return": returns[1],
            "winner": winner,
            "player_0_success": winner == 0,
            "player_1_success": winner == 1,
            "draw": False,
            "player_0_lose_for_wrong_format": 0,
            "player_1_lose_for_wrong_format": 0,
            "player_0_lose_for_overlong_response": 0,
            "player_1_lose_for_overlong_response": 0,
            "player_0_lose_for_overlong_sequence": 0,
            "player_1_lose_for_overlong_sequence": 0,
        }

    def render(self, mode: str = "text"):
        if self.state is None:
            return "Geography graph is not initialized."
        if mode not in ("text", "rgb_array"):
            raise ValueError(f"Invalid render mode: {mode}")
        return (
            f"Current node: {self.state.graph.labels[self.state.current_node]}\n\n"
            f"Directed graph:\n{self.state.render()}"
        )

    def close(self):
        return None
