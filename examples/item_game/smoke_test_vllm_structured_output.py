"""Run 100 trivial Qwen3/vLLM action calls before the ItemGame pilot.

This intentionally tests the inference/serialization boundary only.  It does
not run a game episode or the formal subtype suite.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from roll.agentic.env.item_game.config import ItemGameConfig
from roll.agentic.env.item_game.generator import generate_instance
from roll.agentic.env.item_game.synchronous_self_play import (
    SynchronousItemGame,
    VLLMSelfPlayPolicy,
    _load_json_answer,
    _parse_decision_output,
    _validate_json_enums,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Qwen3 vLLM structured action output")
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()

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
    )
    schema = game.get_action_schema("P0")
    counts = Counter()
    semantic_matches = 0
    for index in range(args.cases):
        name, intent, expected = intents[index % len(intents)]
        output = policy.generate(
            agent="P0",
            observation=(
                "You are running a protocol grounding smoke test.\n"
                f"Your identity is P0. Other active player: {other}.\n"
                f"Your holdings: {sorted(game.holdings['P0'])}.\n"
                f"Smoke-test intent: {intent}\n"
                "Return the JSON action that realizes exactly this intent."
            ),
            legal_actions=SynchronousItemGame.MESSAGE_TEMPLATES + SynchronousItemGame.STATE_ACTION_TEMPLATES,
            context=(),
            action_schema=schema,
        )
        counts["cases"] += 1
        if output.reasoning.strip():
            counts["reasoning_present"] += 1
        content_is_json = False
        if output.content.strip() and not any(tag in output.content for tag in ("<reason>", "<answer>", "```")):
            try:
                value = _load_json_answer(output.content)
                content_is_json = True
                _parse_decision_output(output.content, agent="P0")
                _validate_json_enums(value, players=game.players, items=game.items, response=False)
                counts["schema_valid"] += 1
                objects = value if isinstance(value, list) else [value]
                if len(objects) == 1 and objects[0] == expected:
                    semantic_matches += 1
            except (TypeError, ValueError):
                counts["schema_invalid"] += 1
        else:
            counts["schema_invalid"] += 1
        counts["content_json_only"] += int(content_is_json)

    summary = {
        "cases": counts["cases"],
        "reasoning_present_rate": counts["reasoning_present"] / counts["cases"],
        "content_json_only_rate": counts["content_json_only"] / counts["cases"],
        "schema_valid_rate": counts["schema_valid"] / counts["cases"],
        "trivial_semantic_match_rate": semantic_matches / counts["cases"],
        "schema_invalid": counts["schema_invalid"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["schema_valid_rate"] >= 0.99 and summary["reasoning_present_rate"] >= 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
