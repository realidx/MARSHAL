#!/usr/bin/env python3
"""Reconstruct exact Hidden Choice diagnostics from a completed rollout."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from math import sqrt

TIERS = {"Near": 0.05, "Medium": 0.25, "Far": 1.0}
CONDITIONS = {
    "NoQuery": "no_query",
    "Necessary": "necessary_query",
    "Irrelevant": "irrelevant_uncertainty",
    "Selective": "selective_query",
    # Appended to preserve seed offsets for legacy NoQuery/Necessary/
    # Irrelevant/Selective runs.
    "CostSuppressed": "cost_suppressed",
}
TIER_ORDER = tuple(TIERS)
CONDITION_ORDER = tuple(CONDITIONS)
MODE_ORDER = ("Hidden", "Full", "Forced")


def parse_tag(tag: str):
    match = re.fullmatch(
        r"HC-(Near|Medium|Far)-(NoQuery|CostSuppressed|Necessary|Irrelevant|Selective)-(Hidden|Full|Forced)",
        tag,
    )
    if match is None:
        raise ValueError(f"unexpected Hidden Choice tag {tag!r}")
    tier, condition_label, mode = match.groups()
    legacy_conditions = ("NoQuery", "Necessary", "Irrelevant", "Selective")
    if condition_label in legacy_conditions and mode in ("Hidden", "Full"):
        # Preserve the seed mapping used by all existing runs.
        tag_index = (
            TIER_ORDER.index(tier) * len(legacy_conditions) * 2
            + legacy_conditions.index(condition_label) * 2
            + (0 if mode == "Hidden" else 1)
        )
    else:
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


def _wilson(successes, trials, z=1.96):
    """Approximate 95% binomial interval for reproducible small-N reports."""
    if not trials:
        return None
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    half = z * sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def recover_semantic_action(turn, legal_actions):
    """Recover one legal action from the relaxed `<answer> ACTION` protocol."""
    parsed = str(turn.get("parsed_action", ""))
    legal = {str(action).lower(): str(action) for action in legal_actions}
    if parsed.lower() in legal:
        return legal[parsed.lower()]
    raw = str(turn.get("raw_response", ""))
    match = re.search(
        r"<answer>\s*((?:ASK|ACT)\s+[A-Za-z][A-Za-z0-9_-]*)",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return None
    return legal.get(" ".join(match.group(1).split()).lower())


def strict_answer_protocol_valid(turn, legal_actions):
    """Validate the V3 protocol: `<answer>` + one action, no close required."""
    raw = str(turn.get("raw_response", ""))
    match = re.search(
        r"(?:<reason>.*?</reason>\s*)?<answer>\s*((?:ASK|ACT)\s+[A-Za-z][A-Za-z0-9_-]*)"
        r"(?:</answer>)?\s*$",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return False
    legal = {str(action).lower() for action in legal_actions}
    return " ".join(match.group(1).split()).lower() in legal


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
    forced_information = spec["mode"] == "forced"
    game = HiddenChoiceGame(
        instance,
        full_information=full_information,
        forced_information_fact=instance.pivotal_fact if forced_information else None,
    )
    protocol_failure = False
    stopping_failure = False
    strict_protocol_valid = True
    semantic_validities = []
    first_action = ""

    for turn in turns:
        strict_valid = strict_answer_protocol_valid(turn, game.legal_actions())
        strict_protocol_valid = strict_protocol_valid and strict_valid
        action = recover_semantic_action(turn, game.legal_actions())
        semantic_validities.append(action is not None)
        if len(semantic_validities) == 1:
            first_action = action or ""
        if action is not None and action in game.legal_actions():
            game.step(action)
            continue
        protocol_failure = True
        stopping_failure = bool(
            (action or "").startswith("ASK ")
            and not full_information
            and game.query_used
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
    first_semantic_valid = bool(semantic_validities and semantic_validities[0])
    correct_query_eligible = bool(
        first_semantic_valid and not full_information and should_ask and first_ask
    )
    post_query_eligible = bool(
        correct_query_eligible
        and game.records
        and len(semantic_validities) > 1
        and semantic_validities[1]
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
        "family_id": instance.family_id,
        "rollout_index": turns[0]["rollout_index"],
        "oracle_margin": max_voi - instance.communication_cost,
        "strict_protocol_valid": float(strict_protocol_valid),
        "semantic_action_valid": float(all(semantic_validities)),
        "voi_policy_eligible": float(first_semantic_valid),
        "first_ask": float(first_ask),
        "ask_act_correct": float(bool(first_semantic_valid and game.records and game.records[0].get("optimal_action") == 1.0)),
        "over_querying": float(info.get("over_querying", 0.0)) if first_semantic_valid else None,
        "under_querying": float(info.get("under_querying", 0.0)) if first_semantic_valid else None,
        "query_selection_correct": float(info.get("query_selection_correct", 0.0)),
        "query_selection_eligible": float(correct_query_eligible),
        "post_query_action_correct": float(info.get("post_query_action_correct", 0.0)),
        "post_query_eligible": float(post_query_eligible),
        "final_action_optimal": float(info.get("final_action_optimal", 0.0)) if first_semantic_valid else None,
        "full_info_action_correct": float(info.get("full_info_action_correct", 0.0)),
        "forced_info_action_correct": float(
            info.get("final_action_optimal", 0.0) if forced_information else 0.0
        ),
        "benchmark_success": float(info.get("benchmark_success", 0.0)),
        "total_utility": game.total_reward,
        "path_regret": path_regret,
        "protocol_failure": float(protocol_failure),
        "stopping_failure": float(stopping_failure),
        "turns": len(turns),
    }


def aggregate(records):
    # A matched pair is only formed when hidden/full runs reconstruct the same
    # exact family_id. This prevents silently treating different states as
    # controls when an old run used different seed offsets.
    full_by_family = {
        record["family_id"]: record
        for record in records
        if record["mode"] == "full"
    }
    for record in records:
        if record["mode"] == "hidden":
            matched = full_by_family.get(record["family_id"])
            record["matched_full_info_correct"] = (
                matched["full_info_action_correct"] if matched is not None else None
            )
            record["under_query_given_full_correct"] = (
                record["under_querying"]
                if matched is not None and matched["full_info_action_correct"] == 1.0
                else None
            )
        else:
            record["matched_full_info_correct"] = None
            record["under_query_given_full_correct"] = None
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
                "strict_protocol_validity": _mean(record["strict_protocol_valid"] for record in group),
                "semantic_action_validity": _mean(record["semantic_action_valid"] for record in group),
                "voi_policy_coverage": _mean(record["voi_policy_eligible"] for record in group),
                "ask_rate": _mean(record["first_ask"] if record["voi_policy_eligible"] else None for record in group),
                "ask_rate_ci": _wilson(
                    sum(record["first_ask"] for record in group if record["voi_policy_eligible"]),
                    sum(1 for record in group if record["voi_policy_eligible"]),
                ),
                "ask_act_accuracy": _mean(record["ask_act_correct"] if record["voi_policy_eligible"] else None for record in group),
                "over_query_rate": _mean(record["over_querying"] for record in group),
                "under_query_rate": _mean(record["under_querying"] for record in group),
                "under_query_rate_ci": _wilson(
                    sum(record["under_querying"] for record in group if record["voi_policy_eligible"]),
                    sum(1 for record in group if record["voi_policy_eligible"]),
                ),
                "query_selection_accuracy": _rate(
                    sum(
                        record["query_selection_correct"]
                        for record in group
                        if record["voi_policy_eligible"]
                    ),
                    query_denominator,
                ),
                "post_query_action_accuracy": _rate(
                    sum(
                        record["post_query_action_correct"]
                        for record in group
                        if record["post_query_eligible"]
                    ),
                    post_denominator,
                ),
                "final_action_accuracy": _mean(record["final_action_optimal"] for record in group),
                "full_info_action_accuracy": _mean(
                    record["full_info_action_correct"] for record in group
                ) if mode == "full" else None,
                "under_query_given_full_correct": _mean(
                    record["under_query_given_full_correct"] for record in group
                ) if mode == "hidden" else None,
                "benchmark_success_rate": _mean(record["benchmark_success"] for record in group),
                "voi_policy_success_rate": _mean(
                    record["benchmark_success"] if record["voi_policy_eligible"] else None
                    for record in group
                ),
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
        by_margin[round(float(record["oracle_margin"]), 2)].append(
            record["first_ask"] if record["voi_policy_eligible"] else None
        )
    ask_curve = [
        {"oracle_margin": margin, "ask_rate": _mean(values), "trajectories": len(values)}
        for margin, values in sorted(by_margin.items())
    ]
    matched_hidden = [
        record for record in hidden if record.get("under_query_given_full_correct") is not None
    ]
    return {
        "rows": rows,
        "ask_curve": ask_curve,
        "trajectories": len(records),
        "matched_pair_count": len(matched_hidden),
        "matched_under_query_given_full_correct": _mean(
            record["under_query_given_full_correct"] for record in matched_hidden
        ),
    }


def _percent(value):
    return "N/A" if value is None else f"{100 * value:.1f}%"


def render_markdown(summary):
    lines = [
        "# Hidden Choice diagnostic",
        "",
        "The report separates strict envelope compliance, recoverable semantic actions, and VOI policy metrics. VOI metrics are computed only for trajectories whose first action is semantically recoverable. Matched hidden/full metrics are reported only when family_id agrees exactly.",
        "",
        "| Margin | Condition | Mode | N | Strict | Semantic | VOI cov. | ASK | Over-query | Under-query | Under-query\n(full-info correct) | Query selection | Post-query act | VOI success | Full-info act | Protocol fail |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {oracle_margin:+.2f} | {condition} | {mode} | {trajectories} | {strict} | {semantic} | {coverage} | {ask} | {over} | {under} | {under_matched} | {selection} | {post} | {voisuccess} | {full} | {protocol} |".format(
                **row,
                strict=_percent(row["strict_protocol_validity"]),
                semantic=_percent(row["semantic_action_validity"]),
                coverage=_percent(row["voi_policy_coverage"]),
                ask=_percent(row["ask_rate"]),
                over=_percent(row["over_query_rate"]),
                under=_percent(row["under_query_rate"]),
                under_matched=_percent(row["under_query_given_full_correct"]),
                selection=_percent(row["query_selection_accuracy"]),
                post=_percent(row["post_query_action_accuracy"]),
                voisuccess=_percent(row["voi_policy_success_rate"]),
                full=_percent(row["full_info_action_accuracy"]),
                utility=row["mean_total_utility"],
                regret=("N/A" if row["mean_path_regret"] is None else f"{row['mean_path_regret']:.3f}"),
                protocol=_percent(row["protocol_failure_rate"]),
            )
        )
    lines.extend(["", "## P(ASK | oracle margin)", "", "| Delta | N | Ask rate |", "|---:|---:|---:|"])
    for point in summary["ask_curve"]:
        lines.append(
            f"| {point['oracle_margin']:+.2f} | {point['trajectories']} | {_percent(point['ask_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## Matched hidden/full control",
            "",
            f"Exact family matches: {summary.get('matched_pair_count', 0)}",
            f"Under-query rate conditioned on matched full-info correctness: {_percent(summary.get('matched_under_query_given_full_correct'))}",
        ]
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
