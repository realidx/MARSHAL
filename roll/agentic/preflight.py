"""Generation-only preflight reporting for agentic rollouts."""

from __future__ import annotations

import json
from collections import Counter
from math import comb
import random
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _game_id(trajectory_id: str) -> str:
    # Markovian rollouts append `_p{player}_a{turn}`. All samples in an
    # environment group still belong to the same graph and must therefore
    # share one pass@k bucket, including attempts with no valid transition.
    return re.sub(r"_p[01](?:_a\d+)?$", "", str(trajectory_id))


def _percentile(values: Sequence[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _pass_at_k(sample_count: int, success_count: int, k: int) -> float | None:
    """Unbiased pass@k estimate from repeated samples of one graph."""
    if sample_count < k:
        return None
    if sample_count - success_count < k:
        return 1.0
    return 1.0 - comb(sample_count - success_count, k) / comb(sample_count, k)


def _summarize_root_move_pass_at_k(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root_attempts = [
        record
        for record in records
        if int(record.get("decision_index", record.get("turn_index", 0))) == 0
        and int(record.get("retry_attempt_index", 0)) == 0
    ]
    graphs: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in root_attempts:
        # game_id is present before an action is parsed, whereas graph_id is
        # transition metadata and is consequently absent on invalid/capped
        # responses. Using game_id keeps all 32 attempts in the same bucket.
        graph_key = str(record["game_id"])
        graphs.setdefault((str(record.get("tag", "all")), graph_key), []).append(record)

    def summarize(graph_samples: Sequence[list[Mapping[str, Any]]]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "graph_count": len(graph_samples),
            "sample_count": sum(len(samples) for samples in graph_samples),
        }
        result["valid_action_rate"] = (
            sum(
                bool(record.get("valid_action", False))
                for samples in graph_samples
                for record in samples
            )
            / result["sample_count"]
            if result["sample_count"]
            else 0.0
        )
        result["token_limit_hit_rate"] = (
            sum(
                bool(record.get("hit_token_limit", False))
                for samples in graph_samples
                for record in samples
            )
            / result["sample_count"]
            if result["sample_count"]
            else 0.0
        )
        for k in (1, 8, 32):
            estimates = []
            for samples in graph_samples:
                successes = sum(
                    bool(record.get("valid_action", False))
                    and bool(
                        record.get(
                            "counterfactual_optimal_action",
                            record.get("minimax_optimal_action", False),
                        )
                    )
                    for record in samples
                )
                estimate = _pass_at_k(len(samples), successes, k)
                if estimate is not None:
                    estimates.append(estimate)
            result[f"graphs_with_pass@{k}"] = len(estimates)
            result[f"pass@{k}"] = (
                sum(estimates) / len(estimates) if estimates else None
            )
        return result

    by_group = {}
    for tag in sorted({tag for tag, _ in graphs}):
        by_group[tag] = summarize(
            [samples for (sample_tag, _), samples in graphs.items() if sample_tag == tag]
        )
    by_group["overall"] = summarize(list(graphs.values()))
    return by_group


def summarize_agentic_preflight(
    records_by_rollout: Sequence[Iterable[Mapping[str, Any]]],
    trajectory_ids: Sequence[str],
    terminal_infos: Sequence[Mapping[str, Any]],
    tags: Sequence[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not (len(records_by_rollout) == len(trajectory_ids) == len(terminal_infos)):
        raise ValueError("preflight inputs must have the same length")
    if tags is None:
        tags = ["all"] * len(records_by_rollout)
    if len(tags) != len(records_by_rollout):
        raise ValueError("preflight tags must match the number of rollouts")

    games: dict[str, dict[str, Any]] = {}
    flat_records: list[dict[str, Any]] = []
    for rollout_index, (
        rollout_records,
        trajectory_id,
        terminal_info,
        tag,
    ) in enumerate(zip(records_by_rollout, trajectory_ids, terminal_infos, tags)):
        rollout_records = list(rollout_records)
        game_id = _game_id(trajectory_id)
        game = games.setdefault(
            game_id,
            {
                "records": [],
                "terminal_info": dict(terminal_info),
                "players": set(),
                "tags": set(),
            },
        )
        game["players"].update(int(record["player_id"]) for record in rollout_records)
        game["tags"].add(str(tag))
        if terminal_info:
            game["terminal_info"] = dict(terminal_info)
        for record in rollout_records:
            item = dict(record)
            item["game_id"] = game_id
            item["trajectory_id"] = str(trajectory_id)
            item["rollout_index"] = rollout_index
            item["tag"] = str(tag)
            game["records"].append(item)
            flat_records.append(item)

    flat_records.sort(key=lambda item: (item["game_id"], item["turn_index"], item["player_id"]))
    lengths = [int(record["token_length"]) for record in flat_records]
    valid = [record for record in flat_records if record["valid_action"]]
    closing = [record for record in flat_records if record["has_closing_answer_tag"]]
    limited = [record for record in flat_records if record["hit_token_limit"]]
    missing_answers = [record for record in flat_records if not record["has_closing_answer_tag"]]
    capped_without_answer = [
        record
        for record in flat_records
        if record["hit_token_limit"] and not record["has_closing_answer_tag"]
    ]
    first_attempts = [
        record for record in flat_records
        if int(record.get("retry_attempt_index", 0)) == 0
    ]
    retry_records = [
        record for record in flat_records
        if int(record.get("retry_attempt_index", 0)) > 0
    ]
    decisions = {}
    for record in flat_records:
        decision_key = (
            int(record["rollout_index"]),
            int(record["player_id"]),
            int(record.get("decision_index", record["turn_index"])),
        )
        decisions.setdefault(decision_key, []).append(record)
    eventual_valid_count = sum(
        any(bool(attempt["valid_action"]) for attempt in attempts)
        for attempts in decisions.values()
    )
    retry_success_count = sum(bool(record["valid_action"]) for record in retry_records)
    additional_retry_tokens = sum(int(record["token_length"]) for record in retry_records)

    action_counts = Counter(
        str(record.get("parsed_action", ""))
        for record in valid
        if str(record.get("parsed_action", ""))
    )
    dominant_action_count = max(action_counts.values(), default=0)
    dominant_action_rate = dominant_action_count / len(valid) if valid else 0.0

    # Some environments (e.g. Hidden Choice with an automatic truthful
    # partner) are single-model-player games.  A terminal player-0 trajectory
    # is complete even though no player-1 model turn exists.
    complete_games = [
        game for game in games.values()
        if game["players"] in ({0}, {0, 1})
        and game["terminal_info"].get("success", False)
    ]
    artificial_truncation_count = sum(
        bool(game["terminal_info"].get("artificial_truncation", False))
        for game in games.values()
    )
    completed_legal_games = 0
    for game in complete_games:
        terminal_info = game["terminal_info"]
        if terminal_info.get("success", False) and all(record["valid_action"] for record in game["records"]):
            completed_legal_games += 1

    by_player = {}
    for player_id in (0, 1):
        player_records = [record for record in flat_records if int(record["player_id"]) == player_id]
        player_valid = sum(bool(record["valid_action"]) for record in player_records)
        player_closing = sum(bool(record["has_closing_answer_tag"]) for record in player_records)
        player_limited = sum(bool(record["hit_token_limit"]) for record in player_records)
        player_missing = len(player_records) - player_closing
        player_optimal = sum(
            bool(
                record.get(
                    "counterfactual_optimal_action",
                    record.get("minimax_optimal_action", False),
                )
            )
            for record in player_records
        )
        player_first_attempts = [
            record for record in player_records
            if int(record.get("retry_attempt_index", 0)) == 0
        ]
        player_retries = [
            record for record in player_records
            if int(record.get("retry_attempt_index", 0)) > 0
        ]
        player_decisions = {
            key: attempts for key, attempts in decisions.items() if key[1] == player_id
        }
        player_eventual_valid = sum(
            any(bool(attempt["valid_action"]) for attempt in attempts)
            for attempts in player_decisions.values()
        )
        by_player[str(player_id)] = {
            "turn_count": len(player_records),
            "valid_action_rate": player_valid / len(player_records) if player_records else 0.0,
            "closing_answer_tag_rate": player_closing / len(player_records) if player_records else 0.0,
            "token_limit_hit_rate": player_limited / len(player_records) if player_records else 0.0,
            "missing_answer_rate": player_missing / len(player_records) if player_records else 0.0,
            "minimax_optimal_action_count": player_optimal,
            "minimax_optimality_rate": player_optimal / len(player_records) if player_records else 0.0,
            "minimax_optimality_when_valid_rate": (
                player_optimal / player_valid if player_valid else 0.0
            ),
            "first_attempt_count": len(player_first_attempts),
            "first_attempt_validity_rate": (
                sum(bool(record["valid_action"]) for record in player_first_attempts)
                / len(player_first_attempts) if player_first_attempts else 0.0
            ),
            "retry_attempt_count": len(player_retries),
            "retry_success_rate": (
                sum(bool(record["valid_action"]) for record in player_retries)
                / len(player_retries) if player_retries else 0.0
            ),
            "eventual_validity_rate": (
                player_eventual_valid / len(player_decisions) if player_decisions else 0.0
            ),
            "additional_retry_tokens": sum(int(record["token_length"]) for record in player_retries),
        }

    turn_count = len(flat_records)
    observed_game_count = len(games)
    game_count = len(complete_games)
    role_validity_asymmetry = (
        abs(by_player["0"]["valid_action_rate"] - by_player["1"]["valid_action_rate"])
        if any(int(record["player_id"]) == 1 for record in flat_records)
        else 0.0
    )

    counterfactual_optimal_count = sum(
        bool(
            record.get(
                "counterfactual_optimal_action",
                record.get("minimax_optimal_action", False),
            )
        )
        for record in flat_records
    )
    role_minimax_optimality_gap = abs(
        by_player["0"]["minimax_optimality_rate"]
        - by_player["1"]["minimax_optimality_rate"]
    )

    role_first_attempt_validity_gap = abs(
        by_player["0"]["first_attempt_validity_rate"]
        - by_player["1"]["first_attempt_validity_rate"]
    )
    role_eventual_validity_gap = abs(
        by_player["0"]["eventual_validity_rate"]
        - by_player["1"]["eventual_validity_rate"]
    )

    single_model_outcomes_by_tag = {}
    for game in games.values():
        if len(game["players"]) != 1 or len(game["tags"]) != 1:
            continue
        tag = next(iter(game["tags"]))
        player_id = next(iter(game["players"]))
        terminal_info = game["terminal_info"]
        outcome = single_model_outcomes_by_tag.setdefault(
            tag,
            {
                "game_count": 0,
                "completed_count": 0,
                "invalid_or_truncated_count": 0,
                "win_count": 0,
                "draw_count": 0,
                "loss_count": 0,
            },
        )
        outcome["game_count"] += 1
        if not terminal_info.get("success", False):
            outcome["invalid_or_truncated_count"] += 1
            continue
        outcome["completed_count"] += 1
        explicit_success_key = f"player_{player_id}_success"
        if explicit_success_key in terminal_info:
            model_success = bool(terminal_info[explicit_success_key])
            model_return = float(terminal_info.get(f"player_{player_id}_return", 0.0))
        else:
            model_return = float(terminal_info.get(f"player_{player_id}_return", 0.0))
            model_success = model_return > 0
        if model_success:
            outcome["win_count"] += 1
        elif model_return < 0:
            outcome["loss_count"] += 1
        else:
            outcome["draw_count"] += 1

    for outcome in single_model_outcomes_by_tag.values():
        games_for_tag = outcome["game_count"]
        completed_for_tag = outcome["completed_count"]
        outcome["completion_rate"] = (
            completed_for_tag / games_for_tag if games_for_tag else 0.0
        )
        for name in ("win", "draw", "loss"):
            outcome[f"{name}_rate_when_completed"] = (
                outcome[f"{name}_count"] / completed_for_tag
                if completed_for_tag
                else 0.0
            )

    summary = {
        "game_count": game_count,
        "observed_game_count": observed_game_count,
        "partial_game_count": observed_game_count - game_count,
        "turn_count": turn_count,
        "decision_count": len(decisions),
        "first_attempt_valid_count": sum(bool(record["valid_action"]) for record in first_attempts),
        "first_attempt_validity_rate": (
            sum(bool(record["valid_action"]) for record in first_attempts)
            / len(first_attempts) if first_attempts else 0.0
        ),
        "eventual_valid_count": eventual_valid_count,
        "eventual_validity_rate": eventual_valid_count / len(decisions) if decisions else 0.0,
        "retry_attempt_count": len(retry_records),
        "retry_success_count": retry_success_count,
        "retry_success_rate": retry_success_count / len(retry_records) if retry_records else 0.0,
        "additional_retry_tokens": additional_retry_tokens,
        "final_episode_truncation_count": artificial_truncation_count,
        "final_episode_truncation_rate": (
            artificial_truncation_count / observed_game_count if observed_game_count else 0.0
        ),
        "role_first_attempt_validity_gap": role_first_attempt_validity_gap,
        "role_eventual_validity_gap": role_eventual_validity_gap,
        "single_model_outcomes_by_tag": single_model_outcomes_by_tag,
        "completed_legal_game_count": completed_legal_games,
        "completed_legal_game_rate": completed_legal_games / game_count if game_count else 0.0,
        "valid_action_count": len(valid),
        "valid_action_rate": len(valid) / turn_count if turn_count else 0.0,
        "closing_answer_tag_count": len(closing),
        "closing_answer_tag_rate": len(closing) / turn_count if turn_count else 0.0,
        "token_limit_hit_count": len(limited),
        "token_limit_hit_rate": len(limited) / turn_count if turn_count else 0.0,
        "missing_answer_count": len(missing_answers),
        "missing_answer_rate": len(missing_answers) / turn_count if turn_count else 0.0,
        "capped_without_answer_count": len(capped_without_answer),
        "capped_without_answer_rate": len(capped_without_answer) / turn_count if turn_count else 0.0,
        "role_validity_asymmetry": role_validity_asymmetry,
        "counterfactual_optimal_action_count": counterfactual_optimal_count,
        "counterfactual_optimality_rate": (
            counterfactual_optimal_count / turn_count if turn_count else 0.0
        ),
        "counterfactual_optimality_when_valid_rate": (
            counterfactual_optimal_count / len(valid) if valid else 0.0
        ),
        "minimax_optimal_action_count": counterfactual_optimal_count,
        "minimax_optimality_rate": (
            counterfactual_optimal_count / turn_count if turn_count else 0.0
        ),
        "minimax_optimality_when_valid_rate": (
            counterfactual_optimal_count / len(valid) if valid else 0.0
        ),
        "role_minimax_optimality_gap": role_minimax_optimality_gap,
        "action_diversity": {
            "unique_action_count": len(action_counts),
            "action_counts": dict(sorted(action_counts.items())),
            "dominant_action_rate": dominant_action_rate,
        },
        "response_length": {
            "median": _percentile(lengths, 0.5),
            "p90": _percentile(lengths, 0.9),
            "p95": _percentile(lengths, 0.95),
            "p99": _percentile(lengths, 0.99),
            "max": max(lengths, default=0),
        },
        "by_player": by_player,
    }
    summary["gate"] = {
        "valid_action_rate_at_least_0_95": summary["valid_action_rate"] >= 0.95,
        "eventual_validity_rate_at_least_0_95": summary["eventual_validity_rate"] >= 0.95,
        "closing_answer_tag_rate_at_least_0_95": summary["closing_answer_tag_rate"] >= 0.95,
        "token_limit_hit_rate_at_most_0_02": summary["token_limit_hit_rate"] <= 0.02,
        "role_validity_asymmetry_at_most_0_05": role_validity_asymmetry <= 0.05,
        "at_least_3_unique_actions": len(action_counts) >= 3,
        "dominant_action_rate_at_most_0_80": dominant_action_rate <= 0.80,
    }
    summary["passed"] = all(summary["gate"].values())
    informative_valid = [
        record
        for record in flat_records
        if record.get("valid_action")
        and float(record.get("counterfactual_decision_spread", 0.0)) > 0.0
    ]
    by_distance = {}
    for distance in sorted(
        {int(record.get("remaining_optimal_distance", 0)) for record in informative_valid}
    ):
        bucket = [
            record
            for record in informative_valid
            if int(record.get("remaining_optimal_distance", 0)) == distance
        ]
        optimal = sum(
            bool(record.get("counterfactual_optimal_action", False))
            for record in bucket
        )
        by_distance[str(distance)] = {
            "decision_count": len(bucket),
            "optimal_action_rate": optimal / len(bucket) if bucket else 0.0,
            "normalized_regret_mean": (
                sum(float(record.get("counterfactual_regret", 0.0)) for record in bucket)
                / len(bucket)
                if bucket
                else 0.0
            ),
        }
    summary["informative_decisions_by_remaining_optimal_distance"] = by_distance
    summary["root_move_pass_at_k"] = _summarize_root_move_pass_at_k(flat_records)
    return summary, flat_records


def summarize_tictactoe_preflight(
    records_by_rollout: Sequence[Iterable[Mapping[str, Any]]],
    trajectory_ids: Sequence[str],
    terminal_infos: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compatibility wrapper retained for existing callers and reports."""
    return summarize_agentic_preflight(
        records_by_rollout, trajectory_ids, terminal_infos
    )


def write_agentic_preflight_report(
    output_dir: str | Path,
    records_by_rollout: Sequence[Iterable[Mapping[str, Any]]],
    trajectory_ids: Sequence[str],
    terminal_infos: Sequence[Mapping[str, Any]],
    random_seed: int = 42,
    tags: Sequence[str] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    summary, records = summarize_agentic_preflight(
        records_by_rollout, trajectory_ids, terminal_infos, tags=tags
    )

    (output_path / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_path / "turns.jsonl").open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    failures = [
        record for record in records
        if not record["valid_action"] or record["hit_token_limit"] or not record["has_closing_answer_tag"]
    ]
    longest = sorted(records, key=lambda record: record["token_length"], reverse=True)[:5]
    valid_records = [record for record in records if record["valid_action"]]
    sampled = random.Random(random_seed).sample(valid_records, min(10, len(valid_records)))
    inspection = {"failures": failures, "five_longest": longest, "random_valid_sample": sampled}
    (output_path / "inspection.json").write_text(
        json.dumps(inspection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def write_tictactoe_preflight_report(
    output_dir: str | Path,
    records_by_rollout: Sequence[Iterable[Mapping[str, Any]]],
    trajectory_ids: Sequence[str],
    terminal_infos: Sequence[Mapping[str, Any]],
    random_seed: int = 42,
) -> dict[str, Any]:
    """Compatibility wrapper retained for existing preflight commands."""
    return write_agentic_preflight_report(
        output_dir,
        records_by_rollout,
        trajectory_ids,
        terminal_infos,
        random_seed=random_seed,
    )
