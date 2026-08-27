"""Source-aware multi-partner Hidden Choice diagnostics.

This module is deliberately separate from the legacy one-query game.  It
adds a finite query budget, deterministic UNKNOWN responses, and a recursive
exact oracle while keeping the original benchmark/API backwards compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from .enumerator import enumerate_act_values, enumerate_answer_probabilities, enumerate_compatible_worlds
from .types import HiddenChoiceInstance


@dataclass(frozen=True)
class SourceAwareConfig:
    partners: Tuple[str, ...] = ("Alice", "Bob", "Carol")
    knowledge: Mapping[str, Tuple[str, ...]] | None = None
    max_queries: int = 2
    query_cost: float = 0.25


@dataclass(frozen=True)
class SourceHistory:
    known: Tuple[Tuple[str, str], ...] = ()
    queries: Tuple[Tuple[str, str, str], ...] = ()
    remaining_queries: int = 2
    accumulated_cost: float = 0.0


@dataclass(frozen=True)
class SourceDecision:
    value: float
    action_values: Tuple[Tuple[str, float], ...]
    optimal_actions: Tuple[str, ...]


class SourceAwareVOIOracle:
    """Brute-force recursive oracle over worlds, sources, and retries."""

    def __init__(self, instance: HiddenChoiceInstance, config: SourceAwareConfig):
        if config.max_queries < 0 or config.query_cost < 0:
            raise ValueError("max_queries and query_cost must be nonnegative")
        self.instance = instance
        self.config = config
        default = {partner: tuple(instance.fact_names) for partner in config.partners}
        self.knowledge = {partner: tuple(facts) for partner, facts in (config.knowledge or default).items()}
        if set(self.knowledge) != set(config.partners):
            raise ValueError("knowledge must specify exactly all configured partners")
        self._cache: Dict[SourceHistory, SourceDecision] = {}

    def response(self, partner: str, fact: str) -> str:
        return fact if fact in self.knowledge[partner] else "UNKNOWN"

    def _act_values(self, known: Tuple[Tuple[str, str], ...]):
        belief = enumerate_compatible_worlds(self.instance, known)
        return enumerate_act_values(self.instance, belief)

    def solve(self, history: SourceHistory | None = None) -> SourceDecision:
        history = history or SourceHistory(remaining_queries=self.config.max_queries)
        cached = self._cache.get(history)
        if cached is not None:
            return cached
        known = tuple(history.known)
        queried = frozenset((partner, fact) for partner, fact, _ in history.queries)
        act_values = self._act_values(known)
        candidates = list(act_values)
        if history.remaining_queries:
            for partner in self.config.partners:
                for fact in self.instance.fact_names:
                    key = (partner, fact)
                    if key in queried:
                        continue
                    response = self.response(partner, fact)
                    if response == "UNKNOWN":
                        next_history = SourceHistory(known, history.queries + ((partner, fact, response),), history.remaining_queries - 1, history.accumulated_cost + self.config.query_cost)
                        value = self.solve(next_history).value - self.config.query_cost
                    else:
                        expected = 0.0
                        belief = enumerate_compatible_worlds(self.instance, known)
                        for answer, probability in enumerate_answer_probabilities(self.instance, belief, fact):
                            next_known = dict(known); next_known[fact] = answer
                            next_history = SourceHistory(tuple(next_known.items()), history.queries + ((partner, fact, answer),), history.remaining_queries - 1, history.accumulated_cost + self.config.query_cost)
                            expected += probability * self.solve(next_history).value
                        value = expected - self.config.query_cost
                    candidates.append((f"ASK {partner} {fact}", value))
        best = max(value for _, value in candidates)
        optimal = tuple(action for action, value in candidates if abs(value - best) <= 1e-10)
        decision = SourceDecision(best, tuple(candidates), optimal)
        self._cache[history] = decision
        return decision


class SourceAwareGame:
    """Deterministic transition system for multi-source ASK/UNKNOWN play."""

    def __init__(self, instance: HiddenChoiceInstance, config: SourceAwareConfig):
        self.instance, self.config = instance, config
        self.oracle = SourceAwareVOIOracle(instance, config)
        self.history = SourceHistory(remaining_queries=config.max_queries)
        self.done = False
        self.total_reward = 0.0
        self.records = []

    @property
    def legal_actions(self):
        actions = [f"ACT {option}" for option in self.instance.option_names]
        if self.history.remaining_queries:
            queried = {(p, f) for p, f, _ in self.history.queries}
            actions.extend(
                f"ASK {partner} {fact}"
                for partner in self.config.partners
                for fact in self.instance.fact_names
                if (partner, fact) not in queried
            )
        return tuple(actions)

    def step(self, action: str):
        if self.done or action not in self.legal_actions:
            raise ValueError(f"illegal Source-aware action: {action}")
        oracle = self.oracle.solve(self.history)
        optimal = action in oracle.optimal_actions
        if action.startswith("ACT "):
            option = action.removeprefix("ACT ")
            reward = self.instance.actual_utility(option)
            self.done = True
            observation = f"Final choice: {option}. Realized utility: {reward:g}."
        else:
            _, partner, fact = action.split(maxsplit=2)
            answer = self.oracle.response(partner, fact)
            if answer != "UNKNOWN":
                answer = self.instance.actual_value(fact)
                known = dict(self.history.known); known[fact] = answer
            else:
                known = dict(self.history.known)
            self.history = SourceHistory(
                tuple(known.items()),
                self.history.queries + ((partner, fact, answer),),
                self.history.remaining_queries - 1,
                self.history.accumulated_cost + self.config.query_cost,
            )
            reward = -self.config.query_cost
            observation = f"{partner} answers: {fact} = {answer}."
        self.total_reward += reward
        record = {"action": action, "oracle_optimal": float(optimal), "step_reward": reward}
        self.records.append(record)
        return observation, reward, self.done, record
