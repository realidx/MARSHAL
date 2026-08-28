"""Regression tests for the structured Item Coalition Game v0.1."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ENV_DIR = Path(__file__).parents[3] / "roll/agentic/env"
PACKAGE = "_item_game_test_env"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ENV_DIR)]
sys.modules[PACKAGE] = package
base_spec = importlib.util.spec_from_file_location(f"{PACKAGE}.base", ENV_DIR / "base.py")
base_module = importlib.util.module_from_spec(base_spec)
sys.modules[base_spec.name] = base_module
base_spec.loader.exec_module(base_module)
sub_package = types.ModuleType(f"{PACKAGE}.item_game")
sub_package.__path__ = [str(ENV_DIR / "item_game")]
sys.modules[sub_package.__name__] = sub_package
for module_name in ("config", "generator", "game", "env"):
    module_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.item_game.{module_name}", ENV_DIR / "item_game" / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)

Config = sys.modules[f"{PACKAGE}.item_game.config"].ItemGameConfig
generate_instance = sys.modules[f"{PACKAGE}.item_game.generator"].generate_instance
BaseItemGame = sys.modules[f"{PACKAGE}.item_game.game"].BaseItemGame
ItemGameEnv = sys.modules[f"{PACKAGE}.item_game.env"].ItemGameEnv
ItemGameInstance = sys.modules[f"{PACKAGE}.item_game.generator"].ItemGameInstance


def game(generator, subtype=None):
    config = Config(generator=generator, subtype=subtype, randomize_items=False)
    return BaseItemGame(generate_instance(7, config=config), config)


def finish(g, action):
    _, reward, done, info = g.step(action)
    assert done
    return reward, info


def test_v01_uses_eight_steps_and_six_communication_actions():
    for generator, subtype in (
        ("pure_collaboration", None),
        ("mixed_incentive", "exchange"),
        ("mixed_incentive", "give_first"),
        ("mixed_incentive", "request_surplus"),
        ("resource_conflict", "cannot_help"),
        ("resource_conflict", "refuse_harmful_request"),
    ):
        config = Config(generator=generator, subtype=subtype)
        assert config.max_ego_steps == 8
        assert config.communication_budget == 6
        first = generate_instance(11, config=config)
        second = generate_instance(12, config=config)
        assert first == generate_instance(11, config=config)
        assert first.items != second.items

    # The v0.1 templates remain valid at the recommended 6-item minimum.
    six_items = tuple(f"item_{symbol}" for symbol in ("K", "Q", "M", "V", "T", "Z"))
    for generator, subtype in (
        ("pure_collaboration", None),
        ("mixed_incentive", "exchange"),
        ("mixed_incentive", "give_first"),
        ("mixed_incentive", "request_surplus"),
        ("resource_conflict", "cannot_help"),
        ("resource_conflict", "refuse_harmful_request"),
    ):
        config = Config(
            generator=generator,
            subtype=subtype,
            item_vocabulary=six_items,
            randomize_items=False,
        )
        instance = generate_instance(11, config=config)
        assert len(instance.items) == 6


def test_pure_collaboration_forms_agreement_then_exact_joint_commit():
    g = game("pure_collaboration")
    g.step("ASK P1 GOAL")
    g.step("ASK P1 HOLDINGS")
    message, reward, done, _ = g.step("ASK P1 JOIN {EGO,P1}")
    assert "AGREE_JOIN" in message
    assert reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_M"}
    assert "ACT JOIN_COMMIT {EGO,P1}" in g.legal_actions()

    reward, info = finish(g, "ACT JOIN_COMMIT {EGO,P1}")
    assert reward == 1.0
    assert info["agreement_formed"] == 1.0
    assert info["agreement_followed_through"] == 1.0
    assert info["correct_join_commit"] == 1.0
    assert g.member_commit_actions == {
        "EGO": "ACT JOIN_COMMIT {EGO,P1}",
        "P1": "ACT JOIN_COMMIT {EGO,P1}",
    }


def test_exchange_is_agreement_then_two_give_actions():
    g = game("mixed_incentive", "exchange")
    g.step("ASK P1 GOAL")
    g.step("ASK P1 HOLDINGS")
    message, reward, done, _ = g.step(
        "ASK P1 EXCHANGE give=item_V receive=item_Q"
    )
    assert "AGREE_EXCHANGE" in message
    assert reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_V", "item_M"}
    assert "ACT EXCHANGE P1 give=item_V receive=item_Q" not in g.legal_actions()
    assert "ACT GIVE item_V TO P1" in g.legal_actions()

    _, reward, done, info = g.step("ACT GIVE item_V TO P1")
    assert reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    assert g.holdings["P1"] == {"item_V", "item_T", "item_Z"}
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert info["agreement_followed_through"] == 1.0
    assert info["executed_exchange"] == 1.0


def test_give_first_requires_mandatory_response_and_ego_give_followthrough():
    g = game("mixed_incentive", "give_first")
    assert set(g.legal_actions()) == {
        "SAY P1 CANNOT_GIVE item_V",
        "SAY P1 CAN_GIVE item_V",
    }
    _, reward, done, info = g.step("SAY P1 CAN_GIVE item_V")
    assert reward == 0.0 and not done
    assert g.communication_used == 0
    assert g.holdings["EGO"] == {"item_K", "item_V", "item_M"}
    assert "ACT GIVE item_V TO P1" in g.legal_actions()

    g.step("ACT GIVE item_V TO P1")
    assert g.holdings["EGO"] == {"item_K", "item_M"}
    assert g.holdings["P1"] == {"item_Q", "item_T", "item_Z", "item_V"}
    message, _, _, _ = g.step("ASK P1 GIVE item_Q")
    assert "CAN_GIVE item_Q" in message
    assert g.holdings["EGO"] == {"item_K", "item_M"}
    assert g.pending_partner_give == ("P1", "item_Q")
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    assert info["mandatory_request_answered"] == 1.0
    assert info["agreement_followed_through"] == 1.0

    refused = game("mixed_incentive", "give_first")
    refused.step("SAY P1 CANNOT_GIVE item_V")
    refused.step("ASK P1 GIVE item_Q")
    reward, _ = finish(refused, "ACT JOIN_COMMIT {EGO}")
    assert reward == 0.0


def test_request_surplus_is_partner_agreement_then_scripted_partner_give():
    g = game("mixed_incentive", "request_surplus")
    message, reward, done, _ = g.step("ASK P1 GIVE item_Q")
    assert "CAN_GIVE item_Q" in message
    assert reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_V"}
    assert g.holdings["P1"] == {"item_T", "item_Z", "item_Q", "item_F"}
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_V", "item_Q"}
    assert info["useful_give_request"] == 1.0


def test_cannot_help_reroutes_to_surplus_partner():
    g = game("resource_conflict", "cannot_help")
    message, _, _, _ = g.step("ASK P1 GIVE item_Q")
    assert "CANNOT_GIVE item_Q" in message
    message, _, _, _ = g.step("ASK P2 GIVE item_Q")
    assert "CAN_GIVE item_Q" in message
    assert g.holdings["EGO"] == {"item_K", "item_M"}
    assert g.pending_partner_give == ("P2", "item_Q")
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    assert info["rerouted_after_cannot"] == 1.0
    assert info["useful_give_request"] == 1.0


def test_refuse_harmful_request_requires_refusal_then_safe_reroute():
    g = game("resource_conflict", "refuse_harmful_request")
    assert g.pending_partner_request == "ASK EGO GIVE item_Q"
    assert set(g.legal_actions()) == {
        "SAY P1 CANNOT_GIVE item_Q",
        "SAY P1 CAN_GIVE item_Q",
    }
    g.step("SAY P1 CANNOT_GIVE item_Q")
    assert g.communication_used == 0
    assert g.pending_partner_request is None
    g.step("ASK P2 GIVE item_V")
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert info["mandatory_request_answered"] == 1.0
    assert info["harmful_transfer_avoided"] == 1.0
    assert info["rerouted_after_cannot"] == 1.0


def test_two_partner_join_waits_for_every_exact_join_agreement():
    config = Config(randomize_items=False)
    instance = ItemGameInstance(
        episode_seed=7,
        generator="pure_collaboration",
        subtype="collaboration",
        items=("item_K", "item_Q", "item_M", "item_V", "item_T", "item_Z"),
        goals={
            "EGO": frozenset({"item_K", "item_Q"}),
            "P1": frozenset({"item_K", "item_Q"}),
            "P2": frozenset({"item_K", "item_Q"}),
        },
        holdings={
            "EGO": frozenset({"item_K"}),
            "P1": frozenset({"item_Q"}),
            "P2": frozenset({"item_M"}),
        },
    )
    g = BaseItemGame(instance, config)
    g.step("ASK P1 JOIN {EGO,P1,P2}")
    assert "ACT JOIN_COMMIT {EGO,P1,P2}" not in g.legal_actions()
    g.step("ASK P2 JOIN {EGO,P1,P2}")
    action = "ACT JOIN_COMMIT {EGO,P1,P2}"
    assert action in g.legal_actions()
    reward, info = finish(g, action)
    assert reward == 1.0
    assert info["correct_join_commit"] == 1.0
    assert set(g.member_commit_actions.values()) == {action}


def test_communication_budget_is_hard_but_mandatory_response_is_free():
    g = game("pure_collaboration")
    for action in (
        "ASK P1 GOAL",
        "ASK P1 HOLDINGS",
        "ASK P1 GIVE item_K",
        "ASK P1 GIVE item_M",
        "ASK P1 GIVE item_V",
        "ASK P1 GIVE item_Q",
    ):
        _, reward, done, _ = g.step(action)
        assert reward == 0.0 and not done
    assert not any(action.startswith(("ASK ", "SAY ")) for action in g.legal_actions())
    assert "ACT JOIN_COMMIT {EGO}" in g.legal_actions()
    with pytest.raises(ValueError):
        g.step("ASK P1 GOAL")

    mandatory = game("mixed_incentive", "give_first")
    mandatory.step("SAY P1 CANNOT_GIVE item_V")
    assert mandatory.communication_used == 0


def test_roll_adapter_exposes_only_v01_actions_and_answer_protocol():
    env = ItemGameEnv(Config(randomize_items=False))
    initial, execute_results = env.reset(seed=3)
    assert not execute_results
    prompt = env.get_prompt(think=False)
    assert "ACT GIVE <item> TO <partner>" in prompt["user"]
    assert "ACT EXCHANGE" not in prompt["user"]
    assert "ACT TRANSFER" not in prompt["user"]
    action = next(iter(initial["legal_actions"].values()))
    assert env.validate_response(f"<answer>{action}</answer>", initial["legal_actions"])
    transition = env.step(action)[0]
    assert transition["current_player"] == 0
    assert transition["info"]["step_reward"] == 0.0


def test_roll_adapter_returns_only_ego_reward_at_terminal():
    env = ItemGameEnv(Config(randomize_items=False))
    env.reset(seed=3)
    transition = env.step("ACT JOIN_COMMIT {EGO}")[0]
    assert transition["done"] is True
    assert transition["rewards"] == [0.0, 0.0]
    assert transition["info"]["player_1_return"] == 0.0
    assert transition["info"]["player_1_success"] is False


def test_roll_adapter_provides_invalid_response_losing_state():
    env = ItemGameEnv(Config(randomize_items=False))
    env.reset(seed=3)
    transition = env.get_losing_state(
        player_id=0, overlong_response=True, overlong_sequence=True
    )[0]
    assert transition["done"] is True
    assert transition["rewards"] == [0.0, 0.0]
    assert transition["info"]["artificial_truncation"] == 1.0
    assert transition["info"]["player_0_lose_for_wrong_format"] == 1
    assert transition["info"]["player_0_lose_for_overlong_response"] == 1
    assert transition["info"]["player_0_lose_for_overlong_sequence"] == 1
