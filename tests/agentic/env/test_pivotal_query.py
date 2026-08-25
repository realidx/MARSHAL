import importlib.util
from pathlib import Path
import sys
import types

import pytest


ENV_DIR = Path(__file__).parents[3] / "roll/agentic/env"
PACKAGE = "_pivotal_query_test_env"


def _package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_package(PACKAGE, ENV_DIR)
_package(f"{PACKAGE}.pivotal_query", ENV_DIR / "pivotal_query")
_load(f"{PACKAGE}.base", ENV_DIR / "base.py")
CONFIG = _load(f"{PACKAGE}.pivotal_query.config", ENV_DIR / "pivotal_query/config.py")
TYPES = _load(f"{PACKAGE}.pivotal_query.types", ENV_DIR / "pivotal_query/types.py")
ORACLE = _load(f"{PACKAGE}.pivotal_query.oracle", ENV_DIR / "pivotal_query/oracle.py")
GENERATOR = _load(f"{PACKAGE}.pivotal_query.generator", ENV_DIR / "pivotal_query/generator.py")
GAME = _load(f"{PACKAGE}.pivotal_query.game", ENV_DIR / "pivotal_query/game.py")
METRICS = _load(f"{PACKAGE}.pivotal_query.metrics", ENV_DIR / "pivotal_query/metrics.py")
ENV = _load(f"{PACKAGE}.pivotal_query.env", ENV_DIR / "pivotal_query/env.py")

PivotalQueryConfig = CONFIG.PivotalQueryConfig
PivotalQueryEnv = ENV.PivotalQueryEnv
PivotalQueryGame = GAME.PivotalQueryGame
ExactQueryOracle = ORACLE.ExactQueryOracle
PivotalQueryInstance = TYPES.PivotalQueryInstance
World = TYPES.World
generate_instance = GENERATOR.generate_instance
generate_matched_family = GENERATOR.generate_matched_family
aggregate_metrics = METRICS.aggregate_pivotal_query_metrics


def test_matched_family_preserves_labels_actual_world_and_family_id():
    family = generate_matched_family(73)
    instances = list(family.values())
    reference = instances[0]
    for instance in instances[1:]:
        assert instance.family_id == reference.family_id
        assert instance.fact_names == reference.fact_names
        assert instance.partner_names == reference.partner_names
        assert instance.partner_knowledge == reference.partner_knowledge
        assert instance.option_names == reference.option_names
        assert instance.actual_values == reference.actual_values
        assert instance.pivotal_fact == reference.pivotal_fact


def test_exact_condition_oracles_separate_missing_from_valuable_information():
    family = generate_matched_family(19)
    decisions = {
        condition: ExactQueryOracle(instance).solve(instance.known_dict()) for condition, instance in family.items()
    }
    assert decisions["known_pivotal"].should_ask is False
    assert decisions["ask_necessary"].should_ask is True
    assert decisions["costly_query"].should_ask is False
    assert decisions["irrelevant_uncertainty"].should_ask is False

    necessary = family["ask_necessary"]
    owner = next(
        partner for partner in necessary.partner_names if necessary.partner_knows(partner, necessary.pivotal_fact)
    )
    assert decisions["ask_necessary"].optimal_actions == (f"ASK {owner} {necessary.pivotal_fact}",)
    assert decisions["ask_necessary"].best_act_value == pytest.approx(6.0)
    assert decisions["ask_necessary"].value == pytest.approx(6.75)


def test_oracle_plans_through_queries_with_joint_but_not_myopic_value():
    worlds = tuple(
        World(
            values=(left, right),
            probability=0.25,
            payoffs=(float((left == right)), float((left != right))),
        )
        for left in ("0", "1")
        for right in ("0", "1")
    )
    instance = PivotalQueryInstance(
        family_id="xor",
        condition="joint",
        fact_names=("X", "Y"),
        fact_domains=(("0", "1"), ("0", "1")),
        partner_names=("Alice", "Bob"),
        partner_knowledge=(("X",), ("Y",)),
        option_names=("EQUAL", "DIFFERENT"),
        worlds=worlds,
        initially_known=(),
        query_costs=((0.1, 0.1), (0.1, 0.1)),
        actual_values=("0", "1"),
        pivotal_fact="X",
    )
    decision = ExactQueryOracle(instance).solve({})
    assert decision.best_act_value == pytest.approx(0.5)
    assert decision.value == pytest.approx(0.8)
    assert decision.should_ask is True
    assert set(decision.optimal_actions) == {"ASK Alice X", "ASK Bob Y"}


def test_game_answers_truthfully_then_stops_when_information_is_sufficient():
    instance = generate_instance(31, "ask_necessary")
    game = PivotalQueryGame(instance)
    target = instance.pivotal_fact
    owner = next(partner for partner in instance.partner_names if instance.partner_knows(partner, target))
    observation, reward, done, first_info = game.step(f"ASK {owner} {target}")
    assert observation == f"{owner} answers: {target} = {instance.actual_value(target)}."
    assert reward == pytest.approx(-0.25)
    assert done is False
    assert first_info["optimal_action"] == 1.0

    next_decision = game.oracle.solve(
        game.known,
        game.available_queries(),
        game.max_queries - len(game.attempted_queries),
    )
    assert next_decision.should_ask is False
    best_act = max(next_decision.act_values, key=lambda pair: pair[1])[0]
    _, _, done, terminal = game.step(best_act)
    assert done is True
    assert terminal["necessary_ask_hit"] == 1.0
    assert terminal["first_query_targeted"] == 1.0
    assert terminal["post_sufficiency_excess_communication"] == 0.0


def test_asking_after_sufficiency_is_counted_as_excess_communication():
    instance = generate_instance(44, "known_pivotal")
    game = PivotalQueryGame(instance)
    partner, irrelevant = next(query for query in game.available_queries() if instance.partner_knows(*query))
    game.step(f"ASK {partner} {irrelevant}")
    decision = game.oracle.solve(
        game.known,
        game.available_queries(),
        game.max_queries - len(game.attempted_queries),
    )
    best_act = max(decision.act_values, key=lambda pair: pair[1])[0]
    _, _, _, terminal = game.step(best_act)
    assert terminal["unnecessary_ask"] == 1.0
    assert terminal["post_sufficiency_excess_communication"] == 1.0


def test_metric_aggregation_uses_the_right_condition_denominators():
    infos = [
        {
            "initial_should_ask": 1.0,
            "first_action_ask": 1.0,
            "necessary_ask_hit": 1.0,
            "unnecessary_ask": 0.0,
            "first_query_targeted": 1.0,
            "first_query_fact_relevant": 1.0,
            "first_query_source_capable": 1.0,
            "first_query_route_optimal": 1.0,
            "total_query_regret": 0.0,
            "post_sufficiency_excess_communication": 0.0,
            "first_decision_optimal": 1.0,
            "num_asks": 1.0,
            "unproductive_queries": 0.0,
        },
        {
            "initial_should_ask": 0.0,
            "first_action_ask": 1.0,
            "necessary_ask_hit": 0.0,
            "unnecessary_ask": 1.0,
            "first_query_targeted": 0.0,
            "first_query_fact_relevant": 0.0,
            "first_query_source_capable": 1.0,
            "first_query_route_optimal": 0.0,
            "total_query_regret": 0.25,
            "post_sufficiency_excess_communication": 1.0,
            "first_decision_optimal": 0.0,
            "num_asks": 1.0,
            "unproductive_queries": 0.0,
        },
    ]
    metrics = aggregate_metrics(infos)
    assert metrics["necessary_ask_recall"] == 1.0
    assert metrics["unnecessary_ask_rate"] == 1.0
    assert metrics["targeted_first_query_rate"] == 1.0
    assert metrics["relevant_fact_first_query_rate"] == 1.0
    assert metrics["capable_source_first_query_rate"] == 1.0
    assert metrics["first_decision_optimal_rate"] == 0.5


def test_roll_adapter_is_deterministic_and_emits_symbolic_diagnostics():
    env = PivotalQueryEnv(PivotalQueryConfig(condition="ask_necessary"))
    initial, automatic = env.reset(seed=52)
    first_instance = env.game.instance
    assert automatic == []
    assert "Payoff and prior table" in initial["observation"]
    owner = next(
        partner
        for partner in first_instance.partner_names
        if first_instance.partner_knows(partner, first_instance.pivotal_fact)
    )
    assert f"ASK {owner} {first_instance.pivotal_fact}" in initial["legal_actions"].values()
    env.reset(seed=52)
    assert env.game.instance == first_instance

    action = f"ASK {owner} {env.game.instance.pivotal_fact}"
    result = env.step(action)[0]
    assert result["current_player"] == 0
    assert result["next_player"] == 0
    assert result["rewards"] == [-0.25, 0.0]
    assert result["info"]["oracle_should_ask"] == 1.0
    assert result["info"]["optimal_action"] == 1.0


def test_roll_adapter_parser_requires_one_legal_structured_action():
    env = PivotalQueryEnv(PivotalQueryConfig(condition="ask_necessary"))
    initial, _ = env.reset(seed=5)
    action = next(iter(initial["legal_actions"].values()))
    response = f"<answer>{action}</answer>"
    assert env.recover_action(response, initial["legal_actions"]) == action
    assert (
        env.recover_action(
            f"<reason>brief</reason><answer>{action}</answer>",
            initial["legal_actions"],
        )
        == action
    )
    assert env.recover_action(f"<reason>x</reason><answer>{action} extra</answer>", initial["legal_actions"]) is None


def test_ask_after_budget_is_scored_as_terminal_policy_failure():
    env = PivotalQueryEnv(PivotalQueryConfig(condition="known_pivotal", max_queries=3))
    env.reset(seed=17)
    assert env.game is not None
    for _ in range(3):
        ask = next(action for action in env.game.legal_actions() if action.startswith("ASK "))
        result = env.step(ask)[0]
        assert result["done"] is False

    assert all(action.startswith("ACT ") for action in env.game.legal_actions())
    terminal = env.handle_invalid_response(
        player_id=0,
        actions=["ASK Alice F1"],
        raw_response="<answer>ASK Alice F1</answer>",
    )[0]
    assert terminal["done"] is True
    assert terminal["action"] == "ASK Alice F1"
    assert terminal["info"]["success"] is True
    assert terminal["info"]["administrative_terminal"] == 1.0
    assert terminal["info"]["policy_failure"] == 1.0
    assert terminal["info"]["illegal_ask_after_budget"] == 1.0
    assert terminal["info"]["player_0_success"] is False
    assert "artificial_truncation" not in terminal["info"]


def test_decision_rule_hint_is_an_explicit_prompt_intervention():
    neutral = PivotalQueryEnv(PivotalQueryConfig()).get_prompt()["user"]
    hinted = PivotalQueryEnv(PivotalQueryConfig(decision_rule_hint=True)).get_prompt()["user"]
    assert "expected decision value exceeds its cost" not in neutral
    assert "expected decision value exceeds its cost" in hinted


def test_right_fact_asked_to_wrong_partner_separates_what_from_whom():
    instance = generate_instance(61, "ask_necessary")
    game = PivotalQueryGame(instance)
    target = instance.pivotal_fact
    wrong_partner = next(partner for partner in instance.partner_names if not instance.partner_knows(partner, target))
    observation, reward, done, info = game.step(f"ASK {wrong_partner} {target}")
    assert observation == f"{wrong_partner} answers: I do not know {target}."
    assert reward == pytest.approx(-0.25)
    assert done is False
    assert target not in game.known
    assert info["query_fact_relevant"] == 1.0
    assert info["query_source_capable"] == 0.0
    assert info["query_route_optimal"] == 0.0
    assert info["unproductive_query"] == 1.0


@pytest.mark.parametrize("seed", range(20))
def test_exact_partner_aware_policy_is_optimal_across_matched_families(seed):
    for condition, instance in generate_matched_family(seed).items():
        game = PivotalQueryGame(instance)
        while not game.done:
            decision = game.oracle.solve(
                game.known,
                game.available_queries(),
                game.max_queries - len(game.attempted_queries),
            )
            if decision.should_ask:
                action = next(action for action in decision.optimal_actions if action.startswith("ASK "))
            else:
                action = next(action for action in decision.optimal_actions if action.startswith("ACT "))
            game.step(action)
        assert all(record["optimal_action"] == 1.0 for record in game.records)
        assert len(game.records) == (2 if condition == "ask_necessary" else 1)
