"""Exact finite-world enumeration primitives for Hidden Choice."""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

from .types import HiddenChoiceInstance, HiddenChoiceWorld


WeightedWorlds = Tuple[Tuple[HiddenChoiceWorld, float], ...]


def enumerate_compatible_worlds(
    instance: HiddenChoiceInstance,
    known: Dict[str, str] | Iterable[Tuple[str, str]] = (),
) -> WeightedWorlds:
    known = dict(known)
    compatible = [
        world
        for world in instance.worlds
        if all(
            world.hidden_values[instance.fact_index(fact)] == value
            for fact, value in known.items()
        )
    ]
    mass = sum(world.probability for world in compatible)
    if mass <= 0:
        raise ValueError(f"knowledge is inconsistent with every world: {known}")
    return tuple((world, world.probability / mass) for world in compatible)


def enumerate_act_values(
    instance: HiddenChoiceInstance,
    belief: WeightedWorlds,
):
    return tuple(
        (
            f"ACT {option}",
            sum(probability * world.utilities[index] for world, probability in belief),
        )
        for index, option in enumerate(instance.option_names)
    )


def enumerate_answer_probabilities(
    instance: HiddenChoiceInstance,
    belief: WeightedWorlds,
    fact: str,
):
    fact_index = instance.fact_index(fact)
    probabilities = {}
    for world, probability in belief:
        answer = world.hidden_values[fact_index]
        probabilities[answer] = probabilities.get(answer, 0.0) + probability
    return tuple(probabilities.items())
