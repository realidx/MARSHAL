"""Run 100 trivial Qwen3/vLLM action calls before the ItemGame pilot.

This intentionally tests the inference/serialization boundary only.  It does
not run a game episode or the formal subtype suite.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections import Counter

from roll.agentic.env.item_game.config import ItemGameConfig
from roll.agentic.env.item_game.generator import generate_instance
from roll.agentic.env.item_game.synchronous_self_play import (
    SynchronousItemGame,
    VLLMSelfPlayPolicy,
    _load_json_answer,
    _parse_decision_output,
    _reason_is_english,
    _unwrap_reason_action,
    _validate_json_enums,
)


def wait_for_vllm(
    base_url: str,
    api_key: str,
    *,
    timeout: float,
    interval: float,
) -> dict[str, object]:
    """Wait for the OpenAI-compatible vLLM server to finish startup."""
    normalized_url = base_url.rstrip("/")
    if not normalized_url.endswith("/v1"):
        normalized_url += "/v1"
    ready_url = f"{normalized_url}/models"
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    next_status = started

    while True:
        request = urllib.request.Request(
            ready_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                if 200 <= response.status < 300:
                    models_payload = json.loads(response.read().decode("utf-8"))
                    model_ids = [
                        entry.get("id")
                        for entry in models_payload.get("data", [])
                        if isinstance(entry, dict)
                    ]
                    version_url = f"{normalized_url[:-3]}/version"
                    version = None
                    try:
                        version_request = urllib.request.Request(
                            version_url,
                            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                            method="GET",
                        )
                        with urllib.request.urlopen(version_request, timeout=5.0) as version_response:
                            version_payload = json.loads(version_response.read().decode("utf-8"))
                            version = version_payload.get("version")
                    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
                        pass
                    elapsed = time.monotonic() - started
                    print(f"vLLM ready after {elapsed:.1f}s: {ready_url}", flush=True)
                    print(
                        "server_identity="
                        + json.dumps({"version": version, "model_ids": model_ids}),
                        flush=True,
                    )
                    return {"version": version, "model_ids": model_ids}
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
            pass

        now = time.monotonic()
        if now >= deadline:
            raise RuntimeError(
                f"vLLM did not become ready within {timeout:.0f}s: {ready_url}"
            )
        if now >= next_status:
            elapsed = now - started
            print(
                f"waiting for vLLM readiness ({elapsed:.0f}/{timeout:.0f}s): {ready_url}",
                flush=True,
            )
            next_status = now + 30.0
        time.sleep(min(interval, deadline - now))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Qwen3 vLLM structured action output")
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument(
        "--output-mode",
        choices=("reason_action", "action_only"),
        default="reason_action",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=600.0,
        help="Maximum seconds to wait for GET /v1/models (default: 600)",
    )
    parser.add_argument(
        "--ready-interval",
        type=float,
        default=5.0,
        help="Seconds between vLLM readiness checks (default: 5)",
    )
    args = parser.parse_args()

    if args.ready_timeout <= 0 or args.ready_interval <= 0:
        parser.error("--ready-timeout and --ready-interval must be positive")

    server_identity = wait_for_vllm(
        args.base_url,
        args.api_key,
        timeout=args.ready_timeout,
        interval=args.ready_interval,
    )

    config = ItemGameConfig(
        generator="pure_collaboration",
        subtype="collaboration",
        self_play=True,
        randomize_items=False,
        max_rounds=2,
    )
    game = SynchronousItemGame(generate_instance(7, config=config), config)
    other = next(player for player in game.players if player != "P0")
    own_item = sorted(game.holdings["P0"])[0]
    intents = (
        ("QUERY", f"Ask {other} what their goal is.", {"action": "QUERY", "recipient": other, "field": "GOAL"}),
        ("QUERY", f"Ask {other} what items they hold.", {"action": "QUERY", "recipient": other, "field": "HOLDINGS"}),
        ("INFORM", f"Tell {other} your holdings truthfully.", {"action": "INFORM", "recipient": other, "field": "HOLDINGS", "value": sorted(game.holdings["P0"])}),
        ("GIVE", f"Give {own_item} to {other}.", {"action": "GIVE", "recipient": other, "items": [own_item]}),
        ("REQUEST_TRANSFER", f"Ask {other} to transfer {own_item} to you.", {"action": "REQUEST_TRANSFER", "recipient": other, "items": [own_item]}),
        ("PROPOSE_JOIN", f"Propose joining a coalition with {other}.", {"action": "PROPOSE_JOIN", "recipient": other}),
        ("PASS", "Take no action this round.", {"action": "PASS"}),
    )
    policy = VLLMSelfPlayPolicy(
        args.base_url,
        args.model,
        api_key=args.api_key,
        max_new_tokens=args.max_tokens,
        output_mode=args.output_mode,
    )
    schema = game.get_action_schema("P0", output_mode=args.output_mode)
    available_actions = game.get_available_actions("P0", phase="decision")
    if args.output_mode == "reason_action":
        action_schema = schema.get("properties", {}).get("action", {})
        if action_schema.get("type") != "object":
            raise RuntimeError(
                "reason_action smoke schema is malformed: root action must be an object"
            )
        nested_action = action_schema.get("properties", {}).get("action", {})
        if nested_action.get("type") != "string":
            raise RuntimeError(
                "reason_action smoke schema is malformed: action.action must be a string enum"
            )
    counts = Counter()
    semantic_matches = 0
    generic_message_outputs = 0
    failures: list[dict[str, object]] = []
    reason_empty_cases: list[int] = []
    non_english_reason_cases: list[int] = []
    trailing_quote_repairs = 0
    for index in range(args.cases):
        name, intent, expected = intents[index % len(intents)]
        counts["cases"] += 1
        try:
            output = policy.generate(
                agent="P0",
                observation=(
                    "You are running a protocol grounding smoke test.\n"
                    f"Your identity is P0. Other active player: {other}.\n"
                    f"Your holdings: {sorted(game.holdings['P0'])}.\n"
                    f"Smoke-test intent: {intent}\n"
                    + (
                        "Return a JSON object with a concise non-empty reason string and an action field. "
                        "The action field must realize exactly this intent."
                        if args.output_mode == "reason_action"
                        else "Return the JSON action value that realizes exactly this intent."
                    )
                ),
                legal_actions=SynchronousItemGame.MESSAGE_TEMPLATES + SynchronousItemGame.STATE_ACTION_TEMPLATES,
                context=(),
                action_schema=schema,
                available_actions=available_actions,
            )
        except Exception as exc:  # pragma: no cover - exercised against a live server
            counts["request_failed"] += 1
            failures.append({
                "case": index,
                "intent_name": name,
                "intent": intent,
                "stage": "request",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "raw_response": None,
            })
            continue

        stage = "content_guard"
        reason_present = False
        try:
            if not output.content.strip():
                raise ValueError("content is empty")
            if any(tag in output.content for tag in ("<reason>", "<answer>", "```")):
                raise ValueError("content contains a reasoning/answer wrapper or code fence")
            stage = "json_parse"
            raw_content = output.content.strip()
            repaired_content = raw_content[:-1].rstrip() if raw_content.endswith('"') else raw_content
            envelope = _load_json_answer(output.content)
            def has_generic_message_shape(value):
                if isinstance(value, dict):
                    if any(key in value for key in ("type", "to", "content")):
                        return True
                    return any(has_generic_message_shape(child) for child in value.values())
                if isinstance(value, list):
                    return any(has_generic_message_shape(child) for child in value)
                return False

            if has_generic_message_shape(envelope):
                generic_message_outputs += 1
            stage = "envelope_validation"
            if args.output_mode == "reason_action":
                # Count application-level reasoning independently of action
                # shape validation.  A malformed action must not hide the
                # fact that the model produced a non-empty reason.
                if (
                    isinstance(envelope, dict)
                    and isinstance(envelope.get("reason"), str)
                    and envelope["reason"].strip()
                ):
                    counts["reasoning_present"] += 1
                reason, value = _unwrap_reason_action(envelope)
            else:
                reason, value = "", envelope
                if not isinstance(value, (dict, list)):
                    raise ValueError("action-only content must be an object or array of objects")
            reason_present = bool(reason.strip())
            if not reason_present:
                reason_empty_cases.append(index)
            elif args.output_mode == "reason_action":
                if _reason_is_english(reason):
                    counts["english_reason"] += 1
                else:
                    non_english_reason_cases.append(index)
            if repaired_content != raw_content:
                try:
                    json.loads(repaired_content)
                except (TypeError, json.JSONDecodeError):
                    pass
                else:
                    trailing_quote_repairs += 1
            stage = "decision_parse"
            _parse_decision_output(json.dumps(value), agent="P0")
            stage = "enum_validation"
            _validate_json_enums(value, players=game.players, items=game.items, response=False)
            counts["schema_valid"] += 1
            objects = value if isinstance(value, list) else [value]
            if len(objects) == 1 and objects[0] == expected:
                semantic_matches += 1
        except (TypeError, ValueError) as exc:
            counts["schema_invalid"] += 1
            failures.append({
                "case": index,
                "intent_name": name,
                "intent": intent,
                "stage": stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "raw_response": {
                    "reasoning": output.reasoning,
                    "content": output.content,
                },
            })
    summary = {
        "cases": counts["cases"],
        "server_identity": server_identity,
        "constraint_transport": "response_format.json_schema",
        "guided_decoding_backend": "xgrammar",
        "reason_nonempty_rate": counts["reasoning_present"] / counts["cases"],
        "english_reason_rate": (
            counts["english_reason"] / counts["cases"]
            if args.output_mode == "reason_action"
            else None
        ),
        "schema_valid_rate": counts["schema_valid"] / counts["cases"],
        "trivial_semantic_match_rate": semantic_matches / counts["cases"],
        "generic_message_output": generic_message_outputs,
        "schema_invalid": counts["schema_invalid"],
        "request_failed": counts["request_failed"],
        "reason_empty_or_missing": len(reason_empty_cases),
        "reason_empty_or_missing_cases": reason_empty_cases,
        "non_english_reason_cases": non_english_reason_cases,
        "trailing_quote_repairs": trailing_quote_repairs,
        "failure_details": failures,
    }
    print(json.dumps(summary, indent=2))
    passed = (
        summary["schema_valid_rate"] >= 0.99
        and summary["trivial_semantic_match_rate"] >= 0.99
        and summary["request_failed"] == 0
        and summary["generic_message_output"] == 0
        and (
            args.output_mode == "action_only"
            or (
                summary["reason_nonempty_rate"] >= 0.99
                and summary["english_reason_rate"] >= 0.99
            )
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
