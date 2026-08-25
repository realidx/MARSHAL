"""Exact belief-state dynamic programming for Pivotal Query Game."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional, Tuple

from .types import PivotalQueryInstance, World


@dataclass(frozen=True)
class OracleDecision:
    value: float
    best_act_value: float
    best_query_value: Optional[float]
    act_values: Tuple[Tuple[str, float], ...]
    query_values: Tuple[Tuple[str, float], ...]
    optimal_actions: Tuple[str, ...]
    should_ask: bool

    def action_value(self, action: str) -> float:
        values = dict(self.act_values + self.query_values)
        return values[action]


class ExactQueryOracle:
    """Solve ASK/ACT decisions exactly over the instance's finite worlds."""

    def __init__(self, instance: PivotalQueryInstance, tolerance: float = 1e-10):
        self.instance = instance
        self.tolerance = tolerance

    def solve(
        self,
        known: Dict[str, str],
        available_queries=None,
        queries_left: Optional[int] = None,
    ) -> OracleDecision:
        available = tuple(self.instance.all_queries() if available_queries is None else available_queries)
        if queries_left is None:
            queries_left = len(available)
        return self._solve(
            self.instance.canonical_known(known),
            available,
            int(queries_left),
        )

    def belief(self, known: Dict[str, str]) -> Tuple[Tuple[World, float], ...]:
        return self._belief(self.instance.canonical_known(known))

    def _belief(self, known_key) -> Tuple[Tuple[World, float], ...]:
        known = dict(known_key)
        compatible = []
        for world in self.instance.worlds:
            if all(world.values[self.instance.fact_index(fact)] == value for fact, value in known.items()):
                compatible.append(world)
        mass = sum(world.probability for world in compatible)
        if mass <= 0:
            raise ValueError(f"knowledge is inconsistent with every world: {known}")
        return tuple((world, world.probability / mass) for world in compatible)

    @lru_cache(maxsize=None)
    def _solve(self, known_key, available_queries, queries_left) -> OracleDecision:
        known = dict(known_key)
        belief = self._belief(known_key)
        act_values = []
        for option_index, option in enumerate(self.instance.option_names):
            expected = sum(probability * world.payoffs[option_index] for world, probability in belief)
            act_values.append((f"ACT {option}", expected))
        best_act_value = max(value for _, value in act_values)

        query_values = []
        if queries_left > 0:
            for partner, fact in available_queries:
                if fact in known:
                    continue
                action = f"ASK {partner} {fact}"
                remaining = tuple(query for query in available_queries if query != (partner, fact))
                if self.instance.partner_knows(partner, fact):
                    fact_index = self.instance.fact_index(fact)
                    answer_probabilities: Dict[str, float] = {}
                    for world, probability in belief:
                        answer = world.values[fact_index]
                        answer_probabilities[answer] = answer_probabilities.get(answer, 0.0) + probability
                    continuation = 0.0
                    for answer, probability in answer_probabilities.items():
                        next_known = dict(known)
                        next_known[fact] = answer
                        continuation += (
                            probability
                            * self._solve(
                                self.instance.canonical_known(next_known),
                                remaining,
                                queries_left - 1,
                            ).value
                        )
                else:
                    # A truthful "I don't know" changes routing history but not
                    # the world belief.
                    continuation = self._solve(
                        known_key,
                        remaining,
                        queries_left - 1,
                    ).value
                query_values.append(
                    (
                        action,
                        continuation - self.instance.query_cost(partner, fact),
                    )
                )

        best_query_value = max((value for _, value in query_values), default=None)
        value = max(
            best_act_value,
            best_query_value if best_query_value is not None else float("-inf"),
        )
        optimal_actions = tuple(
            action for action, action_value in act_values + query_values if abs(action_value - value) <= self.tolerance
        )
        # Ties deliberately stop: communication must strictly improve net value.
        should_ask = best_query_value is not None and best_query_value > best_act_value + self.tolerance
        return OracleDecision(
            value=value,
            best_act_value=best_act_value,
            best_query_value=best_query_value,
            act_values=tuple(act_values),
            query_values=tuple(query_values),
            optimal_actions=optimal_actions,
            should_ask=should_ask,
        )
