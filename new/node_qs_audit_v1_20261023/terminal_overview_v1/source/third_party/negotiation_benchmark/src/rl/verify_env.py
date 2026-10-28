"""
Verification script for the RL negotiation wrapper.

This checks that wrapper-mediated transitions match direct engine transitions
for the same chosen partner and offer. It is intentionally narrow: the goal is
to verify semantic equivalence of state updates, not learning performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.game_configs import ScenarioProfile, create_sat_masks, generate_game_config
from rl.env import NegotiationTurnEnv


def _make_game(seed: int):
    profile = ScenarioProfile(
        structure_type="adversarial",
        binary_fraction=0.3,
        complexity_zipf_a=1.6,
    )
    game_config = generate_game_config(
        n_players=4,
        country_idx2num_actions={i: 3 for i in range(4)},
        n_goals=8,
        k_factors=3,
        seed=seed,
        profile=profile,
        shift="balanced",
    )
    sat_masks = create_sat_masks(game_config)
    return game_config, sat_masks


def _assert_same_transition(left_state, right_state, *, label: str):
    if left_state.idx != right_state.idx:
        raise AssertionError(
            f"{label}: idx mismatch {left_state.idx} != {right_state.idx}"
        )
    if not np.array_equal(left_state.P, right_state.P):
        raise AssertionError(f"{label}: policy matrix mismatch")
    if not np.allclose(left_state.get_payoff_vector(), right_state.get_payoff_vector()):
        raise AssertionError(f"{label}: payoff vector mismatch")


def verify_one_seed(seed: int):
    game_config, sat_masks = _make_game(seed)
    env = NegotiationTurnEnv(
        max_players=game_config["N_PLAYERS"],
        max_actions=game_config["N_ACTIONS"],
        max_candidate_offers=256,
        max_changes=2,
        allow_self_partner=False,
        game_config=game_config,
        sat_masks=sat_masks,
    )

    observation, _ = env.reset(seed=seed)
    partner_mask = observation["partner_mask"]
    legal_partners = np.flatnonzero(partner_mask == 1)
    if legal_partners.size == 0:
        raise AssertionError("No legal partners available for verification.")

    partner = int(legal_partners[0])
    direct_state = env.game.clone()

    observation, reward, terminated, truncated, info = env.step(partner)
    if reward != 0.0 or terminated or truncated:
        raise AssertionError("Partner-selection step should be non-terminal with zero reward.")
    _assert_same_transition(env.game, direct_state, label="partner-selection")

    # Verify explicit no-deal maps to reject_deal().
    no_deal_state = direct_state.clone()
    no_deal_state.reject_deal()
    observation, reward, terminated, truncated, info = env.step(0)
    _assert_same_transition(env.game, no_deal_state, label="no-deal")
    if env.game.is_terminal():
        return

    # Reset and verify one real offer also matches direct play_deal().
    observation, _ = env.reset(seed=seed)
    partner = int(np.flatnonzero(observation["partner_mask"] == 1)[0])
    direct_state = env.game.clone()
    observation, _, _, _, _ = env.step(partner)

    offer_candidates = env.offer_menu.candidates
    offer_index = None
    chosen_offer = None
    for idx, candidate in enumerate(offer_candidates):
        if candidate is not None:
            offer_index = idx
            chosen_offer = candidate
            break

    if offer_index is None:
        raise AssertionError("Offer menu only contained no-deal.")

    accepted_state = direct_state.clone()
    accepted_state.play_deal(chosen_offer, partner)
    observation, _, _, _, _ = env.step(offer_index)
    _assert_same_transition(env.game, accepted_state, label="accepted-offer")


def main():
    seeds = [0, 1, 2]
    for seed in seeds:
        verify_one_seed(seed)
    print(f"RL wrapper verification passed for seeds: {seeds}")


if __name__ == "__main__":
    main()
