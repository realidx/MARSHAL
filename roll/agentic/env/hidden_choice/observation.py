"""Structured, model-independent observation generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .types import HiddenChoiceInstance, HiddenChoiceWorld


@dataclass(frozen=True)
class HiddenChoiceObservation:
    family_id: str
    condition: str
    context: Tuple[Tuple[str, str], ...]
    known_facts: Tuple[Tuple[str, str], ...]
    unknown_facts: Tuple[str, ...]
    available_questions: Tuple[Tuple[str, str], ...]
    communication_cost: float
    option_names: Tuple[str, ...]
    worlds: Tuple[HiddenChoiceWorld, ...]
    full_information: bool


def generate_observation(
    instance: HiddenChoiceInstance,
    known: Dict[str, str] | None = None,
    allow_questions: bool = True,
    full_information: bool = False,
) -> HiddenChoiceObservation:
    values = dict(known or {})
    if full_information:
        values.update(zip(instance.fact_names, instance.actual_values))
        allow_questions = False
    known_facts = instance.canonical_known(values)
    unknown_facts = tuple(fact for fact in instance.fact_names if fact not in values)
    questions = tuple(
        (question, fact)
        for question, fact in instance.questions
        if allow_questions and fact not in values
    )
    return HiddenChoiceObservation(
        family_id=instance.family_id,
        condition=instance.condition,
        context=instance.context,
        known_facts=known_facts,
        unknown_facts=unknown_facts,
        available_questions=questions,
        communication_cost=instance.communication_cost,
        option_names=instance.option_names,
        worlds=instance.worlds,
        full_information=full_information,
    )
