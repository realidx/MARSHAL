"""Deterministic regression tests for the structured Item Coalition Game."""

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
generator_module = sys.modules[f"{PACKAGE}.item_game.generator"]
generate_instance = generator_module.generate_instance
validate_instance = generator_module.validate_instance
BaseItemGame = sys.modules[f"{PACKAGE}.item_game.game"].BaseItemGame
ItemGameEnv = sys.modules[f"{PACKAGE}.item_game.env"].ItemGameEnv
ItemGameInstance = generator_module.ItemGameInstance


def game(generator, subtype=None):
    config = Config(generator=generator, subtype=subtype, randomize_items=False)
    return BaseItemGame(generate_instance(7, config=config), config)


def finish(g, action):
    _, reward, done, info = g.step(action)
    assert done
    return reward, info


def establish_collaboration(g):
    """Use the decentralized proposal path and return the acceptance message."""
    message, reward, done, _ = g.step("PROPOSE JOIN {EGO,P1}")
    assert "QUERY EGO GOAL" in message
    assert reward == 0.0 and not done
    g.step(f"INFORM P1 GOAL {g._format_set(g.goals['EGO'])}")
    assert g.pending_partner_query == "HOLDINGS"
    message, reward, done, _ = g.step(f"INFORM P1 HOLDINGS {g._format_set(g.holdings['EGO'])}")
    assert "ACT ACCEPT" in message
    assert reward == 0.0 and not done
    return message


def test_all_generators_are_deterministic_and_validate_invariants():
    cases = (
        ("pure_collaboration", None),
        ("mixed_incentive", "exchange"),
        ("mixed_incentive", "give_first"),
        ("mixed_incentive", "request_surplus"),
        ("resource_conflict", "cannot_help"),
        ("resource_conflict", "refuse_harmful_request"),
    )
    for generator, subtype in cases:
        config = Config(generator=generator, subtype=subtype, randomize_items=True)
        first = generate_instance(11, config=config)
        second = generate_instance(12, config=config)
        assert first == generate_instance(11, config=config)
        assert first.items != second.items
        validate_instance(first)

        six = Config(
            generator=generator,
            subtype=subtype,
            item_vocabulary=tuple(f"item_{x}" for x in "KQ MVTZ".replace(" ", "")),
            randomize_items=False,
        )
        validate_instance(generate_instance(11, config=six))


def test_collaboration_requires_local_information_then_accepts_and_commits_items():
    g = game("pure_collaboration")
    goal = set(g.goals["EGO"])
    ego_items = set(g.holdings["EGO"])
    p1_items = set(g.holdings["P1"])
    assert g.goals["P1"] == goal
    assert not goal.issubset(ego_items)
    assert not goal.issubset(p1_items)
    assert goal.issubset(ego_items | p1_items)
    assert goal & ego_items
    assert goal & p1_items

    message, reward, done, _ = g.step("PROPOSE JOIN {EGO,P1}")
    assert "QUERY EGO GOAL" in message
    assert reward == 0.0 and not done
    assert g.pending_proposal is not None
    assert g.collaboration_coalition is None
    assert g.legal_actions() == (f"INFORM P1 GOAL {g._format_set(g.goals['EGO'])}",)

    g.step(f"INFORM P1 GOAL {g._format_set(g.goals['EGO'])}")
    assert g.pending_partner_query == "HOLDINGS"
    assert g.legal_actions() == (f"INFORM P1 HOLDINGS {g._format_set(g.holdings['EGO'])}",)
    message, reward, done, info = g.step(f"INFORM P1 HOLDINGS {g._format_set(g.holdings['EGO'])}")
    assert "ACT ACCEPT" in message
    assert g.collaboration_coalition == {"EGO", "P1"}
    assert not done
    assert reward == 0.0
    assert "ACT COMMIT" in " ".join(g.legal_actions())
    assert "ACT JOIN_COMMIT" not in " ".join(g.legal_actions())

    ego_commit = goal & ego_items
    message, reward, done, info = g.step(f"ACT COMMIT {g._format_set(ego_commit)}")
    assert done
    assert "P1 ACT COMMIT" in message
    assert done
    assert reward == pytest.approx(1.0 + 3 * g._COLLAB_COMMUNICATION_BONUS)
    assert info["proposal_accepted"] == 1.0
    assert info["commit_valid"] == 1.0
    assert info["terminal_success"] == 1.0


def test_collaboration_commit_is_item_scoped_and_missing_goal_item_fails():
    g = game("pure_collaboration")
    establish_collaboration(g)
    foreign_item = next(iter(set(g.holdings["P1"]) - set(g.holdings["EGO"])))
    with pytest.raises(ValueError):
        g.step(f"ACT COMMIT {{{foreign_item}}}")

    incomplete = game("pure_collaboration")
    establish_collaboration(incomplete)
    reward, info = finish(incomplete, "ACT COMMIT {}")
    assert reward == 0.0
    assert info["commit_valid"] == 1.0
    assert info["goal_satisfied"] == 0.0
    assert info["terminal_success"] == 0.0


def test_collaboration_redundant_commit_only_has_small_penalty():
    g = game("pure_collaboration")
    establish_collaboration(g)
    all_ego_items = frozenset(g.holdings["EGO"])
    reward, info = finish(g, f"ACT COMMIT {g._format_set(all_ego_items)}")
    assert reward > 0.0
    assert reward < 1.0 + 6 * g._COLLAB_COMMUNICATION_BONUS
    assert info["redundant_commit_count"] >= 1.0


def test_collaboration_partner_rejects_when_disclosed_goal_is_not_aligned():
    config = Config(generator="pure_collaboration", subtype="collaboration", randomize_items=False)
    instance = ItemGameInstance(
        episode_seed=8,
        generator="pure_collaboration",
        subtype="collaboration",
        items=("item_K", "item_Q", "item_M", "item_V", "item_T", "item_Z"),
        goals={"EGO": frozenset({"item_K"}), "P1": frozenset({"item_K", "item_Q"})},
        holdings={"EGO": frozenset({"item_K", "item_M"}), "P1": frozenset({"item_Q", "item_T"})},
    )
    g = BaseItemGame(instance, config)

    message, _, done, _ = g.step("PROPOSE JOIN {EGO,P1}")
    assert "QUERY EGO GOAL" in message
    g.step("INFORM P1 GOAL {item_K}")
    assert g.pending_partner_query == "HOLDINGS"
    message, reward, done, info = g.step("INFORM P1 HOLDINGS {item_K,item_M}")
    assert "ACT REJECT" in message
    assert reward == 0.0 and not done
    assert g.collaboration_coalition is None
    assert info["proposal_rejected"] == 1.0


def test_exchange_requires_ego_fulfillment_and_partner_fulfillment():
    g = game("mixed_incentive", "exchange")
    g.step("ASK P1 EXCHANGE give=item_V receive=item_Q")
    assert g.holdings["EGO"] == {"item_K", "item_V", "item_M"}
    assert g.agreements[0]["fulfilled"] is False
    assert "ACT GIVE item_V TO P1" in g.legal_actions()
    g.step("ACT GIVE item_V TO P1")
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    assert g.holdings["P1"] == {"item_V", "item_T", "item_Z"}
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert info["executed_exchange"] == 1.0

    cheap_talk = game("mixed_incentive", "exchange")
    cheap_talk.step("ASK P1 EXCHANGE give=item_V receive=item_Q")
    reward, info = finish(cheap_talk, "ACT JOIN_COMMIT {EGO}")
    assert reward == 0.0
    assert info["unfulfilled_agreements"] == 1.0


def test_give_first_has_response_only_turn_and_ego_must_follow_through():
    g = game("mixed_incentive", "give_first")
    assert set(g.legal_actions()) == {
        "SAY P1 CANNOT_GIVE item_V",
        "SAY P1 CAN_GIVE item_V",
    }
    g.step("SAY P1 CAN_GIVE item_V")
    assert g.communication_used == 0
    assert g.pending_partner_request is None
    assert g.holdings["EGO"] == {"item_K", "item_V", "item_M"}
    g.step("ACT GIVE item_V TO P1")
    assert g.holdings["EGO"] == {"item_K", "item_M"}
    message, reward, done, _ = g.step("ASK P1 GIVE item_Q")
    assert "AGREE_GIVE item_Q" in message
    assert "ACT GIVE item_Q TO EGO" in message
    assert g.holdings["EGO"] == {"item_K", "item_M", "item_Q"}
    assert g.agreements[-1]["fulfilled"] is True
    message, reward, done, _ = g.step("ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0 and done


def test_request_surplus_partner_give_executes_in_same_transition():
    g = game("mixed_incentive", "request_surplus")
    message, reward, done, _ = g.step("ASK P1 GIVE item_Q")
    assert "AGREE_GIVE" in message
    assert "ACT GIVE item_Q TO EGO" in message
    assert reward == 0.0 and not done
    assert "item_Q" in g.holdings["EGO"]
    assert g.agreements[-1]["fulfilled"] is True
    message, reward, done, info = g.step("ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0 and done
    assert info["useful_give_request"] == 1.0


def test_cannot_help_allows_direct_inference_and_reroute():
    g = game("resource_conflict", "cannot_help")
    message, _, _, _ = g.step("ASK P1 GIVE item_Q")
    assert "CANNOT_GIVE item_Q" in message
    message, _, _, _ = g.step("ASK P2 GIVE item_Q")
    assert "AGREE_GIVE item_Q" in message
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert info["rerouted_after_cannot"] == 1.0

    direct = game("resource_conflict", "cannot_help")
    direct.step("ASK P2 GIVE item_Q")
    reward, _ = finish(direct, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0


def test_refuse_harmful_request_is_safe_singleton_and_transfer_fails():
    g = game("resource_conflict", "refuse_harmful_request")
    assert g.turn_phase == "mandatory_response"
    assert set(g.legal_actions()) == {
        "SAY P1 CANNOT_GIVE item_Q",
        "SAY P1 CAN_GIVE item_Q",
    }
    g.step("SAY P1 CANNOT_GIVE item_Q")
    assert g.communication_used == 0
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    assert info["harmful_transfer_avoided"] == 1.0

    harmful = game("resource_conflict", "refuse_harmful_request")
    harmful.step("SAY P1 CAN_GIVE item_Q")
    harmful.step("ACT GIVE item_Q TO P1")
    reward, info = finish(harmful, "ACT JOIN_COMMIT {EGO}")
    assert reward == 0.0
    assert info["agreement_followed_through"] == 1.0


def test_two_partner_join_requires_every_partner_consent_and_same_commit():
    g = game("pure_collaboration")
    assert "PROPOSE JOIN {EGO,P1}" in g.legal_actions()
    assert "ACT COMMIT {}" not in g.legal_actions()


def test_communication_budget_is_hard_but_mandatory_response_is_free():
    g = game("mixed_incentive", "exchange")
    for action in (
        "ASK P1 GOAL", "ASK P1 HOLDINGS", "ASK P1 GIVE item_K",
        "ASK P1 GIVE item_M", "ASK P1 GIVE item_V", "ASK P1 GIVE item_Q",
    ):
        _, reward, done, _ = g.step(action)
        assert reward == 0.0 and not done
    assert not any(action.startswith(("ASK ", "SAY ")) for action in g.legal_actions())
    with pytest.raises(ValueError):
        g.step("ASK P1 GOAL")
    mandatory = game("mixed_incentive", "give_first")
    mandatory.step("SAY P1 CANNOT_GIVE item_V")
    assert mandatory.communication_used == 0


def test_roll_adapter_prompt_and_terminal_protocol():
    env = ItemGameEnv(Config(randomize_items=False))
    initial, execute_results = env.reset(seed=3)
    assert not execute_results
    prompt = env.get_prompt(think=False)
    assert "response-only" in prompt["user"]
    assert "PROPOSE JOIN" in prompt["user"]
    assert "ACT COMMIT" in prompt["user"]
    assert "ACT JOIN_COMMIT" not in prompt["user"]
    assert "Pending scripted action" not in env.render()
    assert env.validate_response(f"<answer>{next(iter(initial['legal_actions'].values()))}</answer>", initial["legal_actions"])
    transition = env.step("QUERY P1 GOAL")[0]
    assert transition["done"] is False
    assert transition["rewards"] == [0.0, 0.0]
    assert transition["info"]["canonical_reward_player_1"] == 0.0
    assert "QUERY P1 GOAL" in transition["observation"]


def test_logging_exposes_separate_behavioral_diagnostics():
    g = game("resource_conflict", "refuse_harmful_request")
    g.step("SAY P1 CANNOT_GIVE item_Q")
    reward, info = finish(g, "ACT JOIN_COMMIT {EGO}")
    assert reward == 1.0
    for key in (
        "goal_satisfied", "agreement_formed", "agreement_fulfilled",
        "coalition_valid", "harmful_give_avoided", "rerouted_after_unavailability",
        "terminal_success",
    ):
        assert key in info
    assert info["goal_satisfied"] == 1.0
    assert info["coalition_valid"] == 1.0
    assert info["harmful_give_avoided"] == 1.0
    assert info["terminal_success"] == 1.0


def test_roll_adapter_provides_invalid_response_losing_state():
    env = ItemGameEnv(Config(randomize_items=False))
    env.reset(seed=3)
    transition = env.get_losing_state(player_id=0, overlong_response=True, overlong_sequence=True)[0]
    assert transition["done"] is True
    assert transition["rewards"] == [-0.05, 0.0]
    assert transition["info"]["artificial_truncation"] == 1.0
    assert transition["info"]["player_0_lose_for_wrong_format"] == 1
