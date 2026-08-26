"""Dependency-free finite-world types for Hidden Choice."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class HiddenChoiceWorld:
    hidden_values: Tuple[str, ...]
    probability: float
    utilities: Tuple[float, ...]


@dataclass(frozen=True)
class HiddenChoiceInstance:
    family_id: str
    condition: str
    context: Tuple[Tuple[str, str], ...]
    fact_names: Tuple[str, ...]
    fact_domains: Tuple[Tuple[str, ...], ...]
    option_names: Tuple[str, ...]
    worlds: Tuple[HiddenChoiceWorld, ...]
    actual_values: Tuple[str, ...]
    questions: Tuple[Tuple[str, str], ...]
    communication_cost: float
    action_order: Tuple[str, ...]
    pivotal_fact: str

    def __post_init__(self):
        if not self.fact_names or len(set(self.fact_names)) != len(self.fact_names):
            raise ValueError("fact_names must be nonempty and unique")
        if len(self.fact_domains) != len(self.fact_names):
            raise ValueError("fact_domains must align with fact_names")
        if not self.option_names or len(set(self.option_names)) != len(self.option_names):
            raise ValueError("option_names must be nonempty and unique")
        if self.communication_cost < 0:
            raise ValueError("communication_cost must be nonnegative")
        question_names = [question for question, _ in self.questions]
        if not question_names or len(set(question_names)) != len(question_names):
            raise ValueError("question names must be nonempty and unique")
        if any(fact not in self.fact_names for _, fact in self.questions):
            raise ValueError("every question must reveal a known hidden fact")
        if self.pivotal_fact not in self.fact_names:
            raise ValueError("pivotal_fact must name a hidden fact")
        if len(self.actual_values) != len(self.fact_names):
            raise ValueError("actual_values must align with fact_names")
        if not isclose(sum(world.probability for world in self.worlds), 1.0, abs_tol=1e-9):
            raise ValueError("world probabilities must sum to one")
        assignments = set()
        for world in self.worlds:
            if world.probability <= 0:
                raise ValueError("world probabilities must be positive")
            if len(world.hidden_values) != len(self.fact_names):
                raise ValueError("world hidden values must align with fact_names")
            if len(world.utilities) != len(self.option_names):
                raise ValueError("world utilities must align with option_names")
            if world.hidden_values in assignments:
                raise ValueError("world hidden assignments must be unique")
            assignments.add(world.hidden_values)
        if self.actual_values not in assignments:
            raise ValueError("actual_values must identify a possible world")
        legal_universe = {
            *(f"ASK {fact}" for _, fact in self.questions),
            *(f"ACT {option}" for option in self.option_names),
        }
        if set(self.action_order) != legal_universe or len(self.action_order) != len(legal_universe):
            raise ValueError("action_order must contain every action exactly once")

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

    def question_fact(self, question: str) -> str:
        try:
            return dict(self.questions)[question]
        except KeyError as exc:
            raise ValueError(f"unknown question {question!r}") from exc

    def fact_question(self, fact: str) -> str:
        for question, mapped_fact in self.questions:
            if mapped_fact == fact:
                return question
        raise ValueError(f"no question reveals fact {fact!r}")

    def actual_value(self, fact: str) -> str:
        return self.actual_values[self.fact_index(fact)]

    def actual_utility(self, option: str) -> float:
        option_index = self.option_index(option)
        for world in self.worlds:
            if world.hidden_values == self.actual_values:
                return world.utilities[option_index]
        raise AssertionError("validated actual world disappeared")

    def canonical_known(self, known: Dict[str, str] | Iterable[Tuple[str, str]]):
        values = dict(known)
        return tuple((fact, values[fact]) for fact in self.fact_names if fact in values)
