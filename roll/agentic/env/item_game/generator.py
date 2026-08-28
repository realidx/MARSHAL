"""Deterministic structural generators for the v0.3 item game.

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


def _goal_satisfied(goal: set[str] | frozenset[str], holdings: set[str] | frozenset[str]) -> bool:
    return set(goal).issubset(holdings)


def _after_exchange(
    ego_goal: set[str] | frozenset[str],
    ego_holdings: set[str] | frozenset[str],
    partner_goal: set[str] | frozenset[str],
    partner_holdings: set[str] | frozenset[str],
    give: str,
    receive: str,
) -> tuple[set[str], set[str]]:
    ego_after = (set(ego_holdings) - {give}) | {receive}
    partner_after = (set(partner_holdings) - {receive}) | {give}
    return ego_after, partner_after


def _strictly_beneficial_exchange(
    ego_goal: set[str] | frozenset[str],
    ego_holdings: set[str] | frozenset[str],
    partner_goal: set[str] | frozenset[str],
    partner_holdings: set[str] | frozenset[str],
    give: str,
    receive: str,
) -> bool:
    if give not in ego_holdings or receive not in partner_holdings:
        return False
    ego_after, partner_after = _after_exchange(
        ego_goal, ego_holdings, partner_goal, partner_holdings, give, receive
    )
    ego_before_score = len(set(ego_goal) & set(ego_holdings))
    partner_before_score = len(set(partner_goal) & set(partner_holdings))
    ego_after_score = len(set(ego_goal) & ego_after)
    partner_after_score = len(set(partner_goal) & partner_after)
    ego_benefits = _goal_satisfied(ego_goal, ego_after) or ego_after_score > ego_before_score
    partner_benefits = _goal_satisfied(partner_goal, partner_after) or partner_after_score > partner_before_score
    return ego_benefits and partner_benefits


def validate_instance(instance: ItemGameInstance) -> None:
    """Validate structural and subtype-specific mathematical invariants."""

    players = set(instance.goals)
    if "EGO" not in players or len(players) not in (2, 3):
        raise AssertionError("Item Game must contain EGO and one or two partners")
    if set(instance.holdings) != players:
        raise AssertionError("goals and holdings must contain the same players")
    item_set = set(instance.items)
    if not item_set:
        raise AssertionError("item vocabulary must be nonempty")
    if any(not set(goal).issubset(item_set) for goal in instance.goals.values()):
        raise AssertionError("goals must use only episode items")
    if any(not set(holding).issubset(item_set) for holding in instance.holdings.values()):
        raise AssertionError("holdings must use only episode items")
    if len(set().union(*(set(instance.holdings[p]) - set(instance.goals[p]) for p in players))) < 2:
        raise AssertionError("each instance must contain at least two goal-irrelevant distractors")

    ego_goal = instance.goals["EGO"]
    ego_holdings = instance.holdings["EGO"]
    if instance.subtype == "collaboration":
        if set(instance.goals) != {"EGO", "P1"}:
            raise AssertionError("collaboration must contain exactly EGO and P1")
        if instance.goals["P1"] != ego_goal:
            raise AssertionError("collaboration requires identical goals")
        if _goal_satisfied(ego_goal, ego_holdings) or _goal_satisfied(
            instance.goals["P1"], instance.holdings["P1"]
        ):
            raise AssertionError("collaboration agents must each need cooperation")
        if not _goal_satisfied(
            ego_goal, set(ego_holdings) | set(instance.holdings["P1"])
        ):
            raise AssertionError("collaboration pool must cover the shared goal")

    elif instance.subtype == "exchange":
        partner = "P1"
        if _goal_satisfied(ego_goal, ego_holdings) or _goal_satisfied(
            instance.goals[partner], instance.holdings[partner]
        ):
            raise AssertionError("exchange must require both agents to improve")
        if not any(
            _strictly_beneficial_exchange(
                ego_goal,
                ego_holdings,
                instance.goals[partner],
                instance.holdings[partner],
                give,
                receive,
            )
            for give in ego_holdings
            for receive in instance.holdings[partner]
        ):
            raise AssertionError("exchange must contain a mutual-benefit exchange")

    elif instance.subtype == "give_first":
        partner = "P1"
        event = instance.partner_event
        if event is None or event not in ego_holdings:
            raise AssertionError("give_first requires an initial item request from P1")
        if event in ego_goal:
            raise AssertionError("give_first request must be non-critical to EGO")
        partner_after = set(instance.holdings[partner]) | {event}
        if not _goal_satisfied(instance.goals[partner], partner_after):
            raise AssertionError("give_first concession must make P1's goal feasible")
        if not any(
            item in partner_after
            and item not in instance.goals[partner]
            and item not in ego_holdings
            and item in ego_goal
            for item in partner_after
        ):
            raise AssertionError("give_first must expose an Ego-needed surplus after concession")

    elif instance.subtype == "request_surplus":
        partner = "P1"
        if _goal_satisfied(ego_goal, ego_holdings) or not _goal_satisfied(
            instance.goals[partner], instance.holdings[partner]
        ):
            raise AssertionError("request_surplus requires Ego to need help and P1 to be satisfied")
        if not any(
            item in instance.holdings[partner]
            and item not in instance.goals[partner]
            and item in ego_goal
            and item not in ego_holdings
            for item in instance.items
        ):
            raise AssertionError("request_surplus requires a goal-relevant P1 surplus")

    elif instance.subtype == "cannot_help":
        if set(instance.goals) != {"EGO", "P1", "P2"}:
            raise AssertionError("cannot_help requires two partners")
        critical = set(ego_goal) - set(ego_holdings)
        if not critical:
            raise AssertionError("cannot_help requires Ego to miss a goal item")
        if not any(
            item in instance.holdings["P1"]
            and not _goal_satisfied(instance.goals["P1"], set(instance.holdings["P1"]) - {item})
            and item in ego_goal
            for item in critical
        ):
            raise AssertionError("P1 must hold an Ego-needed item that P1 cannot give")
        if not any(
            item in instance.holdings["P2"]
            and _goal_satisfied(instance.goals["P2"], set(instance.holdings["P2"]) - {item})
            and item in critical
            for item in critical
        ):
            raise AssertionError("P2 must hold a safe surplus reroute item")

    elif instance.subtype == "refuse_harmful_request":
        event = instance.partner_event
        if set(instance.goals) != {"EGO", "P1"}:
            raise AssertionError("refuse_harmful_request must isolate one requesting partner")
        if event is None or event not in ego_holdings or event not in ego_goal:
            raise AssertionError("harmful request must target an Ego goal item")
        if not _goal_satisfied(ego_goal, ego_holdings):
            raise AssertionError("refusal case should permit safe singleton commit after refusal")
        if _goal_satisfied(ego_goal, set(ego_holdings) - {event}):
            raise AssertionError("requested item must be critical to Ego")


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
    instance = ItemGameInstance(
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
    validate_instance(instance)
    return instance


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
            goals = {"EGO": {"K", "Q"}, "P1": {"Q", "T"}, "P2": {"Z", "V"}}
            holdings = {
                "EGO": {"K", "M"},
                "P1": {"Q", "T", "M"},
                "P2": {"Q", "Z", "V", "M"},
            }
        else:
            goals = {
                "EGO": {"K", "Q"},
                "P1": {"Q", "T"},
            }
            holdings = {
                "EGO": {"K", "Q", "M", "V"},
                "P1": {"T", "Z"},
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
