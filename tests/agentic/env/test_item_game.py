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
for module_name in ("config", "generator", "game", "env", "self_play"):
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
self_play_module = sys.modules[f"{PACKAGE}.item_game.self_play"]
SelfPlayItemGame = self_play_module.SelfPlayItemGame
SelfPlayRunner = self_play_module.SelfPlayRunner


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
            ("mixed_incentive", "request_surplus_reroute"),
            ("mixed_incentive", "respond_to_give_request"),
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


def test_request_surplus_reroute_randomizes_helper_identity_and_blocker_mode():
    config = Config(
        generator="mixed_incentive",
        subtype="request_surplus_reroute",
        randomize_items=True,
    )
    helper_ids = set()
    blocker_modes = set()
    for seed in range(100):
        instance = generate_instance(seed, config=config)
        helper = next(partner for partner, role in instance.partner_roles.items() if role == "HELPER")
        blocker = next(partner for partner, role in instance.partner_roles.items() if role != "HELPER")
        helper_ids.add(helper)
        blocker_modes.add(instance.partner_roles[blocker])
    assert helper_ids == {"P1", "P2"}
    assert blocker_modes == {"BLOCKER_INFERABLE", "BLOCKER_HIDDEN_UNWILLING"}


def test_respond_to_give_request_randomizes_partner_case_and_structure():
    config = Config(
        generator="mixed_incentive",
        subtype="respond_to_give_request",
        randomize_items=True,
    )
    partners = set()
    cases = set()
    item_universe_sizes = set()
    ego_goal_sizes = set()
    partner_goal_sizes = set()
    ego_holding_sizes = set()
    partner_holding_sizes = set()
    for seed in range(100):
        instance = generate_instance(seed, config=config)
        validate_instance(instance)
        partners.add(instance.active_partner)
        cases.add(instance.request_case)
        item_universe_sizes.add(len(instance.items))
        ego_goal_sizes.add(len(instance.goals["EGO"]))
        partner_goal_sizes.add(len(instance.goals[instance.active_partner]))
        ego_holding_sizes.add(len(instance.holdings["EGO"]))
        partner_holding_sizes.add(len(instance.holdings[instance.active_partner]))
    assert partners == {"P1", "P2", "P3"}
    assert cases == {"safe", "harmful"}
    assert len(item_universe_sizes) > 1
    assert len(ego_goal_sizes) > 1
    assert len(partner_goal_sizes) > 1
    assert len(ego_holding_sizes) > 1
    assert len(partner_holding_sizes) > 1


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


def reroute_game(blocker_role):
    for seed in range(100):
        config = Config(generator="mixed_incentive", subtype="request_surplus_reroute", randomize_items=False)
        instance = generate_instance(seed, config=config)
        helper = next(partner for partner, role in instance.partner_roles.items() if role == "HELPER")
        blocker = next(partner for partner, role in instance.partner_roles.items() if role != "HELPER")
        if instance.partner_roles[blocker] == blocker_role:
            return BaseItemGame(instance, config), helper, blocker
    raise AssertionError(f"no deterministic reroute seed for {blocker_role}")


def reroute_target(g):
    return next(iter(set(g.goals["EGO"]) - set(g.holdings["EGO"])))


def query_partner(g, partner):
    g.step(f"QUERY {partner} GOAL")
    g.step(f"QUERY {partner} HOLDINGS")


def commit_reroute_goal(g):
    return finish(g, f"ACT COMMIT {g._format_set(g.goals['EGO'])}")


def test_request_surplus_reroute_helper_first_accepts_and_transfers_immediately():
    g, helper, blocker = reroute_game("BLOCKER_INFERABLE")
    target = reroute_target(g)
    query_partner(g, helper)
    message, reward, done, _ = g.step(g._format_give_proposal(helper, target))
    assert f"{helper} ACT ACCEPT" in message
    assert f"{helper} ACT GIVE {target} TO EGO" in message
    assert reward == 0.0 and not done
    assert target in g.holdings["EGO"]
    assert g.reroute_status == {helper: "accepted"}
    assert blocker not in g.reroute_status
    reward, info = commit_reroute_goal(g)
    assert reward == pytest.approx(1.0 + 3 * g._COLLAB_COMMUNICATION_BONUS)
    assert info["terminal_success"] == 1.0
    assert info["reroute_first_partner_is_helper"] == 1.0


def test_request_surplus_reroute_logs_exploration_after_item_is_received():
    g, helper, blocker = reroute_game("BLOCKER_INFERABLE")
    target = reroute_target(g)
    query_partner(g, helper)
    g.step(g._format_give_proposal(helper, target))
    g.step(f"QUERY {blocker} GOAL")
    reward, info = commit_reroute_goal(g)
    assert reward == pytest.approx(1.0 + 2 * g._COLLAB_COMMUNICATION_BONUS)
    assert info["terminal_success"] == 1.0
    assert info["reroute_unnecessary_exploration_after_success"] == 1.0


def test_request_surplus_reroute_inferable_blocker_is_skipped():
    g, helper, blocker = reroute_game("BLOCKER_INFERABLE")
    target = reroute_target(g)
    query_partner(g, blocker)
    assert target in g.goals[blocker]
    query_partner(g, helper)
    message, _, done, _ = g.step(g._format_give_proposal(helper, target))
    assert f"{helper} ACT ACCEPT" in message
    assert blocker not in g.reroute_status
    assert not done
    reward, info = commit_reroute_goal(g)
    assert reward == pytest.approx(1.0 + g._COLLAB_COMMUNICATION_BONUS)
    assert info["terminal_success"] == 1.0
    assert info["reroute_blocker_inferable"] == 1.0
    assert info["rerouted_after_rejection"] == 0.0


def test_request_surplus_reroute_hidden_unwilling_rejects_then_reroutes():
    g, helper, blocker = reroute_game("BLOCKER_HIDDEN_UNWILLING")
    target = reroute_target(g)
    query_partner(g, blocker)
    assert target not in g.goals[blocker]
    message, reward, done, _ = g.step(g._format_give_proposal(blocker, target))
    assert f"{blocker} ACT REJECT GIVE {target}" in message
    assert reward == 0.0 and not done
    query_partner(g, helper)
    message, reward, done, _ = g.step(g._format_give_proposal(helper, target))
    assert f"{helper} ACT ACCEPT" in message
    assert f"{helper} ACT GIVE {target} TO EGO" in message
    assert reward == 0.0 and not done
    reward, info = commit_reroute_goal(g)
    assert reward == pytest.approx(1.0)
    assert info["terminal_success"] == 1.0
    assert info["reroute_blocker_hidden_unwilling"] == 1.0
    assert info["reroute_first_proposal_rejected"] == 1.0
    assert info["rerouted_after_rejection"] == 1.0


def give_request_game(request_case):
    for seed in range(100):
        config = Config(
            generator="mixed_incentive",
            subtype="respond_to_give_request",
            randomize_items=False,
        )
        instance = generate_instance(seed, config=config)
        if instance.request_case == request_case:
            return BaseItemGame(instance, config)
    raise AssertionError(f"no deterministic give-request seed for {request_case}")


def give_request_item(g):
    return g.instance.partner_event


def test_respond_to_give_request_safe_requires_accept_then_exact_give():
    g = give_request_game("safe")
    partner = g.instance.active_partner
    item = give_request_item(g)
    before = set(g.holdings["EGO"])
    proposal = f"PROPOSE GIVE {{giver: EGO,receiver: {partner},items: {g._format_set({item})}}}"
    assert proposal in g.conversation_history[0]["action"]
    assert g.legal_actions() == ("ACT ACCEPT", "ACT REJECT")

    g.step("ACT ACCEPT")
    assert g.holdings["EGO"] == before
    assert g.give_request_accepted
    assert g.give_request_fulfilled is False
    assert g.legal_actions() == (f"ACT GIVE {g._format_set({item})}",)

    g.step(f"ACT GIVE {g._format_set({item})}")
    assert item not in g.holdings["EGO"]
    assert g.holdings[partner] >= {item}
    assert g.give_request_fulfilled
    reward, info = finish(g, f"ACT COMMIT {g._format_set(g.goals['EGO'])}")
    assert reward == pytest.approx(1.0 + g.communication_left * g._COLLAB_COMMUNICATION_BONUS)
    assert info["respond_request_safe"] == 1.0
    assert info["respond_safe_correct"] == 1.0
    assert info["respond_give_fulfilled"] == 1.0


def test_respond_to_give_request_harmful_reject_preserves_critical_item():
    g = give_request_game("harmful")
    partner = g.instance.active_partner
    item = give_request_item(g)
    before = set(g.holdings["EGO"])
    assert item in g.goals["EGO"]
    assert g.legal_actions() == ("ACT ACCEPT", "ACT REJECT")

    message, reward, done, _ = g.step("ACT REJECT")
    assert "ACT REJECT" in message
    assert reward == 0.0 and not done
    assert g.holdings["EGO"] == before
    assert g.give_request_rejected
    assert g.legal_actions() != (f"ACT GIVE {g._format_set({item})}",)
    reward, info = finish(g, f"ACT COMMIT {g._format_set(g.goals['EGO'])}")
    assert reward == pytest.approx(1.0 + g.communication_left * g._COLLAB_COMMUNICATION_BONUS)
    assert info["respond_request_harmful"] == 1.0
    assert info["respond_harmful_correct"] == 1.0
    assert info["harmful_give_avoided"] == 1.0
    assert partner in g.holdings


def test_respond_to_give_request_accept_does_not_allow_wrong_or_skipped_give():
    g = give_request_game("safe")
    item = give_request_item(g)
    g.step("ACT ACCEPT")
    with pytest.raises(ValueError):
        g.step("ACT COMMIT {}")
    wrong_item = next(candidate for candidate in g.items if candidate != item)
    with pytest.raises(ValueError):
        g.step(f"ACT GIVE {g._format_set({wrong_item})}")


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


def test_structured_set_parser_accepts_optional_spaces():
    legal_actions = {0: "ACT COMMIT {item_K,item_M}"}
    env = ItemGameEnv(Config(randomize_items=False))
    spaced = "<reason>commit the required items</reason><answer>ACT COMMIT {item_K, item_M}</answer>"

    assert env.validate_response(spaced, legal_actions)
    assert env.recover_action(spaced, legal_actions) == legal_actions[0]

    g = game("pure_collaboration")
    establish_collaboration(g)
    ego_commit = g.goals["EGO"] & g.holdings["EGO"]
    canonical = f"ACT COMMIT {g._format_set(ego_commit)}"
    assert canonical in g.legal_actions()
    _, reward, done, _ = g.step(canonical.replace(",", ", "))
    assert done
    assert reward > 0.0


def test_reroute_prompt_hides_partner_role_and_exposes_only_reroute_protocol():
    config = Config(
        generator="mixed_incentive",
        subtype="request_surplus_reroute",
        randomize_items=False,
    )
    env = ItemGameEnv(config)
    initial, _ = env.reset(seed=2)
    prompt = env.get_prompt(think=False)
    assert "PROPOSE GIVE" in prompt["user"]
    assert "ACT COMMIT" in prompt["user"]
    assert "HELPER" not in env.render()
    assert "UNWILLING" not in env.render()
    assert env.validate_response(
        f"<answer>{next(iter(initial['legal_actions'].values()))}</answer>",
        initial["legal_actions"],
    )


def test_respond_to_give_request_prompt_exposes_no_legacy_exchange_protocol():
    config = Config(
        generator="mixed_incentive",
        subtype="respond_to_give_request",
        randomize_items=False,
    )
    env = ItemGameEnv(config)
    initial, _ = env.reset(seed=2)
    prompt = env.get_prompt(think=False)
    assert "ACT ACCEPT" in prompt["user"]
    assert "ACT REJECT" in prompt["user"]
    assert "ACT GIVE {<exact requested item>}" in prompt["user"]
    assert "ASK EXCHANGE" not in prompt["user"]
    assert "CAN_GIVE" not in prompt["user"]
    assert tuple(initial["legal_actions"].values()) == ("ACT ACCEPT", "ACT REJECT")
    assert "request_case" not in env.render()


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


def test_self_play_partner_proposal_is_not_accepted_or_transferred_by_environment():
    config = Config(
        generator="mixed_incentive",
        subtype="respond_to_give_request",
        randomize_items=False,
        self_play=True,
        max_total_turns=16,
    )
    instance = generate_instance(7, config=config)
    g = SelfPlayItemGame(instance, config)
    partner = instance.active_partner
    assert g.current_agent == partner
    assert not g.public_history

    proposal = next(
        action for action in g.get_legal_actions(partner)
        if action.startswith("PROPOSE GIVE {giver=EGO,receiver=")
    )
    ego_before = set(g.holdings["EGO"])
    g.step(partner, proposal)
    assert g.current_agent == "EGO"
    assert g.pending_proposal is not None
    assert g.holdings["EGO"] == ego_before
    assert g.get_legal_actions("EGO") == ("ACT ACCEPT", "ACT REJECT")

    g.step("EGO", "ACT ACCEPT")
    assert g.holdings["EGO"] == ego_before
    assert g.current_agent == "EGO"
    assert g.get_legal_actions("EGO")[0].startswith("ACT GIVE {")


def test_self_play_collaboration_requires_partner_accept_and_commit():
    config = Config(
        generator="pure_collaboration",
        subtype="collaboration",
        randomize_items=False,
        self_play=True,
        max_total_turns=16,
    )
    g = SelfPlayItemGame(generate_instance(7, config=config), config)
    ego_before = set(g.holdings["EGO"])
    g.step("EGO", "PROPOSE JOIN {EGO,P1}")
    assert g.current_agent == "P1"
    assert g.join_coalition is None
    assert g.holdings["EGO"] == ego_before
    assert g.get_legal_actions("P1") == ("ACT ACCEPT", "ACT REJECT")

    g.step("P1", "ACT ACCEPT")
    assert g.join_coalition == {"EGO", "P1"}
    assert not g.done
    assert g.current_agent == "EGO"

    ego_commit = g.goals["EGO"] & g.holdings["EGO"]
    p1_commit = g.goals["P1"] & g.holdings["P1"]
    g.step("EGO", f"ACT COMMIT {_format_for_test(ego_commit)}")
    assert not g.done
    assert g.current_agent == "P1"
    g.step("P1", f"ACT COMMIT {_format_for_test(p1_commit)}")
    assert g.done
    assert g.terminal_success


def _format_for_test(items):
    return "{" + ",".join(sorted(items)) + "}"


def test_self_play_runner_keeps_reasoning_private_between_agent_contexts():
    config = Config(
        generator="pure_collaboration",
        subtype="collaboration",
        randomize_items=False,
        self_play=True,
        max_total_turns=16,
    )

    class Policy:
        def __init__(self):
            self.calls = []

        def generate(self, *, agent, observation, legal_actions, context):
            self.calls.append((agent, observation, tuple(context)))
            if "PROPOSE JOIN {EGO,P1}" in legal_actions:
                action = "PROPOSE JOIN {EGO,P1}"
            elif agent == "P1" and "ACT ACCEPT" in legal_actions:
                action = "ACT ACCEPT"
            else:
                goal = next(line for line in observation.splitlines() if line.startswith("Your goal: "))
                holdings = next(line for line in observation.splitlines() if line.startswith("Your holdings: "))
                goal_items = set(goal.split("{", 1)[1].rstrip("}").split(","))
                held_items = set(holdings.split("{", 1)[1].rstrip("}").split(","))
                required = _format_for_test(goal_items & held_items)
                action = f"ACT COMMIT {required}"
                assert action in legal_actions
            return f"<reason>private reasoning for {agent}</reason><answer>{action}</answer>"

    policy = Policy()
    result = SelfPlayRunner(policy, config).run_episode(7)
    assert result.terminal["terminal_success"] is True
    p1_observation = next(observation for agent, observation, _ in policy.calls if agent == "P1")
    assert "private reasoning" not in p1_observation
    assert [turn["agent"] for turn in result.turns] == ["EGO", "P1", "EGO", "P1"]


def test_self_play_runner_supports_all_three_new_subtypes_with_fake_policy():
    class Policy:
        def __init__(self, scripted):
            self.scripted = iter(scripted)

        def generate(self, *, agent, observation, legal_actions, context):
            expected_agent, action = next(self.scripted)
            assert agent == expected_agent
            assert action in legal_actions
            return f"<reason>private {agent}</reason><answer>{action}</answer>"

    # Collaboration: proposal, consent, then both independent commits.
    config = Config(
        generator="pure_collaboration", subtype="collaboration",
        randomize_items=False, self_play=True, max_total_turns=16,
    )
    instance = generate_instance(7, config=config)
    ego_commit = _format_for_test(set(instance.goals["EGO"]) & set(instance.holdings["EGO"]))
    p1_commit = _format_for_test(set(instance.goals["P1"]) & set(instance.holdings["P1"]))
    result = SelfPlayRunner(
        Policy([
            ("EGO", "PROPOSE JOIN {EGO,P1}"),
            ("P1", "ACT ACCEPT"),
            ("EGO", f"ACT COMMIT {ego_commit}"),
            ("P1", f"ACT COMMIT {p1_commit}"),
        ]), config,
    ).run_episode(7)
    assert result.terminal["terminal_success"] is True

    # Reroute: query the known helper, then make the helper own the GIVE action.
    config = Config(
        generator="mixed_incentive", subtype="request_surplus_reroute",
        randomize_items=False, self_play=True, max_total_turns=16,
    )
    instance = generate_instance(7, config=config)
    helper = next(agent for agent, role in instance.partner_roles.items() if role == "HELPER")
    target = next(iter(set(instance.goals["EGO"]) - set(instance.holdings["EGO"])))
    ego_goal = _format_for_test(set(instance.goals["EGO"]))
    result = SelfPlayRunner(
        Policy([
            ("EGO", f"QUERY {helper} GOAL"),
            (helper, f"INFORM EGO GOAL {_format_for_test(set(instance.goals[helper]))}"),
            ("EGO", f"QUERY {helper} HOLDINGS"),
            (helper, f"INFORM EGO HOLDINGS {_format_for_test(set(instance.holdings[helper]))}"),
            ("EGO", f"PROPOSE GIVE {{giver={helper},receiver=EGO,items={_format_for_test({target})}}}"),
            (helper, "ACT ACCEPT"),
            (helper, f"ACT GIVE {_format_for_test({target})} TO EGO"),
            ("EGO", f"ACT COMMIT {ego_goal}"),
        ]), config,
    ).run_episode(7)
    assert result.terminal["terminal_success"] is True

    # RespondToGiveRequest: the partner proposes; Ego decides and, when safe,
    # must execute its own accepted GIVE.
    config = Config(
        generator="mixed_incentive", subtype="respond_to_give_request",
        randomize_items=False, self_play=True, max_total_turns=16,
    )
    instance = generate_instance(7, config=config)
    partner = str(instance.active_partner)
    item = str(instance.partner_event)
    ego_action = "ACT ACCEPT" if instance.request_case == "safe" else "ACT REJECT"
    scripted = [
        (partner, f"PROPOSE GIVE {{giver=EGO,receiver={partner},items={_format_for_test({item})}}}"),
        ("EGO", ego_action),
    ]
    if instance.request_case == "safe":
        scripted.append(("EGO", f"ACT GIVE {_format_for_test({item})} TO {partner}"))
    scripted.extend([
        (partner, f"ACT COMMIT {_format_for_test(set(instance.goals[partner]) & set(instance.holdings[partner]))}"),
        ("EGO", f"ACT COMMIT {_format_for_test(set(instance.goals['EGO']) & set(instance.holdings['EGO']))}"),
    ])
    result = SelfPlayRunner(Policy(scripted), config).run_episode(7)
    assert result.terminal["terminal_success"] is True
