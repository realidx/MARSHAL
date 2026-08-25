"""Dependency-free data types for exact Pivotal Query instances."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Dict, Iterable, Tuple, Union


@dataclass(frozen=True)
class World:
    values: Tuple[str, ...]
    probability: float
    payoffs: Tuple[float, ...]


@dataclass(frozen=True)
class PivotalQueryInstance:
    family_id: str
    condition: str
    fact_names: Tuple[str, ...]
    fact_domains: Tuple[Tuple[str, ...], ...]
    partner_names: Tuple[str, ...]
    partner_knowledge: Tuple[Tuple[str, ...], ...]
    option_names: Tuple[str, ...]
    worlds: Tuple[World, ...]
    initially_known: Tuple[Tuple[str, str], ...]
    query_costs: Tuple[Tuple[float, ...], ...]
    actual_values: Tuple[str, ...]
    pivotal_fact: str

    def __post_init__(self):
        if not self.fact_names or len(set(self.fact_names)) != len(self.fact_names):
            raise ValueError("fact_names must be nonempty and unique")
        if not self.option_names or len(set(self.option_names)) != len(self.option_names):
            raise ValueError("option_names must be nonempty and unique")
        if len(self.fact_domains) != len(self.fact_names):
            raise ValueError("fact_domains must align with fact_names")
        if not self.partner_names or len(set(self.partner_names)) != len(self.partner_names):
            raise ValueError("partner_names must be nonempty and unique")
        if len(self.partner_knowledge) != len(self.partner_names):
            raise ValueError("partner_knowledge must align with partner_names")
        for knowledge in self.partner_knowledge:
            if any(fact not in self.fact_names for fact in knowledge):
                raise ValueError("partner knowledge contains an unknown fact")
        if len(self.query_costs) != len(self.partner_names) or any(
            len(costs) != len(self.fact_names) for costs in self.query_costs
        ):
            raise ValueError("query_costs must be a partner-by-fact matrix")
        if len(self.actual_values) != len(self.fact_names):
            raise ValueError("actual_values must align with fact_names")
        if any(cost < 0 for costs in self.query_costs for cost in costs):
            raise ValueError("query costs must be nonnegative")
        if not isclose(sum(world.probability for world in self.worlds), 1.0, abs_tol=1e-9):
            raise ValueError("world probabilities must sum to one")
        assignments = set()
        for world in self.worlds:
            if len(world.values) != len(self.fact_names):
                raise ValueError("world values must align with fact_names")
            if len(world.payoffs) != len(self.option_names):
                raise ValueError("world payoffs must align with option_names")
            if world.probability <= 0:
                raise ValueError("world probabilities must be positive")
            if world.values in assignments:
                raise ValueError("world assignments must be unique")
            assignments.add(world.values)
        if self.actual_values not in assignments:
            raise ValueError("actual_values must identify a possible world")
        known = dict(self.initially_known)
        if len(known) != len(self.initially_known):
            raise ValueError("initially_known contains duplicate facts")
        for fact, value in known.items():
            index = self.fact_index(fact)
            if value != self.actual_values[index]:
                raise ValueError("initial knowledge must be truthful")
        if self.pivotal_fact not in self.fact_names:
            raise ValueError("pivotal_fact must name a fact")

    def fact_index(self, fact: str) -> int:
        try:
            return self.fact_names.index(fact)
        except ValueError as exc:
            raise ValueError(f"unknown fact {fact!r}") from exc

    def option_index(self, option: str) -> int:
        try:
            return self.option_names.index(option)
        except ValueError as exc:
            raise ValueError(f"unknown option {option!r}") from exc

    def partner_index(self, partner: str) -> int:
        try:
            return self.partner_names.index(partner)
        except ValueError as exc:
            raise ValueError(f"unknown partner {partner!r}") from exc

    def query_cost(self, partner: str, fact: str) -> float:
        return self.query_costs[self.partner_index(partner)][self.fact_index(fact)]

    def partner_knows(self, partner: str, fact: str) -> bool:
        return fact in self.partner_knowledge[self.partner_index(partner)]

    def all_queries(self):
        return tuple((partner, fact) for partner in self.partner_names for fact in self.fact_names)

    def actual_value(self, fact: str) -> str:
        return self.actual_values[self.fact_index(fact)]

    def actual_payoff(self, option: str) -> float:
        option_index = self.option_index(option)
        for world in self.worlds:
            if world.values == self.actual_values:
                return world.payoffs[option_index]
        raise AssertionError("validated actual world disappeared")

    def known_dict(self) -> Dict[str, str]:
        return dict(self.initially_known)

    def canonical_known(self, known: Union[Dict[str, str], Iterable[Tuple[str, str]]]):
        values = dict(known)
        return tuple((fact, values[fact]) for fact in self.fact_names if fact in values)
