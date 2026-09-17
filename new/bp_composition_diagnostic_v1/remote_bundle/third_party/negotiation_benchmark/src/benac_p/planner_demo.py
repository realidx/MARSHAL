"""Reviewable belief-dependent choices and a third-party continuation fixture."""

from __future__ import annotations

import json
from time import perf_counter

import numpy as np

from benac_p.bayes_planner import BayesPlanner
from benac_p.belief import BeliefState, ExactBayesFilter
from benac_p.observations import build_player_observation
from benac_p.schema import ActionRef, GameSpec, Goal, Offer, PassProposal, Preference
from benac_p.state import GameState


def belief_choice_spec():
    """Fixed public structure; inference uses the v0 conditional preference prior."""
    return GameSpec(
        n_players=3, n_actions_per_player=(2, 1, 1),
        goals=(Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),
               Goal(1, (ActionRef(0, 1), ActionRef(2, 0)))),
        private_preferences=np.array([[1, 1], [1, -1], [-1, 1]], dtype=np.int8),
        round_robin=(1, 0), max_changes=1, seed=0,
    )


def run_demo():
    start = perf_counter()
    planner = BayesPlanner()
    cases = []
    for name, offer in (
        ("P1_offers_to_complete_G0", Offer(0, (1,), (1, 0))),
        ("P1_offers_partial_G1", Offer(0, (0,), (0, 1))),
    ):
        state = GameState(belief_choice_spec())
        # Both legal histories end with ego REJECT, leaving identical C/turn/phase.
        state.resolve_offer(offer, "REJECT")
        observation = build_player_observation(state, 0)
        belief = ExactBayesFilter(observation).belief
        result = planner.solve(observation, belief)
        cases.append({
            "name": name, "observation": observation.to_agent_dict(),
            "belief": belief.to_dict(), "planning": result.to_dict(),
        })
    first_action = cases[0]["planning"]["action"]
    second_action = cases[1]["planning"]["action"]
    if first_action == second_action:
        raise AssertionError("Fixture no longer demonstrates different optimal choices.")
    for case, other_action in zip(cases, (second_action, first_action)):
        other_value = next(v["value"] for v in case["planning"]["action_values"] if v["action"] == other_action)
        case["regret_of_other_history_action"] = case["planning"]["value"] - other_value

    # Explicit known-state control: value requires P2's subsequent turn.
    spec = GameSpec(
        n_players=3, n_actions_per_player=(1, 1, 1),
        goals=(Goal(0, tuple(ActionRef(i, 0) for i in range(3))),),
        private_preferences=np.ones((3, 1), dtype=np.int8),
        round_robin=(0, 2), max_changes=1, seed=0,
    )
    state = GameState(spec)
    observation = build_player_observation(state, 0)
    known_belief = BeliefState((1, 2), (((Preference.WANT,), (Preference.WANT,)),), (0.0,))
    result = planner.solve(observation, known_belief)
    return {
        "experiment": "belief-conditioned-planner-smoke-v1",
        "scope": "Constructed diagnostic fixtures; not LLM results or population estimates.",
        "planner": planner.specification(), "belief_choice_cases": cases,
        "third_party_continuation": {
            "observation": observation.to_agent_dict(), "belief": known_belief.to_dict(),
            "planning": result.to_dict(),
            "all_one_offer_snapshot_utilities": [
                observation.state_facts(observation.commitments_if_accepted(o))["your_utility_if_terminal"]
                for o in observation.legal_offers
            ],
            "regret_of_pass": result.regret(PassProposal()),
        },
        "elapsed_seconds": perf_counter() - start,
    }


def main():
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
