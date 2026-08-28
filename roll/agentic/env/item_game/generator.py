"""Deterministic structural generators for the v0.1 item game.

The generators create only hidden game state.  Transition rules live in
``game.py`` so the six cases remain instances of one mechanism.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Mapping

from .config import ItemGameConfig


DEFAULT_SYMBOLS = ("K", "Q", "M", "V", "T", "Z", "F", "L")
GENERATOR_NAMES = ("pure_collaboration", "mixed_incentive", "resource_conflict")
SUBTYPES = {
    "pure_collaboration": ("collaboration",),
    "mixed_incentive": ("exchange", "give_first", "request_surplus"),
    "resource_conflict": ("cannot_help", "refuse_harmful_request"),
}


@dataclass(frozen=True)
class ItemGameInstance:
    episode_seed: int
    generator: str
    subtype: str
    items: tuple[str, ...]
    goals: Mapping[str, frozenset[str]]
    holdings: Mapping[str, frozenset[str]]
    partner_event: str | None = None

    def goal(self, player: str) -> frozenset[str]:
        return self.goals[player]

    def holding(self, player: str) -> frozenset[str]:
        return self.holdings[player]


def _validate_config(config: ItemGameConfig) -> None:
    if config.generator not in GENERATOR_NAMES:
        raise ValueError(f"unknown item-game generator {config.generator!r}")
    if config.subtype is not None and config.subtype not in SUBTYPES[config.generator]:
        raise ValueError(f"subtype {config.subtype!r} is invalid for {config.generator!r}")
    if config.max_ego_steps < 1:
        raise ValueError("max_ego_steps must be positive")
    if config.communication_budget < 0:
        raise ValueError("communication_budget must be nonnegative")
    if not 6 <= len(config.item_vocabulary) <= 8 or len(set(config.item_vocabulary)) != len(config.item_vocabulary):
        raise ValueError("item_vocabulary must contain 6 to 8 unique item names")


def _labels(seed: int, config: ItemGameConfig) -> dict[str, str]:
    symbols = list(DEFAULT_SYMBOLS[: len(config.item_vocabulary)])
    if config.randomize_items:
        random.Random(seed + 17_311).shuffle(symbols)
    vocabulary = list(config.item_vocabulary)
    if config.randomize_items:
        random.Random(seed + 91_027).shuffle(vocabulary)
    return dict(zip(symbols, vocabulary))


def _instance(
    seed: int,
    generator: str,
    subtype: str,
    goals: dict[str, set[str]],
    holdings: dict[str, set[str]],
    partner_event: str | None = None,
    config: ItemGameConfig | None = None,
) -> ItemGameInstance:
    config = config or ItemGameConfig(generator=generator, subtype=subtype)
    labels = _labels(seed, config)
    # Keep two goal-irrelevant distractors in every generated episode.  The
    # templates below already reserve them, but this check catches regressions.
    irrelevant_instances = sum(len(holdings[player] - goals[player]) for player in holdings)
    if irrelevant_instances < 2:
        raise AssertionError("item-game template must contain two irrelevant distractors")
    return ItemGameInstance(
        episode_seed=seed,
        generator=generator,
        subtype=subtype,
        # The configured vocabulary is part of the episode even when a
        # distractor is held by nobody; this keeps every episode in the fixed
        # 6--8 item-type range and prevents the action space from shrinking by
        # structural subtype.
        items=tuple(labels[symbol] for symbol in DEFAULT_SYMBOLS[: len(config.item_vocabulary)]),
        goals={
            player: frozenset(labels[item] for item in values)
            for player, values in goals.items()
        },
        holdings={
            player: frozenset(labels[item] for item in values)
            for player, values in holdings.items()
        },
        partner_event=(labels[partner_event] if partner_event is not None else None),
    )


class PureCollaborationGenerator:
    name = "pure_collaboration"

    def generate(self, seed: int, config: ItemGameConfig | None = None) -> ItemGameInstance:
        return _instance(
            seed,
            self.name,
            "collaboration",
            goals={"EGO": {"K", "Q", "V"}, "P1": {"K", "Q", "V"}},
            holdings={"EGO": {"K", "M"}, "P1": {"Q", "V", "T"}},
            config=config,
        )


class MixedIncentiveGenerator:
    name = "mixed_incentive"

    def generate(self, seed: int, subtype: str = "exchange", config: ItemGameConfig | None = None) -> ItemGameInstance:
        if isinstance(subtype, ItemGameConfig):
            config, subtype = subtype, (subtype.subtype or "exchange")
        if subtype not in SUBTYPES[self.name]:
            raise ValueError(f"unknown mixed-incentive subtype {subtype!r}")
        if subtype == "request_surplus":
            goals = {"EGO": {"K", "Q"}, "P1": {"T", "Z"}}
            holdings = {"EGO": {"K", "M", "V"}, "P1": {"T", "Z", "Q", "F"}}
            if config is not None and len(config.item_vocabulary) < 7:
                holdings = {"EGO": {"K", "M", "V"}, "P1": {"T", "Z", "Q", "M"}}
            event = None
        else:
            goals = {"EGO": {"K", "Q"}, "P1": {"V", "T"}}
            holdings = {"EGO": {"K", "V", "M"}, "P1": {"Q", "T", "Z"}}
            event = "V" if subtype == "give_first" else None
        return _instance(seed, self.name, subtype, goals, holdings, event, config)


class ResourceConflictGenerator:
    name = "resource_conflict"

    def generate(self, seed: int, subtype: str = "cannot_help", config: ItemGameConfig | None = None) -> ItemGameInstance:
        if isinstance(subtype, ItemGameConfig):
            config, subtype = subtype, (subtype.subtype or "cannot_help")
        if subtype not in SUBTYPES[self.name]:
            raise ValueError(f"unknown resource-conflict subtype {subtype!r}")
        if subtype == "cannot_help":
            goals = {"EGO": {"K", "Q"}, "P1": {"Q", "T"}, "P2": {"Z", "F"}}
            holdings = {
                "EGO": {"K", "M"},
                "P1": {"Q", "T", "V"},
                "P2": {"Q", "Z", "F", "L"},
            }
            if config is not None and len(config.item_vocabulary) < 8:
                # Six opaque item types are enough when the two irrelevant
                # distractors are held by more than one agent.
                goals = {"EGO": {"K", "Q"}, "P1": {"Q", "T"}, "P2": {"Z", "V"}}
                holdings = {"EGO": {"K", "V"}, "P1": {"Q", "T", "M"}, "P2": {"Q", "Z", "V", "M"}}
        else:
            # Ego starts one useful item short.  P1's request for Q is
            # harmful because Q is critical to Ego, while P2 owns the other
            # missing item as surplus and can be used for a safe reroute.
            goals = {
                "EGO": {"K", "Q", "V"},
                "P1": {"Q", "T"},
                "P2": {"M", "Z"},
            }
            holdings = {
                "EGO": {"K", "Q", "M"},
                "P1": {"T", "Z"},
                "P2": {"V", "M", "Z", "T"},
            }
        event = "Q" if subtype == "refuse_harmful_request" else None
        return _instance(seed, self.name, subtype, goals, holdings, event, config)


def generate_instance(
    seed: int,
    generator: str = "pure_collaboration",
    subtype: str | None = None,
    config: ItemGameConfig | None = None,
) -> ItemGameInstance:
    if isinstance(subtype, ItemGameConfig):
        config, subtype = subtype, None
    if config is None:
        config = ItemGameConfig(generator=generator, subtype=subtype)
    elif generator != "pure_collaboration" and config.generator != generator:
        config = replace(config, generator=generator)
    if subtype is not None and config.subtype != subtype:
        config = replace(config, subtype=subtype)
    _validate_config(config)
    generator = config.generator
    subtype = subtype or config.subtype
    if generator == "pure_collaboration":
        if subtype not in (None, "collaboration"):
            raise ValueError("pure_collaboration has no selectable subtype")
        return PureCollaborationGenerator().generate(seed, config)
    if generator == "mixed_incentive":
        return MixedIncentiveGenerator().generate(seed, subtype or "exchange", config)
    return ResourceConflictGenerator().generate(seed, subtype or "cannot_help", config)
