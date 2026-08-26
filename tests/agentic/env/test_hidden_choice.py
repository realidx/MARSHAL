import importlib.util
from dataclasses import replace
from pathlib import Path
import sys
import types

import pytest


ENV_DIR = Path(__file__).parents[3] / "roll/agentic/env"
PACKAGE = "_hidden_choice_test_env"


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
_package(f"{PACKAGE}.hidden_choice", ENV_DIR / "hidden_choice")
_load(f"{PACKAGE}.base", ENV_DIR / "base.py")
CONFIG = _load(f"{PACKAGE}.hidden_choice.config", ENV_DIR / "hidden_choice/config.py")
TYPES = _load(f"{PACKAGE}.hidden_choice.types", ENV_DIR / "hidden_choice/types.py")
ENUMERATOR = _load(f"{PACKAGE}.hidden_choice.enumerator", ENV_DIR / "hidden_choice/enumerator.py")
OBSERVATION = _load(f"{PACKAGE}.hidden_choice.observation", ENV_DIR / "hidden_choice/observation.py")
ORACLE = _load(f"{PACKAGE}.hidden_choice.oracle", ENV_DIR / "hidden_choice/oracle.py")
SANITY = _load(f"{PACKAGE}.hidden_choice.sanity", ENV_DIR / "hidden_choice/sanity.py")
GENERATOR = _load(f"{PACKAGE}.hidden_choice.generator", ENV_DIR / "hidden_choice/generator.py")
GAME = _load(f"{PACKAGE}.hidden_choice.game", ENV_DIR / "hidden_choice/game.py")
METRICS = _load(f"{PACKAGE}.hidden_choice.metrics", ENV_DIR / "hidden_choice/metrics.py")
ENV = _load(f"{PACKAGE}.hidden_choice.env", ENV_DIR / "hidden_choice/env.py")

HiddenChoiceConfig = CONFIG.HiddenChoiceConfig
HiddenChoiceEnv = ENV.HiddenChoiceEnv
HiddenChoiceGame = GAME.HiddenChoiceGame
OneShotVOIOracle = ORACLE.OneShotVOIOracle
generate_instance = GENERATOR.generate_instance
generate_matched_quartet = GENERATOR.generate_matched_quartet
generate_threshold_pair = GENERATOR.generate_threshold_pair
aggregate_metrics = METRICS.aggregate_hidden_choice_metrics
generate_observation = OBSERVATION.generate_observation
check_instance = SANITY.check_instance


def _best_act(game):
    decision = game.oracle.solve(game.known, allow_questions=not game.query_used)
    return next(action for action in decision.optimal_actions if action.startswith("ACT "))


def _wrong_act(game):
    decision = game.oracle.solve(game.known, allow_questions=not game.query_used)
    return next(
        f"ACT {option}"
        for option in game.instance.option_names
        if f"ACT {option}" not in decision.optimal_actions
    )


def test_matched_quartet_preserves_surface_labels_context_and_actual_world():
    quartet = generate_matched_quartet(73)
    reference = quartet["no_query"]
    for instance in quartet.values():
        assert instance.family_id == reference.family_id
        assert instance.context == reference.context
        assert instance.fact_names == reference.fact_names
        assert instance.fact_domains == reference.fact_domains
        assert instance.option_names == reference.option_names
        assert instance.actual_values == reference.actual_values
        assert instance.pivotal_fact == reference.pivotal_fact
        shared = set(instance.action_order) & set(reference.action_order)
        assert [action for action in instance.action_order if action in shared] == [
            action for action in reference.action_order if action in shared
        ]


@pytest.mark.parametrize("seed", range(30))
def test_generator_accepts_only_exact_condition_labels(seed):
    quartet = generate_matched_quartet(seed)
    no_query = OneShotVOIOracle(quartet["no_query"]).solve()
    necessary = OneShotVOIOracle(quartet["necessary_query"]).solve()
    irrelevant = OneShotVOIOracle(quartet["irrelevant_uncertainty"]).solve()
    selective = OneShotVOIOracle(quartet["selective_query"]).solve()

    assert no_query.should_ask is False
    assert all(value == pytest.approx(0.0) for _, value in no_query.gross_voi)
    assert necessary.should_ask is True
    assert len(necessary.best_questions) == 1
    assert irrelevant.should_ask is False
    assert all(value == pytest.approx(0.0) for _, value in irrelevant.gross_voi)
    assert selective.should_ask is True
    assert len(selective.best_questions) == 1
    distractors = [
        value for action, value in selective.gross_voi if action not in selective.best_questions
    ]
    assert len(distractors) == 2
    assert all(value == pytest.approx(0.0) for value in distractors)


def test_gross_voi_is_separate_from_communication_cost():
    instance = generate_instance(19, "necessary_query")
    cheap = OneShotVOIOracle(instance).solve()
    expensive = OneShotVOIOracle(replace(instance, communication_cost=2.0)).solve()
    assert cheap.value_act == pytest.approx(5.0 + int(dict(instance.context)["utility_shift"]))
    assert dict(cheap.gross_voi) == pytest.approx(dict(expensive.gross_voi))
    assert next(iter(dict(cheap.gross_voi).values())) == pytest.approx(0.5)
    assert cheap.should_ask is True
    assert expensive.should_ask is False


def test_cost_suppressed_has_positive_gross_but_negative_net_voi():
    instance = generate_instance(19, "cost_suppressed", HiddenChoiceConfig(margin_magnitude=0.25))
    decision = OneShotVOIOracle(instance).solve()
    report = check_instance(instance)
    assert 0.0 < report.max_gross_voi < instance.communication_cost
    assert decision.should_ask is False
    assert report.oracle_margin == pytest.approx(-0.125)


def test_forced_relevant_information_reveals_only_pivotal_fact():
    env = HiddenChoiceEnv(
        HiddenChoiceConfig(condition="selective_query", forced_information_fact="pivotal")
    )
    initial, _ = env.reset(seed=52)
    assert all(action.startswith("ACT ") for action in initial["legal_actions"].values())
    assert "Known hidden facts:" in initial["observation"]
    action = next(action for action in env.game.initial_decision.optimal_actions if action.startswith("ACT "))
    terminal = env.step(action)[0]
    assert terminal["info"]["forced_information"] == 1.0


def test_threshold_pair_changes_only_cost_and_crosses_oracle_boundary():
    cheap, expensive = generate_threshold_pair(17, gross_value=0.8)
    assert cheap.worlds == expensive.worlds
    assert cheap.actual_values == expensive.actual_values
    assert cheap.communication_cost == pytest.approx(0.3)
    assert expensive.communication_cost == pytest.approx(0.9)
    assert OneShotVOIOracle(cheap).solve().should_ask is True
    assert OneShotVOIOracle(expensive).solve().should_ask is False


@pytest.mark.parametrize("magnitude", [0.05, 0.25, 1.0])
def test_margin_sweep_constructs_exact_symmetric_oracle_margins(magnitude):
    config = HiddenChoiceConfig(margin_magnitude=magnitude)
    quartet = generate_matched_quartet(27, config)
    for condition, instance in quartet.items():
        report = check_instance(instance)
        expected = magnitude if condition in ("necessary_query", "selective_query") else -magnitude
        assert report.oracle_margin == pytest.approx(expected)


def test_structured_observation_pairs_hidden_and_full_information():
    instance = generate_instance(21, "selective_query")
    hidden = generate_observation(instance)
    full = generate_observation(instance, full_information=True)
    assert hidden.family_id == full.family_id
    assert hidden.worlds == full.worlds
    assert hidden.known_facts == ()
    assert hidden.unknown_facts == instance.fact_names
    assert hidden.available_questions == instance.questions
    assert full.known_facts == tuple(zip(instance.fact_names, instance.actual_values))
    assert full.unknown_facts == ()
    assert full.available_questions == ()


def test_one_ask_is_a_hard_state_transition_to_act_only():
    game = HiddenChoiceGame(generate_instance(31, "selective_query"))
    question = game.initial_decision.best_questions[0]
    observation, reward, done, info = game.step(question)
    assert observation.startswith("Partner answers:")
    assert reward == pytest.approx(-game.instance.communication_cost)
    assert done is False
    assert info["query_correct"] == 1.0
    assert all(action.startswith("ACT ") for action in game.legal_actions())
    with pytest.raises(ValueError, match="illegal Hidden Choice action"):
        game.step(question)


def test_failure_decomposition_covers_initiation_targeting_and_use():
    no_query = HiddenChoiceGame(generate_instance(5, "no_query"))
    no_query.step(_best_act(no_query))
    assert no_query.terminal_metrics()["correct_abstention"] == 1.0

    over_query = HiddenChoiceGame(generate_instance(5, "irrelevant_uncertainty"))
    over_query.step(next(action for action in over_query.legal_actions() if action.startswith("ASK ")))
    over_query.step(_best_act(over_query))
    assert over_query.terminal_metrics()["over_querying"] == 1.0
    assert over_query.terminal_metrics()["benchmark_success"] == 0.0

    under_query = HiddenChoiceGame(generate_instance(5, "necessary_query"))
    under_query.step(next(action for action in under_query.legal_actions() if action.startswith("ACT ")))
    assert under_query.terminal_metrics()["under_querying"] == 1.0

    selection = HiddenChoiceGame(generate_instance(5, "selective_query"))
    wrong_question = next(
        action
        for action in selection.legal_actions()
        if action.startswith("ASK ") and action not in selection.initial_decision.best_questions
    )
    selection.step(wrong_question)
    selection.step(_best_act(selection))
    assert selection.terminal_metrics()["query_selection_failure"] == 1.0

    misuse = HiddenChoiceGame(generate_instance(5, "necessary_query"))
    misuse.step(misuse.initial_decision.best_questions[0])
    misuse.step(_wrong_act(misuse))
    assert misuse.terminal_metrics()["information_use_failure"] == 1.0

    success = HiddenChoiceGame(generate_instance(5, "necessary_query"))
    success.step(success.initial_decision.best_questions[0])
    success.step(_best_act(success))
    terminal = success.terminal_metrics()
    assert terminal["communication_success"] == 1.0
    assert terminal["benchmark_success"] == 1.0


def test_roll_adapter_is_deterministic_and_scores_ask_after_query_as_stopping_failure():
    env = HiddenChoiceEnv(HiddenChoiceConfig(condition="necessary_query"))
    initial, automatic = env.reset(seed=52)
    first_instance = env.game.instance
    assert automatic == []
    assert "Possible-world utility table" in initial["observation"]
    env.reset(seed=52)
    assert env.game.instance == first_instance

    question = env.game.initial_decision.best_questions[0]
    result = env.step(question)[0]
    assert result["done"] is False
    assert all(action.startswith("ACT ") for action in result["legal_actions"].values())
    terminal = env.handle_invalid_response(
        player_id=0,
        actions=[question],
        raw_response=f"<answer>{question}</answer>",
    )[0]
    assert terminal["done"] is True
    assert terminal["info"]["stopping_failure"] == 1.0
    assert terminal["info"]["ask_after_single_query"] == 1.0
    assert terminal["info"]["player_0_success"] is False
    assert "artificial_truncation" not in terminal["info"]


def test_full_information_control_has_only_act_and_scores_decision_computation():
    env = HiddenChoiceEnv(
        HiddenChoiceConfig(condition="selective_query", full_information=True)
    )
    initial, _ = env.reset(seed=52)
    assert all(action.startswith("ACT ") for action in initial["legal_actions"].values())
    assert "Information mode: full" in initial["observation"]
    action = next(action for action in env.game.initial_decision.optimal_actions if action.startswith("ACT "))
    terminal = env.step(action)[0]
    assert terminal["done"] is True
    assert terminal["info"]["full_info_action_correct"] == 1.0
    assert terminal["info"]["benchmark_success"] == 1.0


def test_adapter_parser_recovers_one_listed_action_without_closing_tag():
    env = HiddenChoiceEnv(HiddenChoiceConfig(condition="selective_query"))
    initial, _ = env.reset(seed=9)
    action = next(iter(initial["legal_actions"].values()))
    assert env.recover_action(f"<answer>{action}</answer>", initial["legal_actions"]) == action
    assert env.recover_action(f"<answer>{action}", initial["legal_actions"]) == action
    assert env.recover_action(f"<reason>reason</reason><answer>{action}", initial["legal_actions"]) == action
    assert env.validate_response(
        f"<reason>reason</reason><answer>{action}</answer>", initial["legal_actions"]
    )
    assert env.validate_response(f"<answer>{action}", initial["legal_actions"])
    assert not env.validate_response(f"<answer>{action}</answer></", initial["legal_actions"])


def test_prompt_explicitly_uses_reason_then_answer_protocol():
    env = HiddenChoiceEnv(HiddenChoiceConfig(condition="selective_query"))
    prompt = env.get_prompt()["user"]
    assert "<reason>...</reason>" in prompt
    assert "<answer>ACT X</answer>" in prompt


def test_aggregate_metrics_keeps_failure_modes_separate():
    infos = [
        {"benchmark_success": 1.0, "correct_abstention": 1.0},
        {"benchmark_success": 0.0, "over_querying": 1.0},
    ]
    metrics = aggregate_metrics(infos)
    assert metrics["benchmark_success"] == 0.5
    assert metrics["correct_abstention"] == 0.5
    assert metrics["over_querying"] == 0.5
    assert metrics["episodes"] == 2.0
