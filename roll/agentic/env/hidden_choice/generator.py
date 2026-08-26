"""Matched-quartet generator accepted only after exact VOI checks."""

from __future__ import annotations

import hashlib
import itertools
import random
from dataclasses import replace
from typing import Dict, Optional

from .config import HiddenChoiceConfig
from .sanity import check_instance
from .types import HiddenChoiceInstance, HiddenChoiceWorld


CONDITIONS = (
    "no_query",
    "necessary_query",
    "irrelevant_uncertainty",
    "selective_query",
)
SUPPORTED_CONDITIONS = (*CONDITIONS, "cost_suppressed")


def _family_id(seed: int) -> str:
    return hashlib.sha256(f"hidden-choice-v1:{seed}".encode()).hexdigest()[:16]


def generate_instance(
    seed: int,
    condition: str,
    config: Optional[HiddenChoiceConfig] = None,
) -> HiddenChoiceInstance:
    config = config or HiddenChoiceConfig()
    if condition == "cycle":
        condition = CONDITIONS[seed % len(CONDITIONS)]
    if condition not in SUPPORTED_CONDITIONS:
        raise ValueError(f"unknown Hidden Choice condition {condition!r}")
    margin_magnitude = config.margin_magnitude
    if margin_magnitude is not None and margin_magnitude <= 0:
        raise ValueError("margin_magnitude must be positive")
    communication_cost = float(
        margin_magnitude if margin_magnitude is not None else config.communication_cost
    )
    positive_margin = float(
        margin_magnitude if margin_magnitude is not None else config.target_positive_margin
    )
    if communication_cost < 0 or positive_margin <= -communication_cost:
        raise ValueError("the requested cost/margin cannot create positive gross VOI")
    # With risky utilities safe_value +/- signal_gap, one binary answer has
    # gross VOI signal_gap/2. This makes Delta exactly positive_margin.
    safe_value = 5.0
    if condition == "cost_suppressed":
        # The pivotal fact changes the decision, but its gross value is only
        # half the communication cost: 0 < G(q*) < c.
        signal_gap = communication_cost
    else:
        signal_gap = 2.0 * (communication_cost + positive_margin)

    rng = random.Random(seed)
    fact_names = ["F1", "F2", "F3"]
    # Use neutral labels so action names cannot be confused with board fields
    # such as communication cost.
    option_names = ["X", "Y", "Z"]
    question_names = ["Q1", "Q2", "Q3"]
    if config.randomize_labels:
        rng.shuffle(fact_names)
        rng.shuffle(option_names)
        rng.shuffle(question_names)
    pivotal_fact = fact_names[0]
    nuisance_fact = fact_names[1]
    question_by_fact = {
        fact: question for fact, question in zip(fact_names, question_names)
    }
    all_questions = tuple((question_by_fact[fact], fact) for fact in fact_names)
    questions = (
        ((question_by_fact[pivotal_fact], pivotal_fact),)
        if condition == "necessary_query"
        else all_questions
    )

    # The observed context changes all utilities by the same amount. It is a
    # genuine known component x of w=(x,y), while leaving every oracle label
    # invariant across the matched quartet.
    context_value = rng.choice(("calm", "busy"))
    utility_shift = rng.randint(-2, 2)
    context = (("market", context_value), ("utility_shift", f"{utility_shift:+d}"))

    domains = tuple(("0", "1") for _ in fact_names)
    assignments = tuple(itertools.product(*domains))
    role_by_option = {
        option_names[0]: "risky",
        option_names[1]: "safe",
        option_names[2]: "conservative",
    }
    worlds = []
    for values in assignments:
        pivotal_value = values[fact_names.index(pivotal_fact)]
        nuisance_value = values[fact_names.index(nuisance_fact)]
        if condition in ("necessary_query", "selective_query", "cost_suppressed"):
            role_utilities = {
                "risky": safe_value + signal_gap if pivotal_value == "1" else safe_value - signal_gap,
                "safe": safe_value,
                "conservative": safe_value - 1.0,
            }
        elif condition == "irrelevant_uncertainty":
            role_utilities = {
                "risky": 8.0,
                "safe": 6.0,
                "conservative": 4.0 if nuisance_value == "1" else 2.0,
            }
        else:
            role_utilities = {"risky": 8.0, "safe": 6.0, "conservative": 4.0}
        utilities = tuple(
            role_utilities[role_by_option[option]] + utility_shift
            for option in option_names
        )
        worlds.append(
            HiddenChoiceWorld(
                hidden_values=values,
                probability=1.0 / len(assignments),
                utilities=utilities,
            )
        )

    actual_values = rng.choice(assignments)
    full_action_order = [
        *(f"ASK {fact}" for _, fact in all_questions),
        *(f"ACT {option}" for option in option_names),
    ]
    if config.shuffle_action_order:
        rng.shuffle(full_action_order)
    legal_universe = {
        *(f"ASK {fact}" for _, fact in questions),
        *(f"ACT {option}" for option in option_names),
    }
    actions = [action for action in full_action_order if action in legal_universe]
    instance = HiddenChoiceInstance(
        family_id=_family_id(seed),
        condition=condition,
        context=context,
        fact_names=tuple(fact_names),
        fact_domains=domains,
        option_names=tuple(option_names),
        worlds=tuple(worlds),
        actual_values=actual_values,
        questions=questions,
        communication_cost=communication_cost,
        action_order=tuple(actions),
        pivotal_fact=pivotal_fact,
    )
    report = check_instance(instance)
    if condition == "cost_suppressed":
        expected_margin = -communication_cost / 2.0
    else:
        expected_margin = (
            positive_margin
            if condition in ("necessary_query", "selective_query")
            else -communication_cost
        )
    if abs(report.oracle_margin - expected_margin) > 1e-9:
        raise ValueError(
            f"generator missed requested oracle margin: {report.oracle_margin} != {expected_margin}"
        )
    return instance


def generate_matched_quartet(
    seed: int,
    config: Optional[HiddenChoiceConfig] = None,
) -> Dict[str, HiddenChoiceInstance]:
    return {
        condition: generate_instance(seed, condition, config)
        for condition in CONDITIONS
    }


def generate_threshold_pair(
    seed: int,
    condition: str = "selective_query",
    gross_value: float = 0.8,
    costs: tuple[float, float] = (0.3, 0.9),
    config: Optional[HiddenChoiceConfig] = None,
) -> tuple[HiddenChoiceInstance, HiddenChoiceInstance]:
    """Create a counterfactual pair with identical worlds and different costs.

    The base instance is constructed so its pivotal query has the requested
    gross value, then only ``communication_cost`` is intervened on. The pair
    therefore crosses the oracle threshold without changing the task state.
    """
    if condition not in ("necessary_query", "selective_query"):
        raise ValueError("threshold pairs require necessary_query or selective_query")
    if gross_value <= 0 or not (costs[0] < gross_value < costs[1]):
        raise ValueError("costs must straddle a positive gross_value")
    base_config = config or HiddenChoiceConfig()
    base_config = replace(
        base_config,
        communication_cost=gross_value / 2.0,
        margin_magnitude=gross_value / 2.0,
    )
    base = generate_instance(seed, condition, base_config)
    pair = tuple(replace(base, communication_cost=float(cost)) for cost in costs)
    return pair  # type: ignore[return-value]
