import importlib.util
from pathlib import Path
import random
import sys
import types

import pytest


ENV_DIR = Path(__file__).parents[3] / "roll/agentic/env"
PACKAGE = "_geography_test_env"


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


# Load Geography independently of the repository-wide environment registry.
# The registry imports optional game dependencies that are not needed by these
# dependency-free solver and adapter correctness tests.
_package(PACKAGE, ENV_DIR)
_package(f"{PACKAGE}.geography", ENV_DIR / "geography")
_load(f"{PACKAGE}.base", ENV_DIR / "base.py")
CONFIG = _load(f"{PACKAGE}.geography.config", ENV_DIR / "geography/config.py")
SOLVER = _load(f"{PACKAGE}.geography.solver", ENV_DIR / "geography/solver.py")
GRAPH = _load(f"{PACKAGE}.geography.graph", ENV_DIR / "geography/graph.py")
ENV = _load(f"{PACKAGE}.geography.env", ENV_DIR / "geography/env.py")

GeographyConfig = CONFIG.GeographyConfig
GeographyEnv = ENV.GeographyEnv
GeographyGraph = GRAPH.GeographyGraph
GeographyState = GRAPH.GeographyState
generate_geography_graph = GRAPH.generate_geography_graph
solve_geography = SOLVER.solve_geography
topological_order = SOLVER.topological_order


GENERATOR_ARGS = {
    "num_nodes": 14,
    "min_depth": 4,
    "max_depth": 8,
    "min_branching": 1,
    "max_branching": 3,
    "transposition_rate": 0.3,
    "target_informative_fraction": 0.5,
    "candidate_count": 12,
}


def generated(seed=17):
    return generate_geography_graph(seed=seed, **GENERATOR_ARGS)


def test_generated_graph_is_acyclic_and_root_reachable():
    graph, _, _ = generated()
    assert len(topological_order(graph.adjacency)) == graph.num_nodes
    assert graph.reachable_nodes() == frozenset(range(graph.num_nodes))


def test_same_seed_reproduces_graph_solution_and_properties():
    first = generated(seed=91)
    second = generated(seed=91)
    assert first == second
    assert first[0].episode_seed == 91


@pytest.mark.parametrize("seed", range(10))
def test_generator_can_target_an_informative_root(seed):
    graph, solution, _ = generate_geography_graph(
        seed=seed,
        num_nodes=8,
        min_depth=2,
        max_depth=4,
        min_branching=1,
        max_branching=2,
        transposition_rate=0.05,
        target_root_informative=True,
        target_informative_fraction=0.5,
        candidate_count=32,
    )
    assert solution.decision_spreads[graph.start_node] > 0


@pytest.mark.parametrize("target_distance", [1, 3, 5])
def test_generator_can_exactly_target_root_optimal_distance(target_distance):
    graph, solution, _ = generate_geography_graph(
        seed=9000 + target_distance,
        num_nodes=12,
        min_depth=4,
        max_depth=6,
        min_branching=1,
        max_branching=3,
        transposition_rate=0.15,
        target_root_informative=True,
        target_root_optimal_distance=target_distance,
        target_root_branching=2,
        target_informative_fraction=0.5,
        candidate_count=8192,
    )
    root = graph.start_node
    assert solution.optimal_distances[root] == target_distance
    assert solution.decision_spreads[root] > 0
    assert len(graph.adjacency[root]) == 2


def test_seed_namespaces_make_splits_reproducible_and_disjoint():
    first = GeographyEnv(
        GeographyConfig(built_in_opponent="none", seed_namespace=1)
    )
    second = GeographyEnv(
        GeographyConfig(built_in_opponent="none", seed_namespace=2)
    )
    first.reset(seed=55)
    first_id = first.state.graph.graph_id
    first_seed = first.state.graph.episode_seed
    first.reset(seed=55)
    assert first.state.graph.graph_id == first_id
    assert first.state.graph.episode_seed == first_seed
    second.reset(seed=55)
    assert second.state.graph.episode_seed != first_seed
    assert second.state.graph.graph_id != first_id


@pytest.mark.parametrize("minimum", [1, 2, 3])
def test_generator_respects_branching_bounds(minimum):
    graph, _, _ = generate_geography_graph(
        seed=73,
        num_nodes=18,
        min_depth=4,
        max_depth=8,
        min_branching=minimum,
        max_branching=3,
        transposition_rate=0.3,
        candidate_count=8,
    )
    nonterminal_degrees = [len(successors) for successors in graph.adjacency if successors]
    assert min(nonterminal_degrees) >= minimum
    assert max(nonterminal_degrees) <= 3


def test_every_state_transition_follows_a_declared_edge():
    graph, _, _ = generated()
    state = GeographyState(graph, graph.start_node)
    while not state.is_terminal():
        before = state.current_node
        action = state.legal_actions()[0]
        state = state.apply_action(action)
        assert action in graph.adjacency[before]


def test_player_to_act_at_terminal_node_loses():
    graph = GeographyGraph(
        adjacency=((1,), ()),
        labels=("N0", "N1"),
        start_node=0,
        episode_seed=0,
        graph_id="one-edge",
        display_order=(0, 1),
    )
    terminal = GeographyState(graph, 0).apply_action(1)
    assert terminal.is_terminal()
    assert terminal.current_player() == 1

    env = GeographyEnv(
        GeographyConfig(
            built_in_opponent="none",
            num_nodes=2,
            min_depth=1,
            max_depth=1,
            max_branching=1,
            target_informative_fraction=None,
            generator_candidates=1,
        )
    )
    env.reset(seed=0)
    result = env.step(next(iter(env.get_all_actions())))[0]
    assert result["done"]
    assert result["info"]["winner"] == 0
    assert result["info"]["player_0_return"] == 1.0
    assert result["info"]["player_1_return"] == -1.0


def test_solver_satisfies_bellman_equations_and_q_sign_flip():
    graph, solution, _ = generated()
    for node, successors in enumerate(graph.adjacency):
        if not successors:
            assert solution.value(node) == -1
            assert solution.action_values(node) == {}
            continue
        q_values = solution.action_values(node)
        assert q_values == {child: -solution.value(child) for child in successors}
        assert solution.value(node) == max(q_values.values())


def test_optimal_actions_have_zero_regret():
    graph, solution, _ = generated()
    for node in range(graph.num_nodes):
        for action in solution.optimal_actions[node]:
            assert solution.regret(node, action) == 0


def test_uniform_counterfactual_rewards_sum_to_zero():
    graph, solution, _ = generated()
    for node, successors in enumerate(graph.adjacency):
        if not successors:
            continue
        q_values = solution.action_values(node)
        baseline = sum(q_values.values()) / len(q_values)
        assert sum(value - baseline for value in q_values.values()) == pytest.approx(0.0)


def test_relabelling_preserves_values_and_optimal_actions():
    graph, solution, _ = generated()
    relabelled = graph.relabel(seed=333)
    relabelled_solution = solve_geography(relabelled.adjacency)
    assert relabelled.graph_id == graph.graph_id
    assert relabelled.labels != graph.labels
    assert relabelled_solution.values == solution.values
    assert tuple(map(set, relabelled_solution.optimal_actions)) == tuple(
        map(set, solution.optimal_actions)
    )


def test_invalid_output_does_not_change_state_or_canonical_values():
    env = GeographyEnv(GeographyConfig(built_in_opponent="none"))
    env.reset(seed=12)
    state_before = env.state
    values_before = env.solution.values
    result = env.get_losing_state(player_id=env.current_player)[0]
    assert env.state == state_before
    assert env.solution.values == values_before
    assert result["rewards"] == [0.0, 0.0]
    assert result["info"]["canonical_reward_player_0"] == 0.0
    assert result["info"]["canonical_reward_player_1"] == 0.0
    assert result["info"]["game_transition"] == 0.0
    assert result["info"]["graph_seed"] == str(env.state.graph.episode_seed)
    assert result["info"]["graph_current_node"] == env.state.graph.labels[
        env.state.current_node
    ]
    assert result["info"]["remaining_optimal_distance"] == (
        env.solution.optimal_distances[env.state.current_node]
    )


def test_random_self_play_terminates_within_longest_depth():
    graph, _, properties = generated(seed=45)
    state = GeographyState(graph, graph.start_node)
    rng = random.Random(45)
    moves = 0
    while not state.is_terminal():
        state = state.apply_action(rng.choice(state.legal_actions()))
        moves += 1
    assert moves <= properties.longest_depth


@pytest.mark.parametrize("seed", range(10))
def test_optimal_play_matches_root_value(seed):
    graph, solution, _ = generated(seed=seed)
    state = GeographyState(graph, graph.start_node)
    while not state.is_terminal():
        state = state.apply_action(solution.optimal_actions[state.current_node][0])
    winner = 1 - state.current_player()
    expected_winner = 0 if solution.value(graph.start_node) == 1 else 1
    assert winner == expected_winner


def test_environment_emits_exact_generic_diagnostics_and_legacy_aliases():
    env = GeographyEnv(GeographyConfig(built_in_opponent="none"))
    env.reset(seed=29)
    before = env.state.current_node
    q_values = env.solution.action_values(before)
    action = next(iter(q_values))
    baseline = sum(q_values.values()) / len(q_values)
    result = env.step(action)[0]
    info = result["info"]
    assert result["rewards"][0] == pytest.approx(q_values[action] - baseline)
    assert result["rewards"][1] == 0.0
    assert info["counterfactual_chosen_q"] == q_values[action]
    assert info["counterfactual_baseline"] == pytest.approx(baseline)
    assert info["counterfactual_advantage"] == pytest.approx(q_values[action] - baseline)
    assert info["counterfactual_decision_spread"] == info["minimax_decision_spread"]
    assert info["counterfactual_regret"] == info["minimax_normalized_regret"]


def test_built_in_optimal_opponent_selects_a_solved_optimal_action():
    env = GeographyEnv(
        GeographyConfig(
            built_in_opponent="optimal",
            opponent_player=0,
            starting_player=0,
        )
    )
    _, automatic = env.reset(seed=31)
    assert len(automatic) == 1
    assert automatic[0]["info"]["counterfactual_optimal_action"] == 1.0


def test_parser_accepts_only_one_legal_answer_label():
    env = GeographyEnv(GeographyConfig(built_in_opponent="none"))
    env.reset(seed=9)
    legal = env.get_all_actions()
    label = next(iter(legal.values()))
    assert env.recover_action(
        f"<reason>the continuation is winning</reason><answer>{label}</answer>",
        legal,
    ) == label
    assert env.recover_action(f"<answer>{label}</answer>", legal) is None
    assert env.recover_action(
        f"<reason>x</reason><answer>{label} extra</answer>", legal
    ) is None


def test_root_decision_only_uses_exact_continuation_and_stops_after_one_move():
    env = GeographyEnv(
        GeographyConfig(
            built_in_opponent="none",
            reward_mode="environment",
            root_decision_only=True,
        )
    )
    env.reset(seed=37)
    before = env.state.current_node
    action = next(
        action
        for action in env.solution.action_values(before)
        if env.state.graph.adjacency[action]
    )
    chosen_q = env.solution.action_values(before)[action]

    result = env.step(action)[0]

    assert result["done"] is True
    assert env.state.is_terminal() is False
    assert result["rewards"][0] == chosen_q
    assert result["rewards"][1] == -chosen_q
    assert result["info"]["solved_continuation"] == 1.0
    assert result["info"]["player_0_return"] == chosen_q
    assert result["info"]["winner"] == (0 if chosen_q == 1 else 1)


def test_normal_mode_does_not_stop_after_a_nonterminal_root_move():
    env = GeographyEnv(GeographyConfig(built_in_opponent="none"))
    env.reset(seed=37)
    action = next(
        action
        for action in env.get_all_actions()
        if env.state.graph.adjacency[action]
    )
    result = env.step(action)[0]
    assert result["done"] is False


def test_prompt_invites_free_form_analysis_with_marshal_concision_instruction():
    env = GeographyEnv()
    prompt = env.get_prompt()["user"].lower()
    assert "<reason>your analysis</reason>" in prompt
    assert "consider future moves" not in prompt
    assert "opponent's possible responses" not in prompt
    assert "analyze the graph carefully" not in prompt
    assert "brief" not in prompt
    assert "keep your thinking process concise" in prompt
    assert "does not follow this format results in immediate loss" in prompt
    assert "token budget" not in prompt
    assert "1200" not in prompt


def test_prompt_explicitly_assigns_the_next_turn_to_the_opponent():
    prompt = GeographyEnv().get_prompt()["user"].lower()

    assert "after you move to a destination" in prompt
    assert "the opponent acts from that destination" in prompt
    assert (
        "if that destination has no outgoing edges, the opponent loses" in prompt
    )


def test_render_describes_terminal_nodes_as_having_no_outgoing_edges():
    env = GeographyEnv()
    state, _ = env.reset(seed=43)
    rendered = state["observation"]
    terminal_labels = [
        env.state.graph.labels[node]
        for node, successors in enumerate(env.state.graph.adjacency)
        if not successors
    ]

    assert terminal_labels
    assert "-> terminal" not in rendered
    for label in terminal_labels:
        assert f"{label}: no outgoing edges" in rendered


def test_turn_prompt_is_role_neutral():
    env = GeographyEnv()
    state, _ = env.reset(seed=41)
    prompt_player_0 = env.format_turn_prompt(
        state["observation"], state["legal_actions"], player_id=0
    )
    prompt_player_1 = env.format_turn_prompt(
        state["observation"], state["legal_actions"], player_id=1
    )

    assert prompt_player_0 == prompt_player_1
    assert "you are player" not in prompt_player_0.lower()


def test_paired_starting_roles_have_identical_graph_and_prompt():
    player_0 = GeographyEnv(
        GeographyConfig(seed_namespace=302, starting_player=0)
    )
    player_1 = GeographyEnv(
        GeographyConfig(seed_namespace=302, seed_offset=-8, starting_player=1)
    )
    state_0, _ = player_0.reset(seed=800008)
    state_1, _ = player_1.reset(seed=800016)

    assert player_0.state.graph == player_1.state.graph
    assert player_0.solution == player_1.solution
    assert player_0.format_turn_prompt(
        state_0["observation"], state_0["legal_actions"], player_id=0
    ) == player_1.format_turn_prompt(
        state_1["observation"], state_1["legal_actions"], player_id=1
    )
