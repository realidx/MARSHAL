#!/usr/bin/env python3
"""Small fixed comparison probe for native tool calling with private XML reasoning.

The same seeds are run with ``tool_choice=auto`` and ``tool_choice=required``.
Each condition defaults to five episodes for each synchronous ItemGame subtype
(15 episodes per condition, 30 total). Full trajectories are written so the
per-decision native message fields can be audited after the probe.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from roll.agentic.env.item_game.config import ItemGameConfig
from roll.agentic.env.item_game.generator import generate_instance
from roll.agentic.env.item_game.synchronous_self_play import (
    SynchronousEpisodeResult,
    SynchronousItemGame,
    SynchronousSelfPlayRunner,
    VLLMSelfPlayPolicy,
)


def _config_for(subtype: str, *, max_rounds: int, max_retries: int) -> ItemGameConfig:
    generator = "pure_collaboration" if subtype == "collaboration" else "mixed_incentive"
    config = ItemGameConfig(
        generator=generator,
        subtype=subtype,
        self_play=True,
        randomize_items=True,
        max_rounds=max_rounds,
    )
    config.max_invalid_retries_per_decision = max_retries
    config.output_mode = "native_tools"
    return config


def _decision_attempts(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for round_data in result.get("rounds", ()):
        for record in round_data.get("decisions", ()):
            enriched = dict(record)
            enriched["round"] = round_data.get("round")
            attempts.append(enriched)
    return attempts


def _first_attempts(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for record in _decision_attempts(result):
        grouped[(record.get("round"), record.get("agent"))].append(record)
    return [
        sorted(records, key=lambda item: int(item.get("retry_index", 0)))[0]
        for records in grouped.values()
    ]


def _final_attempts(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for record in _decision_attempts(result):
        grouped[(record.get("round"), record.get("agent"))].append(record)
    return [
        sorted(records, key=lambda item: int(item.get("retry_index", 0)))[-1]
        for records in grouped.values()
    ]


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _episode_records(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(record)
        for round_data in row.get("rounds", ())
        for record in (*round_data.get("responses", ()), *round_data.get("decisions", ()))
    ]


def _condition_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    successful_rows = [row for row in rows if "error" not in row]
    first = [record for row in successful_rows for record in _first_attempts(row)]
    final = [record for row in successful_rows for record in _final_attempts(row)]
    all_attempts = [record for row in successful_rows for record in _decision_attempts(row)]
    reason_lengths = [len(str(record.get("reason") or "")) for record in first]
    reason_word_lengths = [
        len(str(record.get("reason") or "").split()) for record in first
    ]
    prompt_tokens = [
        sum(int(record.get("usage", {}).get("prompt_tokens", 0)) for record in _episode_records(row))
        for row in successful_rows
    ]
    completion_tokens = [
        sum(int(record.get("usage", {}).get("completion_tokens", 0)) for record in _episode_records(row))
        for row in successful_rows
    ]

    def rate(predicate: Any, records: list[Mapping[str, Any]]) -> float:
        return sum(bool(predicate(record)) for record in records) / len(records) if records else 0.0

    by_subtype: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in successful_rows:
        by_subtype[str(row.get("subtype", "unknown"))].append(row)

    return {
        "episodes_requested": len(rows),
        "episodes_completed": len(successful_rows),
        "episode_errors": len(rows) - len(successful_rows),
        "decision_turns_before_retry": len(first),
        "decision_attempts_total": len(all_attempts),
        "reason_nonempty_rate": rate(lambda r: bool(str(r.get("reason") or "").strip()), first),
        "initial_tool_call_rate": rate(lambda r: r.get("tool_call_present") is True, first),
        "exactly_one_tool_call_rate_before_retry": rate(lambda r: r.get("exactly_one_tool_call") is True, first),
        "invalid_or_no_tool_rate_before_retry": rate(lambda r: r.get("valid") is False, first),
        "no_tool_call_rate_before_retry": rate(lambda r: r.get("tool_call_present") is False, first),
        "semantic_action_accuracy_before_retry": rate(lambda r: r.get("semantic_valid") is True, first),
        "final_valid_action_rate": rate(
            lambda r: r.get("valid") is True and r.get("semantic_valid") is True,
            final,
        ),
        "retry_rate": rate(lambda r: r.get("retry_required") is True, first),
        "pass_frequency_before_retry": rate(lambda r: r.get("tool_call_name") == "PASS", first),
        "average_reasoning_length_chars": _mean(reason_lengths),
        "average_reasoning_length_words": _mean(reason_word_lengths),
        "episode_success_rate": _mean(
            float(row.get("diagnostics", {}).get("task_success", 0.0))
            for row in successful_rows
        ),
        "average_rounds": _mean(
            float(row.get("diagnostics", {}).get("rounds_used", 0.0))
            for row in successful_rows
        ),
        "average_token_usage": {
            "prompt_tokens": _mean(prompt_tokens),
            "completion_tokens": _mean(completion_tokens),
            "total_tokens": _mean(
                prompt + completion
                for prompt, completion in zip(prompt_tokens, completion_tokens)
            ),
        },
        "subtype_success": {
            subtype: _mean(float(row.get("diagnostics", {}).get("task_success", 0.0)) for row in subtype_rows)
            for subtype, subtype_rows in sorted(by_subtype.items())
        },
        "subtype_terminal_success": {
            subtype: _mean(float(row.get("diagnostics", {}).get("terminal_success", 0.0)) for row in subtype_rows)
            for subtype, subtype_rows in sorted(by_subtype.items())
        },
    }


def _paired_episode_rows(
    auto_rows: list[Mapping[str, Any]],
    required_rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[str, int]:
        return str(row.get("subtype")), int(row.get("seed"))

    auto_by_key = {key(row): row for row in auto_rows}
    required_by_key = {key(row): row for row in required_rows}
    if set(auto_by_key) != set(required_by_key):
        raise RuntimeError("auto and required probe rows are not paired by identical subtype/seed keys")

    paired: list[dict[str, Any]] = []
    for pair_key in sorted(auto_by_key):
        auto_row = auto_by_key[pair_key]
        required_row = required_by_key[pair_key]
        auto_success = float(auto_row.get("diagnostics", {}).get("task_success", 0.0))
        required_success = float(required_row.get("diagnostics", {}).get("task_success", 0.0))
        auto_metrics = _condition_summary([auto_row])
        required_metrics = _condition_summary([required_row])
        if auto_success and required_success:
            outcome = "both_success"
        elif auto_success:
            outcome = "auto_only_success"
        elif required_success:
            outcome = "required_only_success"
        else:
            outcome = "neither_success"
        paired.append({
            "subtype": pair_key[0],
            "seed": pair_key[1],
            "ground_truth_match": auto_row.get("ground_truth") == required_row.get("ground_truth"),
            "outcome": outcome,
            "auto": {
                "initial_tool_call_rate": auto_metrics["initial_tool_call_rate"],
                "final_valid_action_rate": auto_metrics["final_valid_action_rate"],
                "episode_success_rate": auto_metrics["episode_success_rate"],
                "average_rounds": auto_metrics["average_rounds"],
                "average_token_usage": auto_metrics["average_token_usage"],
            },
            "required": {
                "initial_tool_call_rate": required_metrics["initial_tool_call_rate"],
                "final_valid_action_rate": required_metrics["final_valid_action_rate"],
                "episode_success_rate": required_metrics["episode_success_rate"],
                "average_rounds": required_metrics["average_rounds"],
                "average_token_usage": required_metrics["average_token_usage"],
            },
        })
    return paired


def _run_condition(
    *,
    model: str,
    base_url: str,
    api_key: str,
    tool_choice: str,
    seeds: list[tuple[str, int]],
    max_rounds: int,
    max_retries: int,
    max_new_tokens: int,
    parallel_tool_calls: bool,
    instances: Mapping[tuple[str, int], Any],
) -> list[dict[str, Any]]:
    policy = VLLMSelfPlayPolicy(
        base_url,
        model,
        api_key=api_key,
        max_new_tokens=max_new_tokens,
        output_mode="native_tools",
        native_tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )
    rows: list[dict[str, Any]] = []
    for subtype, seed in seeds:
        config = _config_for(subtype, max_rounds=max_rounds, max_retries=max_retries)
        instance = instances[(subtype, seed)]
        runner = SynchronousSelfPlayRunner(
            policy,
            config,
            instance_factory=lambda _seed, _config, fixed_instance=instance: fixed_instance,
        )
        try:
            result: SynchronousEpisodeResult = runner.run_episode(seed)
            rows.append(result.to_dict())
        except Exception as exc:  # pragma: no cover - live endpoint failures
            rows.append({"subtype": subtype, "seed": seed, "error": f"{type(exc).__name__}: {exc}"})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--episodes-per-subtype", type=int, default=5)
    parser.add_argument("--seed", type=int, default=910000)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--max-invalid-retries", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--parallel-tool-calls", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("runs/item_game_native_reason_probe"))
    args = parser.parse_args()
    if args.episodes_per_subtype < 1 or args.max_rounds < 1 or args.max_invalid_retries < 0:
        parser.error("episodes-per-subtype and max-rounds must be positive; max-invalid-retries cannot be negative")

    subtypes = list(SynchronousItemGame.SUPPORTED_SUBTYPES)
    seeds = [
        (subtype, args.seed + subtype_index * 1000 + episode)
        for subtype_index, subtype in enumerate(subtypes)
        for episode in range(args.episodes_per_subtype)
    ]
    instances = {
        (subtype, seed): generate_instance(
            seed,
            config=_config_for(subtype, max_rounds=args.max_rounds, max_retries=args.max_invalid_retries),
        )
        for subtype, seed in seeds
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    conditions: dict[str, dict[str, Any]] = {}
    condition_rows: dict[str, list[dict[str, Any]]] = {}
    for tool_choice in ("auto", "required"):
        rows = _run_condition(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            tool_choice=tool_choice,
            seeds=seeds,
            max_rounds=args.max_rounds,
            max_retries=args.max_invalid_retries,
            max_new_tokens=args.max_new_tokens,
            parallel_tool_calls=args.parallel_tool_calls,
            instances=instances,
        )
        trajectory_path = args.output_dir / f"{tool_choice}.jsonl"
        with trajectory_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        condition_rows[tool_choice] = rows
        conditions[tool_choice] = {
            "trajectory_file": str(trajectory_path),
            **_condition_summary(rows),
        }

    paired_rows = _paired_episode_rows(condition_rows["auto"], condition_rows["required"])
    paired_path = args.output_dir / "paired.jsonl"
    with paired_path.open("w", encoding="utf-8") as handle:
        for row in paired_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    auto_summary = conditions["auto"]
    required_summary = conditions["required"]
    numeric_delta = {
        key: float(auto_summary[key]) - float(required_summary[key])
        for key in auto_summary
        if isinstance(auto_summary.get(key), (int, float))
        and isinstance(required_summary.get(key), (int, float))
    }
    numeric_delta["subtype_success"] = {
        subtype: float(auto_summary["subtype_success"].get(subtype, 0.0))
        - float(required_summary["subtype_success"].get(subtype, 0.0))
        for subtype in subtypes
    }

    summary = {
        "model": args.model,
        "base_url": args.base_url,
        "output_mode": "native_tools",
        "episodes_per_subtype": args.episodes_per_subtype,
        "total_episodes_per_condition": len(seeds),
        "fixed_seed_schedule": {subtype: [seed for current_subtype, seed in seeds if current_subtype == subtype] for subtype in subtypes},
        "conditions": conditions,
        "paired_episodes_file": str(paired_path),
        "paired_outcomes": {
            outcome: sum(row["outcome"] == outcome for row in paired_rows)
            for outcome in ("both_success", "auto_only_success", "required_only_success", "neither_success")
        },
        "delta_auto_minus_required": numeric_delta,
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
