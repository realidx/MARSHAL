"""Automatic oracle acceptance checks for generated Hidden Choice states."""

from __future__ import annotations

from dataclasses import dataclass

from .oracle import OneShotVOIOracle
from .types import HiddenChoiceInstance


@dataclass(frozen=True)
class SanityReport:
    condition: str
    value_act: float
    max_gross_voi: float
    communication_cost: float
    oracle_margin: float
    valuable_questions: tuple[str, ...]
    passed: bool


def check_instance(instance: HiddenChoiceInstance, tolerance: float = 1e-9) -> SanityReport:
    decision = OneShotVOIOracle(instance).solve()
    max_voi = max((value for _, value in decision.gross_voi), default=0.0)
    valuable = tuple(
        action
        for action, value in decision.gross_voi
        if value > instance.communication_cost + tolerance
    )
    unknown_exists = bool(instance.fact_names)
    if instance.condition == "no_query":
        passed = max_voi <= instance.communication_cost + tolerance
        passed = passed and len({world.utilities for world in instance.worlds}) == 1
    elif instance.condition == "necessary_query":
        passed = len(valuable) == 1
    elif instance.condition == "irrelevant_uncertainty":
        passed = unknown_exists and max_voi <= instance.communication_cost + tolerance
        passed = passed and len({world.utilities for world in instance.worlds}) > 1
    elif instance.condition == "selective_query":
        passed = len(valuable) == 1 and len(instance.questions) > 1
    else:
        raise ValueError(f"unknown Hidden Choice condition {instance.condition!r}")

    if valuable:
        expected = f"ASK {next(question for question, fact in instance.questions if fact == instance.pivotal_fact)}"
        passed = passed and valuable == (expected,)
    if not passed:
        raise ValueError(
            f"generated {instance.condition} failed oracle sanity check: "
            f"max_voi={max_voi:g}, cost={instance.communication_cost:g}, valuable={valuable}"
        )
    return SanityReport(
        condition=instance.condition,
        value_act=decision.value_act,
        max_gross_voi=max_voi,
        communication_cost=instance.communication_cost,
        oracle_margin=max_voi - instance.communication_cost,
        valuable_questions=valuable,
        passed=True,
    )
