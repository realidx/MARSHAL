import json
from pathlib import Path

import pytest

from examples.strategic_transfer.c2c_paired import (
    OBJECTIVES,
    build_plan,
    condition_worker_configs,
    focal_assignment,
    load_plan,
    write_plan,
)
from examples.strategic_transfer.trust_calibration import (
    ScriptedPolicy,
    generate_episode,
    load_suite,
    run_episode,
    save_suite,
    score_rows,
)


def test_c2c_plan_is_deterministic_balanced_and_self_consistent(tmp_path: Path):
    first = build_plan(num_pairs=16, seed_base=1000, num_boards=5)
    second = build_plan(num_pairs=16, seed_base=1000, num_boards=5)
    assert first == second
    assert {item.focal_seat for item in first} == {0, 1, 2, 3}
    assert {item.focal_objective for item in first} == set(OBJECTIVES)
    assert all(
        focal_assignment(item.board_seed, item.shuffle_seed) == (item.focal_seat, item.focal_objective)
        for item in first
    )

    counts = {(seat, objective): 0 for seat in range(4) for objective in OBJECTIVES}
    for item in first:
        counts[(item.focal_seat, item.focal_objective)] += 1
    assert set(counts.values()) == {2}

    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, first, ["strong/a", "peer/b", "weak/c"], seed_base=1000)
    plan = load_plan(plan_path)
    base = condition_worker_configs(plan, "openai/base", tmp_path / "base", 50)
    treatment = condition_worker_configs(plan, "openai/treatment", tmp_path / "treatment", 50)
    for base_cfg, treatment_cfg in zip(base, treatment):
        assert base_cfg["board_seed"] == treatment_cfg["board_seed"]
        assert base_cfg["shuffle_seed"] == treatment_cfg["shuffle_seed"]
        assert base_cfg["comparison_target_index"] == treatment_cfg["comparison_target_index"]
        assert base_cfg["model_assignment"][1:] == treatment_cfg["model_assignment"][1:]


def test_c2c_plan_requires_three_counterparties(tmp_path: Path):
    with pytest.raises(ValueError, match="exactly three"):
        write_plan(tmp_path / "plan.json", build_plan(1, 1, 1), ["only", "two"], 1)


def test_trust_suite_round_trip_and_persistent_roles(tmp_path: Path):
    episode = generate_episode(seed=42, episode_id=1, num_rounds=12, switch=True)
    assert all(
        tuple(report.source for report in round_.reports) == ("Atlas", "Beacon", "Cipher", "Delta")
        for round_ in episode.rounds
    )
    assert all(
        next(report for report in round_.reports if report.source == "Delta").behavior == "aligned_reliable"
        for round_ in episode.rounds[:6]
    )
    assert all(
        next(report for report in round_.reports if report.source == "Delta").behavior == "adversarial"
        for round_ in episode.rounds[6:]
    )

    path = tmp_path / "suite.jsonl"
    save_suite(path, [episode])
    assert load_suite(path) == [episode]


def test_oracle_policy_has_zero_decision_regret():
    episode = generate_episode(seed=9, episode_id=1)
    rows = run_episode(episode, ScriptedPolicy("oracle"))
    score = score_rows(rows)
    assert score["accuracy"] == 1.0
    assert score["decision_regret"] == 0.0
    assert score["fraction_oracle_gap_recovered"] == 1.0
    assert score["decisions"] == 12
