"""Small, reproducible filter smoke experiment; no LLM, planner or training."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

from benac_p.belief import ConditionalPreferencePrior, ExactBayesFilter
from benac_p.controlled import SoftProgressPolicy
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.observations import build_player_observation
from benac_p.schema import OfferProposal
from benac_p.state import GameState


def run_demo(seed: int = 0, n_goals: int = 3, n_rounds: int = 2, ego_id: int = 0, *, include_joint=False):
    started = perf_counter()
    config = GeneratorConfig(actions_per_player=2, n_goals=n_goals, n_rounds=n_rounds)
    spec = generate_game(seed, config)
    state = GameState(spec)
    policies = {i: SoftProgressPolicy(seed=seed + i) for i in range(spec.n_players)}
    prior = ConditionalPreferencePrior(preference_probs=config.preference_probs)
    tracker = ExactBayesFilter(
        build_player_observation(state, ego_id), prior=prior,
        partner_policies={i: p for i, p in policies.items() if i != ego_id},
    )
    snapshots = [{"stage": "prior", "belief": tracker.belief.to_dict(include_joint=include_joint)}]
    while not state.is_terminal:
        actor = state.current_proposer()
        proposal = policies[actor].propose(build_player_observation(state, actor))
        if isinstance(proposal, OfferProposal):
            offer = proposal.offer
            # The ego can use this belief BEFORE choosing a response.
            tracker.synchronize(build_player_observation(
                state, ego_id, pending_proposer_id=actor, pending_offer=offer,
            ))
            snapshots.append({
                "stage": "pending_offer", "turn": state.turn_index,
                "belief": tracker.belief.to_dict(include_joint=include_joint),
            })
            response = policies[offer.partner_id].respond(build_player_observation(
                state, offer.partner_id, pending_proposer_id=actor, pending_offer=offer,
            ), offer)
            state.resolve_offer(offer, response)
        else:
            state.apply_pass()
        tracker.synchronize(build_player_observation(state, ego_id))
        snapshots.append({
            "stage": "completed_turn", "turn": state.turn_index - 1,
            "belief": tracker.belief.to_dict(include_joint=include_joint),
        })
    # Re-initialize using only the final observation, checking streaming vs replay.
    replay = ExactBayesFilter(
        build_player_observation(state, ego_id), prior=prior,
        partner_policies={i: p for i, p in policies.items() if i != ego_id},
    )
    max_error = max(abs(a - b) for a, b in zip(tracker.belief.probabilities, replay.belief.probabilities))
    return {
        "experiment": "conditional-prior-and-filter-smoke-v1", "seed": seed,
        "n_goals": n_goals, "n_rounds": n_rounds,
        "filter": tracker.specification(), "snapshots": snapshots, "updates": tracker.updates,
        "transcript": [e.to_dict() for e in state.transcript],
        "terminal_rewards": state.terminal_rewards().tolist(),
        "log_evidence": tracker.log_evidence, "stream_replay_max_probability_error": max_error,
        "elapsed_seconds": perf_counter() - started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-goals", type=int, default=3)
    parser.add_argument("--n-rounds", type=int, default=2)
    parser.add_argument("--ego-id", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--include-joint", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_demo(
        args.seed, args.n_goals, args.n_rounds, args.ego_id, include_joint=args.include_joint,
    ), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
