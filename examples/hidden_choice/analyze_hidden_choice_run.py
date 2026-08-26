#!/usr/bin/env python3
"""Reconstruct exact Hidden Choice diagnostics from a completed rollout."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

TIERS = {"Near": 0.05, "Medium": 0.25, "Far": 1.0}
CONDITIONS = {
    "NoQuery": "no_query",
    "Necessary": "necessary_query",
    "Irrelevant": "irrelevant_uncertainty",
    "Selective": "selective_query",
}
TIER_ORDER = tuple(TIERS)
CONDITION_ORDER = tuple(CONDITIONS)
MODE_ORDER = ("Hidden", "Full")


def parse_tag(tag: str):
    match = re.fullmatch(
        r"HC-(Near|Medium|Far)-(NoQuery|Necessary|Irrelevant|Selective)-(Hidden|Full)",
        tag,
    )
    if match is None:
        raise ValueError(f"unexpected Hidden Choice tag {tag!r}")
    tier, condition_label, mode = match.groups()
    tag_index = (
        TIER_ORDER.index(tier) * len(CONDITION_ORDER) * len(MODE_ORDER)
        + CONDITION_ORDER.index(condition_label) * len(MODE_ORDER)
        + MODE_ORDER.index(mode)
    )
    return {
        "tier": tier,
        "magnitude": TIERS[tier],
        "condition": CONDITIONS[condition_label],
        "mode": mode.lower(),
        "seed_offset": -5 * tag_index,
    }


def _mean(values):
    values = [float(value) for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _rate(numerator, denominator):
    return float(numerator) / denominator if denominator else None


def reconstruct_trajectory(turns):
    from roll.agentic.env.hidden_choice.config import HiddenChoiceConfig
    from roll.agentic.env.hidden_choice.game import HiddenChoiceGame
    from roll.agentic.env.hidden_choice.generator import generate_instance

    turns = sorted(turns, key=lambda row: row["turn_index"])
    spec = parse_tag(turns[0]["tag"])
    seed_match = re.search(r"_(\d+)$", turns[0]["trajectory_id"])
    if seed_match is None:
        raise ValueError(f"trajectory id has no seed: {turns[0]['trajectory_id']!r}")
    seed = int(seed_match.group(1)) + spec["seed_offset"]
    config = HiddenChoiceConfig(margin_magnitude=spec["magnitude"])
    instance = generate_instance(seed, spec["condition"], config)
    full_information = spec["mode"] == "full"
    game = HiddenChoiceGame(instance, full_information=full_information)
    protocol_failure = False
    stopping_failure = False
    first_action = str(turns[0].get("parsed_action", ""))

    for turn in turns:
        action = str(turn.get("parsed_action", ""))
        if bool(turn.get("valid_action")) and action in game.legal_actions():
            game.step(action)
            continue
        protocol_failure = True
        stopping_failure = bool(
            action.startswith("ASK ") and not full_information and game.query_used
        )
        break

    if game.records:
        info = game.terminal_metrics(stopping_failure=stopping_failure)
        path_regret = sum(record["decision_regret"] for record in game.records)
    else:
        info = {
            "benchmark_success": 0.0,
            "over_querying": 0.0,
            "under_querying": 0.0,
            "query_selection_correct": 0.0,
            "post_query_action_correct": 0.0,
            "full_info_action_correct": 0.0,
            "final_action_optimal": 0.0,
        }
        path_regret = None
    should_ask = game.communication_decision.should_ask
    first_ask = first_action.startswith("ASK ")
    correct_query_eligible = bool(not full_information and should_ask and first_ask)
    post_query_eligible = bool(
        correct_query_eligible
        and game.records
        and game.records[0].get("query_correct") == 1.0
    )
    max_voi = max(
        (value for _, value in game.communication_decision.gross_voi),
        default=0.0,
    )
    return {
        **spec,
        "tag": turns[0]["tag"],
        "trajectory_id": turns[0]["trajectory_id"],
        "rollout_index": turns[0]["rollout_index"],
        "oracle_margin": max_voi - instance.communication_cost,
        "first_ask": float(first_ask),
        "ask_act_correct": float(
            bool(game.records and game.records[0].get("optimal_action") == 1.0)
        ),
        "over_querying": float(info.get("over_querying", 0.0)),
        "under_querying": float(info.get("under_querying", 0.0)),
        "query_selection_correct": float(info.get("query_selection_correct", 0.0)),
        "query_selection_eligible": float(correct_query_eligible),
        "post_query_action_correct": float(info.get("post_query_action_correct", 0.0)),
        "post_query_eligible": float(post_query_eligible),
        "final_action_optimal": float(info.get("final_action_optimal", 0.0)),
        "full_info_action_correct": float(info.get("full_info_action_correct", 0.0)),
        "benchmark_success": float(info.get("benchmark_success", 0.0)),
        "total_utility": game.total_reward,
        "path_regret": path_regret,
        "protocol_failure": float(protocol_failure),
        "stopping_failure": float(stopping_failure),
        "turns": len(turns),
    }


def aggregate(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[(record["tier"], record["condition"], record["mode"])].append(record)
    rows = []
    for (tier, condition, mode), group in sorted(
        grouped.items(),
        key=lambda item: (
            TIER_ORDER.index(item[0][0]),
            tuple(CONDITIONS.values()).index(item[0][1]),
            MODE_ORDER.index(item[0][2].title()),
        ),
    ):
        query_denominator = int(sum(record["query_selection_eligible"] for record in group))
        post_denominator = int(sum(record["post_query_eligible"] for record in group))
        rows.append(
            {
                "margin_tier": tier,
                "oracle_margin": group[0]["oracle_margin"],
                "condition": condition,
                "mode": mode,
                "trajectories": len(group),
                "ask_rate": _mean(record["first_ask"] for record in group),
                "ask_act_accuracy": _mean(record["ask_act_correct"] for record in group),
                "over_query_rate": _mean(record["over_querying"] for record in group),
                "under_query_rate": _mean(record["under_querying"] for record in group),
                "query_selection_accuracy": _rate(
                    sum(record["query_selection_correct"] for record in group),
                    query_denominator,
                ),
                "post_query_action_accuracy": _rate(
                    sum(record["post_query_action_correct"] for record in group),
                    post_denominator,
                ),
                "final_action_accuracy": _mean(record["final_action_optimal"] for record in group),
                "full_info_action_accuracy": _mean(
                    record["full_info_action_correct"] for record in group
                ) if mode == "full" else None,
                "benchmark_success_rate": _mean(record["benchmark_success"] for record in group),
                "mean_total_utility": _mean(record["total_utility"] for record in group),
                "mean_path_regret": _mean(record["path_regret"] for record in group),
                "protocol_failure_rate": _mean(record["protocol_failure"] for record in group),
                "stopping_failure_rate": _mean(record["stopping_failure"] for record in group),
                "mean_turns": _mean(record["turns"] for record in group),
            }
        )

    hidden = [record for record in records if record["mode"] == "hidden"]
    by_margin = defaultdict(list)
    for record in hidden:
        by_margin[record["oracle_margin"]].append(record["first_ask"])
    ask_curve = [
        {"oracle_margin": margin, "ask_rate": _mean(values), "trajectories": len(values)}
        for margin, values in sorted(by_margin.items())
    ]
    return {"rows": rows, "ask_curve": ask_curve, "trajectories": len(records)}


def _percent(value):
    return "N/A" if value is None else f"{100 * value:.1f}%"


def render_markdown(summary):
    lines = [
        "# Hidden Choice diagnostic",
        "",
        "| Margin | Condition | Mode | N | Ask | Ask/Act acc. | Over-query | Under-query | Query selection | Post-query act | Final act | Full-info act | Utility | Path regret | Protocol fail | Stop fail |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {oracle_margin:+.2f} | {condition} | {mode} | {trajectories} | {ask} | {askact} | {over} | {under} | {selection} | {post} | {final} | {full} | {utility:.3f} | {regret} | {protocol} | {stop} |".format(
                **row,
                ask=_percent(row["ask_rate"]),
                askact=_percent(row["ask_act_accuracy"]),
                over=_percent(row["over_query_rate"]),
                under=_percent(row["under_query_rate"]),
                selection=_percent(row["query_selection_accuracy"]),
                post=_percent(row["post_query_action_accuracy"]),
                final=_percent(row["final_action_accuracy"]),
                full=_percent(row["full_info_action_accuracy"]),
                utility=row["mean_total_utility"],
                regret=("N/A" if row["mean_path_regret"] is None else f"{row['mean_path_regret']:.3f}"),
                protocol=_percent(row["protocol_failure_rate"]),
                stop=_percent(row["stopping_failure_rate"]),
            )
        )
    lines.extend(["", "## P(ASK | oracle margin)", "", "| Delta | N | Ask rate |", "|---:|---:|---:|"])
    for point in summary["ask_curve"]:
        lines.append(
            f"| {point['oracle_margin']:+.2f} | {point['trajectories']} | {_percent(point['ask_rate'])} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    turns_path = args.run_dir / "preflight" / "turns.jsonl"
    turns = [json.loads(line) for line in turns_path.read_text().splitlines() if line.strip()]
    grouped = defaultdict(list)
    for turn in turns:
        grouped[(turn["trajectory_id"], turn["rollout_index"], turn["tag"])].append(turn)
    records = [reconstruct_trajectory(group) for group in grouped.values()]
    summary = aggregate(records)
    json_path = args.run_dir / "hidden_choice_diagnostic.json"
    markdown_path = args.run_dir / "hidden_choice_diagnostic.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    markdown_path.write_text(render_markdown(summary))
    print(markdown_path.read_text())


if __name__ == "__main__":
    main()
