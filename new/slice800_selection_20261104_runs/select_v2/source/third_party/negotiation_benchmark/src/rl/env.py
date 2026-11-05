"""
Gym-style RL wrapper for negotiation games.

This environment is an adapter on top of the existing negotiation engine. It
does not modify transition semantics: state changes still happen exclusively
through ``play_deal()`` and ``reject_deal()`` on ``NegotiationState``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:  # pragma: no cover - fallback for local usage without gymnasium
    class _FallbackEnv:
        metadata = {}

        def reset(self, *, seed=None):
            self._seed = seed

    class _FallbackSpace:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FallbackBox(_FallbackSpace):
        def __init__(self, low, high, shape, dtype):
            super().__init__(low=low, high=high, shape=shape, dtype=dtype)

    class _FallbackDiscrete(_FallbackSpace):
        def __init__(self, n):
            super().__init__(n=n)

    class _FallbackDict(_FallbackSpace):
        def __init__(self, spaces_dict):
            super().__init__(spaces=spaces_dict)

        def __getitem__(self, key):
            return self.spaces[key]

    class _FallbackSpaces:
        Box = _FallbackBox
        Dict = _FallbackDict
        Discrete = _FallbackDiscrete

    class _FallbackGym:
        Env = _FallbackEnv

    gym = _FallbackGym()
    spaces = _FallbackSpaces()
from core.game_state import NegotiationState
from rl.action_space import build_offer_menu, build_partner_mask
from rl.observation import OFFER_SELECTION_STAGE, PARTNER_SELECTION_STAGE, encode_observation
from rl.rewards import terminal_reward_for_actor


@dataclass
class PendingPartnerChoice:
    """Partner selection held between the two subdecisions of one turn."""

    partner_id: int


class NegotiationTurnEnv(gym.Env):
    """
    Turn-based negotiation env with masked partner and offer subdecisions.

    One environment step corresponds to exactly one subdecision:
    - partner selection
    - offer selection

    Offer selection includes an explicit no-deal action that maps to
    ``reject_deal()``.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        max_players: int,
        max_actions: int,
        max_candidate_offers: int = 1024,
        max_changes: int = 2,
        max_goal_slots: int | None = None,
        allow_self_partner: bool = False,
        allowed_actions=None,
        forbidden_actions=None,
        game_config: dict | None = None,
        sat_masks: dict | None = None,
        reward_fn=terminal_reward_for_actor,
    ):
        self.max_players = max_players
        self.max_actions = max_actions
        self.max_candidate_offers = max_candidate_offers
        self.max_changes = max_changes
        self.max_goal_slots = max_goal_slots
        self.allow_self_partner = allow_self_partner
        self.allowed_actions = allowed_actions
        self.forbidden_actions = forbidden_actions
        self.default_game_config = game_config
        self.default_sat_masks = sat_masks
        self.reward_fn = reward_fn

        self.game = None
        self.stage = PARTNER_SELECTION_STAGE
        self.pending_partner = None
        self.offer_menu = None
        self._last_obs = None

        offer_width = 1 + (2 * max_actions)
        if max_goal_slots is not None:
            feature_dim = (9 * max_goal_slots) + 2
        elif sat_masks is not None:
            feature_dim = 9 * len(sat_masks) + 2
        else:
            feature_dim = 2

        self.observation_space = spaces.Dict(
            {
                "player_features": spaces.Box(
                    low=-np.inf,
                    high=np.inf,
                    shape=(max_players, feature_dim),
                    dtype=np.float32,
                ),
                "policy_matrix": spaces.Box(
                    low=0,
                    high=1,
                    shape=(max_players, max_actions),
                    dtype=np.int8,
                ),
                "payoff_vector": spaces.Box(
                    low=-np.inf,
                    high=np.inf,
                    shape=(max_players,),
                    dtype=np.float32,
                ),
                "player_active_mask": spaces.Box(
                    low=0, high=1, shape=(max_players,), dtype=np.int8
                ),
                "stage": spaces.Box(low=0, high=2, shape=(1,), dtype=np.int64),
                "acting_player": spaces.Box(
                    low=-1, high=max_players - 1, shape=(1,), dtype=np.int64
                ),
                "selected_partner": spaces.Box(
                    low=-1, high=max_players - 1, shape=(1,), dtype=np.int64
                ),
                "turn_index": spaces.Box(low=0, high=10_000, shape=(1,), dtype=np.int64),
                "turns_remaining": spaces.Box(
                    low=0, high=10_000, shape=(1,), dtype=np.int64
                ),
                "proposer_num_actions": spaces.Box(
                    low=0, high=max_actions, shape=(1,), dtype=np.int64
                ),
                "partner_num_actions": spaces.Box(
                    low=0, high=max_actions, shape=(1,), dtype=np.int64
                ),
                "partner_mask": spaces.Box(
                    low=0, high=1, shape=(max_players,), dtype=np.int8
                ),
                "offer_mask": spaces.Box(
                    low=0, high=1, shape=(max_candidate_offers,), dtype=np.int8
                ),
                "offer_actions": spaces.Box(
                    low=0,
                    high=1,
                    shape=(max_candidate_offers, offer_width),
                    dtype=np.int8,
                ),
            }
        )
        self.action_space = spaces.Discrete(max(max_players, max_candidate_offers))

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        """Reset the env around a fresh or supplied game instance."""
        super().reset(seed=seed)

        options = options or {}
        game_config = options.get("game_config", self.default_game_config)
        sat_masks = options.get("sat_masks", self.default_sat_masks)

        if game_config is None or sat_masks is None:
            raise ValueError(
                "reset() requires game_config and sat_masks, either via the "
                "constructor defaults or reset(options=...)."
            )

        self.game = NegotiationState(
            n_players=game_config["N_PLAYERS"],
            n_actions=game_config["N_ACTIONS"],
            n_turns=options.get("n_turns", game_config.get("n_turns", 5)),
            G=game_config["G"],
            sat_masks=sat_masks,
            country_idx2num_actions=game_config["country_idx2num_actions"],
            seed=seed if seed is not None else options.get("state_seed", 0),
            binary_goals=game_config.get("binary_goals", []),
            allowed_actions=game_config.get("allowed_actions", self.allowed_actions),
            forbidden_actions=game_config.get("forbidden_actions", self.forbidden_actions),
            model=game_config.get("model", None),
            round_robin=game_config.get("round_robin", None),
        )

        self.stage = PARTNER_SELECTION_STAGE
        self.pending_partner = None
        self.offer_menu = None

        observation = self._build_observation()
        info = self._build_info(chosen_action=None, acted_player=None)
        return observation, info

    def step(self, action: int):
        """Apply one masked subdecision."""
        if self.game is None:
            raise RuntimeError("Call reset() before step().")

        if self.game.is_terminal():
            raise RuntimeError("Cannot step a terminated environment. Call reset().")

        acting_player = self.game.proposer()

        if self.stage == PARTNER_SELECTION_STAGE:
            partner_mask = build_partner_mask(
                self.game,
                max_players=self.max_players,
                allow_self=self.allow_self_partner,
            )
            self._validate_masked_action(action, partner_mask, "partner")
            self.pending_partner = PendingPartnerChoice(partner_id=int(action))
            self.offer_menu = build_offer_menu(
                self.game,
                partner_id=self.pending_partner.partner_id,
                max_actions=self.max_actions,
                max_candidate_offers=self.max_candidate_offers,
                max_changes=self.max_changes,
                allowed_actions=self.allowed_actions,
                forbidden_actions=self.forbidden_actions,
                include_no_deal=True,
            )
            self.stage = OFFER_SELECTION_STAGE
            terminated = False
            reward = 0.0

        elif self.stage == OFFER_SELECTION_STAGE:
            if self.pending_partner is None or self.offer_menu is None:
                raise RuntimeError("Offer stage reached without a selected partner.")

            self._validate_masked_action(action, self.offer_menu.mask, "offer")
            chosen_offer = self.offer_menu.candidates[int(action)]
            if chosen_offer is None:
                self.game.reject_deal()
            else:
                self.game.play_deal(chosen_offer, self.pending_partner.partner_id)

            terminated = self.game.is_terminal()
            reward = self.reward_fn(self.game, acting_player, terminated)
            self.pending_partner = None
            self.offer_menu = None
            self.stage = PARTNER_SELECTION_STAGE

        else:
            raise ValueError(f"Unknown stage id: {self.stage}")

        observation = self._build_observation()
        info = self._build_info(chosen_action=int(action), acted_player=acting_player)
        truncated = False
        return observation, reward, terminated, truncated, info

    def _build_observation(self):
        """Construct the current stage-aware observation."""
        partner_mask = np.zeros(self.max_players, dtype=np.int8)
        offer_mask = np.zeros(self.max_candidate_offers, dtype=np.int8)
        encoded_offer_actions = np.zeros(
            (self.max_candidate_offers, 1 + (2 * self.max_actions)), dtype=np.int8
        )
        selected_partner = None

        if self.game is not None and not self.game.is_terminal():
            if self.stage == PARTNER_SELECTION_STAGE:
                partner_mask = build_partner_mask(
                    self.game,
                    max_players=self.max_players,
                    allow_self=self.allow_self_partner,
                )
            elif self.stage == OFFER_SELECTION_STAGE:
                if self.pending_partner is None or self.offer_menu is None:
                    raise RuntimeError("Missing pending partner or offer menu.")
                selected_partner = self.pending_partner.partner_id
                offer_mask = self.offer_menu.mask
                encoded_offer_actions = self.offer_menu.encoded_actions

        observation = encode_observation(
            state=self.game,
            stage=self.stage,
            max_players=self.max_players,
            max_actions=self.max_actions,
            max_candidate_offers=self.max_candidate_offers,
            max_goal_slots=self.max_goal_slots,
            partner_mask=partner_mask,
            offer_mask=offer_mask,
            encoded_offer_actions=encoded_offer_actions,
            selected_partner=selected_partner,
        )

        if self.observation_space["player_features"].shape[1] != observation[
            "player_features"
        ].shape[1]:
            feature_dim = observation["player_features"].shape[1]
            self.observation_space.spaces["player_features"] = spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(self.max_players, feature_dim),
                dtype=np.float32,
            )

        self._last_obs = observation
        return observation

    def _build_info(self, *, chosen_action, acted_player):
        """Build auxiliary metadata for debugging and training."""
        info = {
            "stage": int(self.stage),
            "chosen_action": chosen_action,
            "acted_player": acted_player,
            "selected_partner": None
            if self.pending_partner is None
            else self.pending_partner.partner_id,
        }

        if self.offer_menu is not None:
            info["offer_candidates"] = self.offer_menu.candidates
            info["offer_mask"] = self.offer_menu.mask.copy()

        if self.game is not None and self.game.is_terminal():
            info["terminal_payoff_vector"] = self.game.get_payoff_vector().copy()

        return info

    @staticmethod
    def _validate_masked_action(action: int, mask: np.ndarray, kind: str):
        """Reject out-of-range or masked actions."""
        if action < 0 or action >= len(mask):
            raise ValueError(f"{kind} action {action} is out of range.")
        if mask[action] != 1:
            raise ValueError(f"{kind} action {action} is masked out.")
