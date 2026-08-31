"""Compare legacy DSL, JSON envelope, and native tool calling on trivial intents."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.item_game.smoke_test_vllm_structured_output import wait_for_vllm
from roll.agentic.env.item_game.config import ItemGameConfig
from roll.agentic.env.item_game.generator import generate_instance
from roll.agentic.env.item_game.synchronous_self_play import (
    SynchronousItemGame,
    VLLMSelfPlayPolicy,
    _load_json_answer,
    _parse_decision_output,
    _reason_is_english,
    _typed_decision_to_legacy,
    _unwrap_reason_action,
    _validate_json_enums,
    _validate_tool_call_schema,
)


def raw_completion(base_url, api_key, body):
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    request = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B/C test ItemGame output protocols")
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--cases-per-protocol", type=int, default=24)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--ready-timeout", type=float, default=600)
    parser.add_argument("--ready-interval", type=float, default=5)
    args = parser.parse_args()
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
    item = sorted(game.holdings["P0"])[0]
    intents = (
        (f"Ask {other} for their goal.", {"action": "QUERY", "recipient": other, "field": "GOAL"}),
        (f"Ask {other} for their holdings.", {"action": "QUERY", "recipient": other, "field": "HOLDINGS"}),
        (f"Give {item} to {other}.", {"action": "GIVE", "recipient": other, "items": [item]}),
    )
    available = game.get_available_actions("P0", phase="decision")
    envelope_schema = game.get_action_schema("P0", output_mode="reason_action")
    policies = {
        "B_envelope_json": VLLMSelfPlayPolicy(
            args.base_url, args.model, api_key=args.api_key,
            max_new_tokens=args.max_tokens, output_mode="reason_action",
        ),
        "C_native_tools": VLLMSelfPlayPolicy(
            args.base_url, args.model, api_key=args.api_key,
            max_new_tokens=args.max_tokens, output_mode="native_tools",
            native_tool_choice="auto",
        ),
    }
    stats = defaultdict(Counter)
    outputs = defaultdict(lambda: defaultdict(Counter))

    for protocol in ("A_legacy_xml_dsl", "B_envelope_json", "C_native_tools"):
        for index in range(args.cases_per_protocol):
            intent, expected = intents[index % len(intents)]
            expected_legacy = _typed_decision_to_legacy(expected, agent="P0")
            stats[protocol]["cases"] += 1
            try:
                if protocol == "A_legacy_xml_dsl":
                    payload = raw_completion(args.base_url, args.api_key, {
                        "model": args.model,
                        "messages": [
                            {"role": "system", "content": (
                                "Return <reason>brief private reason</reason> and <answer>one action</answer>. "
                                "Use exactly one DSL action: QUERY <AGENT> FOR THEIR GOAL|HOLDINGS; "
                                "GIVE {<ITEM>} TO <AGENT>; or NO MESSAGE."
                            )},
                            {"role": "user", "content": f"P0 holds {sorted(game.holdings['P0'])}. Intent: {intent}"},
                        ],
                        "temperature": 0, "max_tokens": args.max_tokens,
                        "chat_template_kwargs": {"enable_thinking": False},
                    })
                    message = payload["choices"][0]["message"]
                    text = message.get("content") or ""
                    reason_nonempty = bool(text.split("</reason>", 1)[0].replace("<reason>", "").strip())
                    parsed = _parse_decision_output(text, agent="P0")
                    valid = True
                    match = parsed == expected_legacy
                    canonical = json.dumps(parsed, sort_keys=True)
                    usage = payload.get("usage") or {}
                else:
                    policy = policies[protocol]
                    output = policy.generate(
                        agent="P0", observation=f"Realize this trivial intent exactly: {intent}",
                        legal_actions=(), context=(), action_schema=envelope_schema,
                        available_actions=available,
                    )
                    usage = output.usage or {}
                    if protocol == "B_envelope_json":
                        reason, action = _unwrap_reason_action(_load_json_answer(output.content))
                        _validate_json_enums(action, players=game.players, items=game.items, response=False)
                        valid = True
                        match = action == expected
                        reason_nonempty = bool(reason.strip())
                        canonical = json.dumps(action, sort_keys=True)
                    else:
                        reason_nonempty = bool(output.reason.strip())
                        valid = len(output.tool_calls) == 1
                        if valid:
                            _validate_tool_call_schema(output.tool_calls[0], available)
                        action = ({"action": output.tool_calls[0].tool_name, **dict(output.tool_calls[0].arguments)} if valid else {})
                        match = valid and action == expected
                        canonical = json.dumps(action, sort_keys=True)
                        stats[protocol]["exactly_one"] += int(len(output.tool_calls) == 1)
                stats[protocol]["valid"] += int(valid)
                stats[protocol]["semantic_match"] += int(match)
                stats[protocol]["reason_nonempty"] += int(reason_nonempty)
                stats[protocol]["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
                stats[protocol]["completion_tokens"] += int(usage.get("completion_tokens", 0))
                outputs[protocol][index % len(intents)][canonical] += 1
            except Exception:
                stats[protocol]["request_or_parse_failed"] += 1

    summary = {"server_identity": identity, "protocols": {}}
    for protocol, counter in stats.items():
        total = counter["cases"]
        stability = sum(max(values.values()) for values in outputs[protocol].values()) / total
        summary["protocols"][protocol] = {
            "cases": total,
            "schema_or_protocol_valid_rate": counter["valid"] / total,
            "trivial_semantic_match_rate": counter["semantic_match"] / total,
            "reason_nonempty_rate": counter["reason_nonempty"] / total,
            "output_stability_rate": stability,
            "exactly_one_tool_call_rate": counter["exactly_one"] / total if protocol == "C_native_tools" else None,
            "mean_prompt_tokens": counter["prompt_tokens"] / total,
            "mean_completion_tokens": counter["completion_tokens"] / total,
            "request_or_parse_failed": counter["request_or_parse_failed"],
        }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
