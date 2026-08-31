"""Protocol-only smoke test for Qwen3 native ItemGame tool calling."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from roll.agentic.env.item_game.config import ItemGameConfig
from roll.agentic.env.item_game.generator import generate_instance
from roll.agentic.env.item_game.synchronous_self_play import (
    SynchronousItemGame,
    VLLMSelfPlayPolicy,
    _reason_is_english,
    _validate_tool_call_schema,
)

from examples.item_game.smoke_test_vllm_structured_output import wait_for_vllm


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Qwen3 native ItemGame tool calls")
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--tool-choice", choices=("auto", "required"), default="auto",
        help="Use auto to isolate the Qwen/Hermes parser path from required guided decoding.",
    )
    parser.add_argument("--ready-timeout", type=float, default=600.0)
    parser.add_argument("--ready-interval", type=float, default=5.0)
    parser.add_argument("--output", help="Optional JSONL file containing per-case results")
    args = parser.parse_args()
    if args.cases < 50:
        parser.error("--cases must be at least 50")

    identity = wait_for_vllm(
        args.base_url, args.api_key,
        timeout=args.ready_timeout, interval=args.ready_interval,
    )
    config = ItemGameConfig(
        generator="pure_collaboration", subtype="collaboration",
        self_play=True, randomize_items=False, max_rounds=2,
    )
    game = SynchronousItemGame(generate_instance(7, config=config), config)
    other = next(player for player in game.players if player != "P0")
    own_item = sorted(game.holdings["P0"])[0]
    cases = (
        (f"Ask {other} for their goal.", "QUERY", {"recipient": other, "field": "GOAL"}),
        (f"Ask {other} for their holdings.", "QUERY", {"recipient": other, "field": "HOLDINGS"}),
        (f"Truthfully tell {other} your holdings.", "INFORM", {"recipient": other, "field": "HOLDINGS", "value": sorted(game.holdings["P0"])}),
        (f"Give {own_item} to {other}.", "GIVE", {"recipient": other, "items": [own_item]}),
        (f"Ask {other} to transfer {own_item} to you.", "REQUEST_TRANSFER", {"recipient": other, "items": [own_item]}),
        (f"Propose a coalition with {other}.", "PROPOSE_JOIN", {"recipient": other}),
        (f"Commit {own_item}.", "COMMIT", {"items": [own_item]}),
        ("Take no proactive action.", "PASS", {}),
    )
    available = game.get_available_actions("P0", phase="decision")
    policy = VLLMSelfPlayPolicy(
        args.base_url, args.model, api_key=args.api_key,
        max_new_tokens=args.max_tokens, output_mode="native_tools",
        native_tool_choice=args.tool_choice,
    )
    counts = Counter()
    details: list[dict[str, object]] = []
    for index in range(args.cases):
        intent, expected_name, expected_arguments = cases[index % len(cases)]
        row: dict[str, object] = {
            "case": index, "intent": intent,
            "expected": {"tool_name": expected_name, "arguments": expected_arguments},
        }
        counts["cases"] += 1
        try:
            output = policy.generate(
                agent="P0",
                observation=(
                    "This is a trivial protocol-grounding case. Realize the stated intent exactly.\n"
                    f"P0 holdings: {sorted(game.holdings['P0'])}. Other active player: {other}.\n"
                    f"Intent: {intent}"
                ),
                legal_actions=(), context=(), available_actions=available,
            )
        except Exception as exc:  # pragma: no cover - live endpoint
            counts["request_failed"] += 1
            row.update(stage="request", error=f"{type(exc).__name__}: {exc}")
            details.append(row)
            continue

        reason = output.reason.strip()
        if reason:
            counts["reason_nonempty"] += 1
            if _reason_is_english(reason):
                counts["reason_english"] += 1
        calls = output.tool_calls
        if calls:
            counts["tool_call_present"] += 1
        if len(calls) == 1:
            counts["exactly_one"] += 1
        generic = any(call.tool_name.lower() in {"message", "send_message"} for call in calls)
        counts["generic_message_tool"] += int(generic)
        schema_valid = False
        schema_error = None
        if len(calls) == 1:
            try:
                _validate_tool_call_schema(calls[0], available)
                schema_valid = True
                counts["schema_valid"] += 1
            except ValueError as exc:
                schema_error = str(exc)
        semantic_match = bool(
            schema_valid
            and calls[0].tool_name == expected_name
            and dict(calls[0].arguments) == expected_arguments
        )
        counts["semantic_match"] += int(semantic_match)
        usage = dict(output.usage or {})
        counts["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
        counts["completion_tokens"] += int(usage.get("completion_tokens", 0))
        row.update(
            reason=output.reason,
            tool_call_count=len(calls),
            tool_calls=[{"tool_name": call.tool_name, "arguments": dict(call.arguments)} for call in calls],
            tool_schema_valid=schema_valid,
            semantic_match=semantic_match,
            schema_error=schema_error,
            usage=usage,
        )
        details.append(row)

    total = counts["cases"]
    summary = {
        "protocol": "native_tools",
        "constraint_transport": f"tools + tool_choice={args.tool_choice}",
        "tool_choice": args.tool_choice,
        "server_identity": identity,
        "cases": total,
        "reason_nonempty_rate": counts["reason_nonempty"] / total,
        "english_reason_rate": counts["reason_english"] / total,
        "tool_call_present_rate": counts["tool_call_present"] / total,
        "exactly_one_tool_call_rate": counts["exactly_one"] / total,
        "tool_schema_valid_rate": counts["schema_valid"] / total,
        "trivial_semantic_match_rate": counts["semantic_match"] / total,
        "generic_message_tool_rate": counts["generic_message_tool"] / total,
        "request_failed": counts["request_failed"],
        "mean_prompt_tokens": counts["prompt_tokens"] / total,
        "mean_completion_tokens": counts["completion_tokens"] / total,
        "failure_details": [row for row in details if row.get("error") or not row.get("semantic_match", False)],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            for row in details:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    passed = (
        summary["reason_nonempty_rate"] >= 0.99
        and summary["exactly_one_tool_call_rate"] >= 0.99
        and summary["tool_schema_valid_rate"] >= 0.99
        and summary["trivial_semantic_match_rate"] >= 0.99
        and summary["generic_message_tool_rate"] == 0
        and summary["request_failed"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
