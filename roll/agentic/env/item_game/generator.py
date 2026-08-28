"""Deterministic structural generators for the structured item game.

The generators create only hidden game state.  Transition rules live in
``game.py`` so the subtypes remain instances of one mechanism.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Mapping

from .config import ItemGameConfig


DEFAULT_SYMBOLS = ("K", "Q", "M", "V", "T", "Z", "F", "L")
GENERATOR_NAMES = ("pure_collaboration", "mixed_incentive", "resource_conflict")
SUBTYPES = {
    "pure_collaboration": ("collaboration",),
    "mixed_incentive": (
        "exchange",
        "give_first",
        "request_surplus",
        "request_surplus_reroute",
        "respond_to_give_request",
    ),
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
    # Internal-only metadata for the rerouting subtype. Never rendered to Ego.
    partner_policies: Mapping[str, str] = field(default_factory=dict)
    partner_roles: Mapping[str, str] = field(default_factory=dict)
    # Metadata for the RespondToGiveRequest subtype. Never rendered to Ego.
    active_partner: str | None = None
    request_case: str | None = None

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
        if not set(ego_goal) & set(ego_holdings) or not set(ego_goal) & set(instance.holdings["P1"]):
            raise AssertionError("collaboration requires both agents to contribute a goal item")

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

    elif instance.subtype == "request_surplus_reroute":
        if set(instance.goals) != {"EGO", "P1", "P2"}:
            raise AssertionError("request_surplus_reroute requires two partners")
        if instance.partner_event is not None:
            raise AssertionError("request_surplus_reroute has no initial partner event")
        critical = set(ego_goal) - set(ego_holdings)
        if len(critical) != 1:
            raise AssertionError("reroute must have exactly one missing Ego goal item")
        target = next(iter(critical))
        if not all(target in instance.holdings[partner] for partner in ("P1", "P2")):
            raise AssertionError("both reroute partners must hold the target item")
        role_values = set(instance.partner_roles.values())
        if role_values not in (
            {"HELPER", "BLOCKER_INFERABLE"},
            {"HELPER", "BLOCKER_HIDDEN_UNWILLING"},
        ):
            raise AssertionError("reroute must designate one helper and one blocker")
        helper = next(partner for partner, role in instance.partner_roles.items() if role == "HELPER")
        blocker = next(
            partner
            for partner, role in instance.partner_roles.items()
            if role in {"BLOCKER_INFERABLE", "BLOCKER_HIDDEN_UNWILLING"}
        )
        if instance.goals[helper] == ego_goal or instance.goals[blocker] == ego_goal:
            raise AssertionError("reroute partner goals must differ from Ego goal")
        if not _goal_satisfied(instance.goals[helper], instance.holdings[helper]):
            raise AssertionError("helper must already satisfy its own goal")
        if target in instance.goals[helper] or not _goal_satisfied(
            instance.goals[helper], set(instance.holdings[helper]) - {target}
        ):
            raise AssertionError("helper target item must be genuine surplus")
        blocker_role = instance.partner_roles[blocker]
        if blocker_role == "BLOCKER_INFERABLE":
            if target not in instance.goals[blocker] or _goal_satisfied(
                instance.goals[blocker], set(instance.holdings[blocker]) - {target}
            ):
                raise AssertionError("inferable blocker target must be critical")
            if instance.partner_policies.get(blocker) != "HELPFUL":
                raise AssertionError("inferable blocker must use the helpful policy")
        elif blocker_role == "BLOCKER_HIDDEN_UNWILLING":
            if target in instance.goals[blocker] or not _goal_satisfied(
                instance.goals[blocker], set(instance.holdings[blocker]) - {target}
            ):
                raise AssertionError("hidden-unwilling blocker target must be surplus")
            if instance.partner_policies.get(blocker) != "UNWILLING":
                raise AssertionError("hidden-unwilling blocker must use the unwilling policy")
        else:
            raise AssertionError(f"unknown reroute blocker role {blocker_role!r}")

    elif instance.subtype == "respond_to_give_request":
        if len(players) != 2 or "EGO" not in players:
            raise AssertionError("respond_to_give_request requires EGO and one active partner")
        partner = instance.active_partner
        if partner is None or partner not in players or partner == "EGO":
            raise AssertionError("respond_to_give_request must identify its active partner")
        if instance.partner_event is None or instance.partner_event not in ego_holdings:
            raise AssertionError("give request must target an item held by Ego")
        requested = instance.partner_event
        if requested not in instance.goals[partner] or requested in instance.holdings[partner]:
            raise AssertionError("partner request must target a missing partner goal item")
        if not _goal_satisfied(instance.goals[partner], set(instance.holdings[partner]) | {requested}):
            raise AssertionError("partner must be able to complete its goal after receiving the request")
        if instance.request_case not in {"safe", "harmful"}:
            raise AssertionError("give request must be either safe or harmful")
        ego_after_give = set(ego_holdings) - {requested}
        if instance.request_case == "safe":
            if requested in ego_goal or not _goal_satisfied(ego_goal, ego_after_give):
                raise AssertionError("safe give must leave Ego's goal satisfied")
        elif requested not in ego_goal or _goal_satisfied(ego_goal, ego_after_give):
            raise AssertionError("harmful give must remove an Ego-critical item")
        if not instance.partner_policies.get(partner, "ACTIVE_REQUESTER") == "ACTIVE_REQUESTER":
            raise AssertionError("give requester must use the explicit active-requester policy")

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


def _labels(
    seed: int,
    config: ItemGameConfig,
    symbols: tuple[str, ...] | None = None,
) -> dict[str, str]:
    symbols = list(symbols or DEFAULT_SYMBOLS[: len(config.item_vocabulary)])
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
    symbols: tuple[str, ...] | None = None,
    partner_policies: Mapping[str, str] | None = None,
    partner_roles: Mapping[str, str] | None = None,
    active_partner: str | None = None,
    request_case: str | None = None,
) -> ItemGameInstance:
    config = config or ItemGameConfig(generator=generator, subtype=subtype)
    symbols = symbols or tuple(DEFAULT_SYMBOLS[: len(config.item_vocabulary)])
    labels = _labels(seed, config, symbols)
    instance = ItemGameInstance(
        episode_seed=seed,
        generator=generator,
        subtype=subtype,
        # The configured vocabulary is part of the episode even when a
        # distractor is held by nobody; this keeps every episode in the fixed
        # 6--8 item-type range and prevents the action space from shrinking by
        # structural subtype.
        items=tuple(labels[symbol] for symbol in symbols),
        goals={
            player: frozenset(labels[item] for item in values)
            for player, values in goals.items()
        },
        holdings={
            player: frozenset(labels[item] for item in values)
            for player, values in holdings.items()
        },
        partner_event=(labels[partner_event] if partner_event is not None else None),
        partner_policies=dict(partner_policies or {}),
        partner_roles=dict(partner_roles or {}),
        active_partner=active_partner,
        request_case=request_case,
    )
    validate_instance(instance)
    return instance


class PureCollaborationGenerator:
    name = "pure_collaboration"

    def generate(self, seed: int, config: ItemGameConfig | None = None) -> ItemGameInstance:
        config = config or ItemGameConfig(generator=self.name, subtype="collaboration")
        rng = random.Random(seed + 61_731)
        available_symbols = list(DEFAULT_SYMBOLS[: len(config.item_vocabulary)])
        rng.shuffle(available_symbols)
        universe_size = rng.randint(6, len(available_symbols))
        symbols = tuple(available_symbols[:universe_size])

        goal_size = rng.randint(2, min(4, universe_size - 2))
        goal = set(rng.sample(list(symbols), goal_size))
        shuffled_goal = sorted(goal)
        rng.shuffle(shuffled_goal)
        split = rng.randint(1, goal_size - 1)
        ego_goal = set(shuffled_goal[:split])
        p1_goal = set(shuffled_goal[split:])

        distractors = [symbol for symbol in symbols if symbol not in goal]
        rng.shuffle(distractors)
        ego_holdings = set(ego_goal) | {distractors.pop()}
        p1_holdings = set(p1_goal) | {distractors.pop()}
        for item in distractors:
            target = rng.choice((ego_holdings, p1_holdings, None))
            if target is not None:
                target.add(item)

        return _instance(
            seed,
            self.name,
            "collaboration",
            goals={"EGO": goal, "P1": goal},
            holdings={"EGO": ego_holdings, "P1": p1_holdings},
            config=config,
            symbols=symbols,
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
        elif subtype == "request_surplus_reroute":
            return self._generate_reroute(seed, config)
        elif subtype == "respond_to_give_request":
            return self._generate_respond_to_give_request(seed, config)
        else:
            goals = {"EGO": {"K", "Q"}, "P1": {"V", "T"}}
            holdings = {"EGO": {"K", "V", "M"}, "P1": {"Q", "T", "Z"}}
            event = "V" if subtype == "give_first" else None
        return _instance(seed, self.name, subtype, goals, holdings, event, config)

    def _generate_reroute(self, seed: int, config: ItemGameConfig | None) -> ItemGameInstance:
        rng = random.Random(seed + 73_419)
        symbols = list(DEFAULT_SYMBOLS[: len((config or ItemGameConfig()).item_vocabulary)])
        rng.shuffle(symbols)
        target, ego_required, helper_goal_a, helper_goal_b, blocker_required, spare = symbols[:6]
        helper_goal = {helper_goal_a, helper_goal_b}
        blocker_mode = rng.choice(("inferable", "hidden_unwilling"))
        helper = rng.choice(("P1", "P2"))
        blocker = "P2" if helper == "P1" else "P1"

        goals = {
            "EGO": {ego_required, target},
            helper: helper_goal,
            blocker: ({target, blocker_required} if blocker_mode == "inferable" else {blocker_required, spare}),
        }
        holdings = {
            "EGO": {ego_required, spare},
            helper: helper_goal | {target, spare},
            blocker: (
                {target, blocker_required, spare}
                if blocker_mode == "inferable"
                else {blocker_required, spare, target}
            ),
        }
        for extra in symbols[6:]:
            rng.choice((holdings["EGO"], holdings[helper], holdings[blocker])).add(extra)
        roles = {helper: "HELPER", blocker: "BLOCKER_INFERABLE" if blocker_mode == "inferable" else "BLOCKER_HIDDEN_UNWILLING"}
        policies = {helper: "HELPFUL", blocker: "HELPFUL" if blocker_mode == "inferable" else "UNWILLING"}
        return _instance(
            seed,
            self.name,
            "request_surplus_reroute",
            goals=goals,
            holdings=holdings,
            config=config,
            symbols=tuple(symbols),
            partner_policies=policies,
            partner_roles=roles,
        )

    def _generate_respond_to_give_request(
        self, seed: int, config: ItemGameConfig | None
    ) -> ItemGameInstance:
        rng = random.Random(seed + 91_247)
        config = config or ItemGameConfig(generator=self.name, subtype="respond_to_give_request")
        universe_size = rng.randint(6, len(config.item_vocabulary))
        symbols = list(DEFAULT_SYMBOLS[:universe_size])
        rng.shuffle(symbols)
        requested = symbols[0]
        active_partner = rng.choice(("P1", "P2", "P3"))
        request_case = rng.choice(("safe", "harmful"))

        ego_goal_size = rng.randint(1, min(3, universe_size - 2))
        partner_goal_size = rng.randint(1, min(3, universe_size - 1))
        remaining = symbols[1:]
        if request_case == "safe":
            ego_goal = set(rng.sample(remaining, ego_goal_size))
        else:
            ego_goal = {requested}
            ego_goal.update(rng.sample(remaining, ego_goal_size - 1))

        partner_goal = {requested}
        partner_goal.update(rng.sample(remaining, partner_goal_size - 1))
        ego_holdings = set(ego_goal) | {requested}
        partner_holdings = set(partner_goal) - {requested}

        # Keep holdings variable while guaranteeing the base validator's two
        # distractors.  For a harmful request, the requested item is goal-
        # critical, so two additional non-goal holdings are required.
        ego_extra_pool = [item for item in symbols if item not in ego_goal and item != requested]
        minimum_ego_extras = 2 if request_case == "harmful" else 1
        ego_extra_count = rng.randint(minimum_ego_extras, min(3, len(ego_extra_pool)))
        ego_holdings.update(rng.sample(ego_extra_pool, ego_extra_count))
        partner_extra_pool = [item for item in symbols if item not in partner_goal]
        partner_extra_count = rng.randint(0, min(2, len(partner_extra_pool)))
        partner_holdings.update(rng.sample(partner_extra_pool, partner_extra_count))

        goals = {"EGO": ego_goal, active_partner: partner_goal}
        holdings = {"EGO": ego_holdings, active_partner: partner_holdings}
        return _instance(
            seed,
            self.name,
            "respond_to_give_request",
            goals=goals,
            holdings=holdings,
            partner_event=requested,
            config=config,
            symbols=tuple(symbols),
            partner_policies={active_partner: "ACTIVE_REQUESTER"},
            active_partner=active_partner,
            request_case=request_case,
        )


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
