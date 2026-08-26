"""Exact one-shot value-of-information oracle for Hidden Choice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .enumerator import (
    enumerate_act_values,
    enumerate_answer_probabilities,
    enumerate_compatible_worlds,
)
from .types import HiddenChoiceInstance, HiddenChoiceWorld


@dataclass(frozen=True)
class OneShotDecision:
    value_act: float
    value: float
    act_values: Tuple[Tuple[str, float], ...]
    value_ask: Tuple[Tuple[str, float], ...]
    gross_voi: Tuple[Tuple[str, float], ...]
    net_query_values: Tuple[Tuple[str, float], ...]
    optimal_actions: Tuple[str, ...]
    best_questions: Tuple[str, ...]
    should_ask: bool

    def action_value(self, action: str) -> float:
        return dict(self.act_values + self.net_query_values)[action]


class OneShotVOIOracle:
    """Compute V_act, V_ask and gross VOI without Bellman recursion."""

    def __init__(self, instance: HiddenChoiceInstance, tolerance: float = 1e-10):
        self.instance = instance
        self.tolerance = tolerance

    def belief(self, known=None) -> Tuple[Tuple[HiddenChoiceWorld, float], ...]:
        return enumerate_compatible_worlds(self.instance, known or {})

    def solve(self, known=None, allow_questions: bool = True) -> OneShotDecision:
        known = dict(known or {})
        belief = self.belief(known)
        act_values = enumerate_act_values(self.instance, belief)
        value_act = max(value for _, value in act_values)

        value_ask = []
        if allow_questions:
            for question, fact in self.instance.questions:
                if fact in known:
                    continue
                post_answer_value = 0.0
                for answer, answer_probability in enumerate_answer_probabilities(
                    self.instance, belief, fact
                ):
                    next_known = dict(known)
                    next_known[fact] = answer
                    post_answer_value += answer_probability * self.solve(
                        next_known, allow_questions=False
                    ).value_act
                value_ask.append((f"ASK {question}", post_answer_value))

        gross_voi = tuple((action, value - value_act) for action, value in value_ask)
        net_query_values = tuple(
            (action, value - self.instance.communication_cost) for action, value in value_ask
        )
        best_gross = max((value for _, value in gross_voi), default=float("-inf"))
        should_ask = best_gross > self.instance.communication_cost + self.tolerance
        if should_ask:
            best_questions = tuple(
                action for action, value in gross_voi if abs(value - best_gross) <= self.tolerance
            )
            optimal_actions = best_questions
            value = max(dict(net_query_values)[action] for action in best_questions)
        else:
            best_questions = ()
            optimal_actions = tuple(
                action for action, value in act_values if abs(value - value_act) <= self.tolerance
            )
            value = value_act
        return OneShotDecision(
            value_act=value_act,
            value=value,
            act_values=act_values,
            value_ask=tuple(value_ask),
            gross_voi=gross_voi,
            net_query_values=net_query_values,
            optimal_actions=optimal_actions,
            best_questions=best_questions,
            should_ask=should_ask,
        )
