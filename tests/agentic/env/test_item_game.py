"""Regression tests for the structured v0 item game."""

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


def play(game, actions):
    for action in actions:
        _, reward, done, info = game.step(action)
    assert done
    return reward, info


def test_all_generators_use_the_same_runtime_budget_and_randomize_opaque_items():
    for generator, subtype in (
        ("pure_collaboration", None),
        ("mixed_incentive", "exchange"),
        ("mixed_incentive", "give_first"),
        ("mixed_incentive", "request_surplus"),
        ("resource_conflict", "cannot_help"),
        ("resource_conflict", "refuse_harmful_request"),
    ):
        config = Config(generator=generator, subtype=subtype)
        first = generate_instance(11, config=config)
        second = generate_instance(12, config=config)
        assert first == generate_instance(11, config=config)
        assert first.items != second.items
        assert config.max_ego_steps == 6
        assert config.communication_budget == 4
        assert all(2 <= len(first.goal(player)) <= 3 for player in first.goals)
        assert all(2 <= len(first.holding(player)) <= 4 for player in first.holdings)


def test_pure_collaboration_uses_joint_commit_with_exact_member_action():
    g = game("pure_collaboration")
    g.step("ASK P1 GOAL")
    g.step("ASK P1 HOLDINGS")
    message, _, _, _ = g.step("ASK P1 JOIN {EGO,P1}")
    assert "YES" in message
    assert "ACT JOIN_COMMIT {EGO,P1}" in g.legal_actions()
    reward, info = play(g, ["ACT JOIN_COMMIT {EGO,P1}"])
    assert reward == 1.0
    assert info["successful_joint_commit"] == 1.0
    assert info["coalition_commit_exact"] == 1.0
    assert g.member_commit_actions == {
        "EGO": "ACT JOIN_COMMIT {EGO,P1}",
        "P1": "ACT JOIN_COMMIT {EGO,P1}",
    }
    assert info["canonical_reward_player_1"] == 0.0


def test_exchange_is_partner_approved_then_ego_executed():
    g = game("mixed_incentive", "exchange")
    g.step("ASK P1 GOAL")
    g.step("ASK P1 HOLDINGS")
    message, reward, done, _ = g.step("ASK P1 EXCHANGE give=item_V receive=item_Q")
    assert "YES" in message and reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_V", "item_M"}
    assert "ACT EXCHANGE P1 give=item_V receive=item_Q" in g.legal_actions()
    g.step("ACT EXCHANGE P1 give=item_V receive=item_Q")
    reward, info = play(g, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 1.0
    assert info["executed_exchange"] == 1.0


def test_give_first_unlocks_delayed_reciprocity_and_refusal_cannot_succeed():
    g = game("mixed_incentive", "give_first")
    g.step("SAY P1 CAN_GIVE item_V")
    g.step("ACT TRANSFER P1 item_V")
    message, _, _, _ = g.step("ASK P1 GIVE item_Q")
    assert "YES" in message
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    reward, _ = play(g, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 1.0

    refused = game("mixed_incentive", "give_first")
    refused.step("SAY P1 CANNOT_GIVE item_V")
    refused.step("ASK P1 GIVE item_Q")
    reward, _ = play(refused, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 0.0


def test_cannot_help_reroutes_and_critical_request_is_refused():
    g = game("resource_conflict", "cannot_help")
    g.step("ASK P1 HOLDINGS")
    assert "CANNOT" in g.step("ASK P1 GIVE item_Q")[0]
    g.step("ASK P2 HOLDINGS")
    assert "YES" in g.step("ASK P2 GIVE item_Q")[0]
    reward, info = play(g, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 1.0
    assert info["rerouted_after_cannot"] == 1.0

    refused = game("resource_conflict", "refuse_harmful_request")
    assert refused.pending_partner_request == "ASK EGO GIVE item_Q"
    refused.step("SAY P1 CANNOT_GIVE item_Q")
    reward, info = play(refused, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 1.0
    assert info["refused_critical_item"] == 1.0


def test_request_surplus_is_an_ask_then_partner_to_ego_transfer():
    g = game("mixed_incentive", "request_surplus")
    message, reward, done, _ = g.step("ASK P1 GIVE item_Q")
    assert "YES" in message and reward == 0.0 and not done
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_V", "item_Q"}
    reward, _ = play(g, ["ACT JOIN_COMMIT {EGO}"])
    assert reward == 1.0


def test_partner_give_request_executes_as_a_scripted_partner_action():
    g = game("mixed_incentive", "request_surplus")
    g.step("ASK P1 GIVE item_Q")
    assert g.holdings["P1"] == {"item_T", "item_Z", "item_F"}
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_V", "item_Q"}


def test_join_requires_matching_goals_and_all_members_consent():
    g = game("resource_conflict", "cannot_help")
    message, _, _, _ = g.step("ASK P1 JOIN {EGO,P1}")
    assert "CANNOT" in message
    assert "ACT JOIN_COMMIT {EGO,P1}" not in g.legal_actions()

    # A two-partner instance also supports the general coalition syntax.  A
    # joint commit is exposed only after every member has approved that exact
    # coalition, and the scripted members then emit the exact same action.
    g = game("pure_collaboration")
    g.step("ASK P1 JOIN {EGO,P1}")
    assert g.join_approved[frozenset({"EGO", "P1"})] == {"P1"}
    assert g.member_commit_actions == {}


def test_two_partner_coalition_waits_for_every_exact_join_approval():
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
    reward, info = play(g, [action])
    assert reward == 1.0
    assert info["coalition_commit_exact"] == 1.0
    assert set(g.member_commit_actions.values()) == {action}


def test_communication_budget_is_hard_and_rewards_are_terminal_only():
    g = game("pure_collaboration")
    for action in ("ASK P1 GOAL", "ASK P1 HOLDINGS", next(a for a in g.legal_actions() if a.startswith("SAY P1 PROFILE")), "ASK P1 GOAL"):
        _, reward, done, _ = g.step(action)
        assert reward == 0.0 and not done
    assert not any(action.startswith(("ASK ", "SAY ")) for action in g.legal_actions())
    with pytest.raises(ValueError):
        g.step("ASK P1 GOAL")

    legal_loss = game("pure_collaboration")
    _, reward, done, info = legal_loss.step("ACT JOIN_COMMIT {EGO}")
    assert done and reward == 0.0
    assert info["success"] is True
    assert info["player_0_success"] is False
    assert info["canonical_reward_player_1"] == 0.0


def test_roll_adapter_uses_structured_answer_protocol():
    env = ItemGameEnv(Config(randomize_items=False))
    initial, execute_results = env.reset(seed=3)
    assert not execute_results
    prompt = env.get_prompt(think=False)
    assert "ACT EXCHANGE" in prompt["user"]
    assert "<reason>" not in prompt["user"]
    action = next(iter(initial["legal_actions"].values()))
    assert env.validate_response(f"<reason>query</reason><answer>{action}</answer>", initial["legal_actions"])
    transition = env.step(action)[0]
    assert transition["current_player"] == 0
    assert transition["info"]["step_reward"] == 0.0
    assert "holdings (not necessarily known)" not in initial["observation"]
    assert env.validate_response(
        f"<reason>query</reason><answer>{action}</answer>", initial["legal_actions"]
    )


def test_roll_adapter_returns_only_ego_reward_at_terminal():
    env = ItemGameEnv(Config(randomize_items=False))
    env.reset(seed=3)
    transition = env.step("ACT JOIN_COMMIT {EGO}")[0]
    assert transition["done"] is True
    assert transition["rewards"] == [0.0, 0.0]
    assert transition["info"]["player_1_return"] == 0.0
    assert transition["info"]["player_1_success"] is False
