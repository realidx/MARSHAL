"""Procedural matched-condition generator for the first ASK pilot."""

from __future__ import annotations

import hashlib
import itertools
import random
from typing import Dict, Optional

from .config import PivotalQueryConfig
from .types import PivotalQueryInstance, World


CONDITIONS = (
    "known_pivotal",
    "ask_necessary",
    "costly_query",
    "irrelevant_uncertainty",
)


def _family_id(seed: int) -> str:
    return hashlib.sha256(f"pivotal-query-v1:{seed}".encode()).hexdigest()[:16]


def generate_instance(
    seed: int,
    condition: str,
    config: Optional[PivotalQueryConfig] = None,
) -> PivotalQueryInstance:
    config = config or PivotalQueryConfig()
    if condition == "cycle":
        condition = CONDITIONS[seed % len(CONDITIONS)]
    if condition not in CONDITIONS:
        raise ValueError(f"unknown Pivotal Query condition {condition!r}")

    rng = random.Random(seed)
    fact_names = ["F1", "F2", "F3"]
    partner_names = ["Alice", "Bob", "Carol"]
    option_names = ["A", "B", "C"]
    if config.randomize_labels:
        rng.shuffle(fact_names)
        rng.shuffle(partner_names)
        rng.shuffle(option_names)

    pivotal_fact = fact_names[0]
    domains = {
        fact_names[0]: ("safe", "unsafe"),
        fact_names[1]: ("red", "blue"),
        fact_names[2]: ("high", "low"),
    }
    option_roles = {
        option_names[0]: "risky",
        option_names[1]: "safe",
        option_names[2]: "conservative",
    }

    worlds = []
    ordered_domains = tuple(domains[fact] for fact in fact_names)
    assignments = tuple(itertools.product(*ordered_domains))
    for values in assignments:
        pivotal_value = values[0]
        payoff_by_role = {
            "risky": (
                5.0
                if condition == "irrelevant_uncertainty" and pivotal_value == "safe"
                else 8.0 if pivotal_value == "safe" else -8.0
            ),
            "safe": 6.0,
            "conservative": 4.0,
        }
        payoffs = tuple(payoff_by_role[option_roles[option]] for option in option_names)
        worlds.append(World(values=values, probability=1.0 / len(assignments), payoffs=payoffs))

    actual_values = rng.choice(assignments)
    initially_known = ()
    if condition == "known_pivotal":
        initially_known = ((pivotal_fact, actual_values[0]),)
    cost = config.high_query_cost if condition == "costly_query" else config.query_cost
    # Each partner holds one fact. The shuffled mapping is common knowledge to
    # the focal agent, so this stage isolates query routing rather than partner
    # model inference.
    partner_knowledge = tuple((fact_names[index],) for index in range(len(partner_names)))
    query_costs = tuple(tuple(float(cost) for _ in fact_names) for _ in partner_names)

    return PivotalQueryInstance(
        family_id=_family_id(seed),
        condition=condition,
        fact_names=tuple(fact_names),
        fact_domains=ordered_domains,
        partner_names=tuple(partner_names),
        partner_knowledge=partner_knowledge,
        option_names=tuple(option_names),
        worlds=tuple(worlds),
        initially_known=initially_known,
        query_costs=query_costs,
        actual_values=actual_values,
        pivotal_fact=pivotal_fact,
    )


def generate_matched_family(seed: int, config: Optional[PivotalQueryConfig] = None) -> Dict[str, PivotalQueryInstance]:
    return {condition: generate_instance(seed, condition, config) for condition in CONDITIONS}
