"""Test-only model-vs-model runner for the three new ItemGame subtypes.

The legacy :class:`BaseItemGame` is intentionally kept Ego-centric for the
existing benchmark.  This module provides the separate v0 self-play path:
the game owns state and rules, while ``SelfPlayRunner`` asks a policy for an
action for whichever agent owns the current turn.  No partner action is
created by the environment.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .config import ItemGameConfig
from .generator import ItemGameInstance, generate_instance


class SelfPlayPolicy(Protocol):
    """Minimal policy interface used by the test-only runner."""

    def generate(
        self,
        *,
        agent: str,
        observation: str,
        legal_actions: Sequence[str],
        context: Sequence[Mapping[str, str]],
    ) -> str:
        ...


def _format_set(items: set[str] | frozenset[str]) -> str:
    return "{" + ",".join(sorted(items)) + "}"


def _normalize_set_spacing(action: str) -> str:
    """Accept optional whitespace after commas without changing semantics."""

    def normalize(match: re.Match[str]) -> str:
        values = [value.strip() for value in match.group(1).split(",") if value.strip()]
        return "{" + ",".join(values) + "}"

    return re.sub(r"\{([^{}]*)\}", normalize, action)


@dataclass
class SelfPlayEpisodeResult:
    seed: int
    subtype: str
    ground_truth: dict[str, Any]
    turns: list[dict[str, Any]]
    terminal: dict[str, Any]
    diagnostics: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "subtype": self.subtype,
            "ground_truth": self.ground_truth,
            "turns": self.turns,
            "terminal": self.terminal,
            "diagnostics": self.diagnostics,
        }


class SelfPlayItemGame:
    """Pure state-transition engine for test-only self-play.

    Only public actions are stored in ``public_history``.  Goals and holdings
    are always private until the owner explicitly discloses them with INFORM.
    """

    SUPPORTED_SUBTYPES = (
        "collaboration",
        "request_surplus_reroute",
        "respond_to_give_request",
    )

    def __init__(self, instance: ItemGameInstance, config: ItemGameConfig):
        if instance.subtype not in self.SUPPORTED_SUBTYPES:
            raise ValueError(
                "self-play v0 supports only collaboration, request_surplus_reroute, "
                "and respond_to_give_request"
            )
        if config.max_total_turns < 1:
            raise ValueError("max_total_turns must be positive")
        self.instance = instance
        self.config = config
        self.goals = {agent: set(goal) for agent, goal in instance.goals.items()}
        self.holdings = {agent: set(items) for agent, items in instance.holdings.items()}
        self.current_agent = (
            str(instance.active_partner)
            if instance.subtype == "respond_to_give_request"
            else "EGO"
        )
        self.done = False
        self.terminal_reason: str | None = None
        self.total_turns = 0
        self.communication_used = 0
        self.public_history: list[dict[str, Any]] = []
        self.public_facts: dict[str, dict[str, set[str]]] = {
            agent: {} for agent in self.players
        }
        self.pending_query: dict[str, str] | None = None
        self.pending_proposal: dict[str, Any] | None = None
        self.agreements: list[dict[str, Any]] = []
        self.committed: dict[str, set[str]] = {}
        self.join_coalition: frozenset[str] | None = None

    @property
    def players(self) -> tuple[str, ...]:
        return tuple(self.instance.goals)

    @property
    def items(self) -> tuple[str, ...]:
        return self.instance.items

    @property
    def communication_left(self) -> int:
        return max(0, self.config.communication_budget - self.communication_used)

    def get_legal_actions(self, agent: str) -> tuple[str, ...]:
        """Return actions for exactly one agent-owned turn."""

        if self.done or agent != self.current_agent:
            return ()
        if self.pending_query is not None:
            if agent != self.pending_query["responder"]:
                return ()
            field = self.pending_query["field"]
            return (
                f"INFORM {self.pending_query['requester']} {field} "
                f"{_format_set(self.goals[agent] if field == 'GOAL' else self.holdings[agent])}",
            )
        if self.pending_proposal is not None:
            if agent != self.pending_proposal["responder"]:
                return ()
            return ("ACT ACCEPT", "ACT REJECT")

        required = self._required_give(agent)
        if required is not None:
            agreement = required
            return (
                f"ACT GIVE {_format_set(agreement['items'])} TO "
                f"{agreement['receiver']}",
            )

        actions: list[str] = []
        if self.communication_left:
            for other in self.players:
                if other == agent:
                    continue
                actions.extend((f"QUERY {other} GOAL", f"QUERY {other} HOLDINGS"))
                actions.extend((
                    f"INFORM {other} GOAL {_format_set(self.goals[agent])}",
                    f"INFORM {other} HOLDINGS {_format_set(self.holdings[agent])}",
                ))
                for item in self._proposal_items(agent, other):
                    actions.append(
                        f"PROPOSE GIVE {{giver={agent},receiver={other},items={_format_set({item})}}}"
                    )
                    actions.append(
                        f"PROPOSE GIVE {{giver={other},receiver={agent},items={_format_set({item})}}}"
                    )

        if self.instance.subtype == "collaboration" and self.join_coalition is None:
            if self.pending_proposal is None:
                actions.append("PROPOSE JOIN {EGO,P1}")

        if self._can_commit(agent):
            actions.extend(
                f"ACT COMMIT {_format_set(subset)}"
                for subset in self._item_subsets(self.holdings[agent])
            )
        return tuple(dict.fromkeys(actions))

    def _proposal_items(self, agent: str, other: str) -> tuple[str, ...]:
        """Return request-relevant singleton items without revealing labels."""
        if self.instance.subtype == "respond_to_give_request":
            if agent == self.instance.active_partner and other == "EGO":
                return tuple(sorted(self.goals[agent] - self.holdings[agent]))
            if agent == "EGO" and other == self.instance.active_partner:
                return tuple(sorted(self.goals[agent] - self.holdings[agent]))
        return self.items

    def get_observation(self, agent: str) -> str:
        """Render only the state and public information visible to ``agent``."""

        if agent not in self.goals:
            raise ValueError(f"unknown ItemGame agent {agent!r}")
        lines = [
            "You are an agent in a sequential Item Coalition Game.",
            f"Your identity: {agent}",
            f"Your goal: {_format_set(self.goals[agent])}",
            f"Your holdings: {_format_set(self.holdings[agent])}",
            f"Current actor: {self.current_agent}",
            f"Turn: {self.total_turns}/{self.config.max_total_turns}",
            f"Communication budget: {self.communication_used}/{self.config.communication_budget}",
        ]
        known = {
            other: {
                key: _format_set(value) for key, value in facts.items()
            }
            for other, facts in self.public_facts.items()
            if other != agent and facts
        }
        lines.append(f"Publicly disclosed facts: {known if known else 'none'}")
        if self.public_history:
            lines.append("Public interaction history:")
            lines.extend(
                f"- turn {entry['turn']}: {entry['agent']} {entry['action']}"
                for entry in self.public_history
            )
        else:
            lines.append("Public interaction history: none")
        if self.pending_query is not None:
            lines.append(
                f"Pending query: {self.pending_query['requester']} asks "
                f"{self.pending_query['responder']} for {self.pending_query['field']}."
            )
        if self.pending_proposal is not None:
            proposal = self.pending_proposal
            if proposal["type"] == "GIVE":
                lines.append(
                    "Pending proposal: PROPOSE GIVE "
                    f"{{giver={proposal['giver']},receiver={proposal['receiver']},"
                    f"items={_format_set(proposal['items'])}}}"
                )
            else:
                lines.append("Pending proposal: PROPOSE JOIN {EGO,P1}")
        if self.join_coalition is not None:
            lines.append(f"Accepted coalition: {_format_set(set(self.join_coalition))}")
        active = [
            agreement for agreement in self.agreements if not agreement.get("fulfilled", False)
        ]
        if active:
            lines.append(f"Unfulfilled accepted agreements: {len(active)}")
        lines.append("Legal actions:")
        lines.extend(f"- {action}" for action in self.get_legal_actions(agent))
        return "\n".join(lines)

    def step(self, agent: str, action: str) -> tuple[str, float, bool, dict[str, Any]]:
        if self.done:
            raise RuntimeError("cannot act in a finished self-play ItemGame")
        if agent != self.current_agent:
            raise ValueError(f"it is {self.current_agent}'s turn, not {agent}'s")
        action = _normalize_set_spacing(" ".join(str(action).strip().split()))
        legal = self.get_legal_actions(agent)
        if action not in legal:
            raise ValueError(f"illegal self-play action {action!r}")

        before = self._snapshot()
        self.public_history.append({"turn": self.total_turns, "agent": agent, "action": action})
        self.total_turns += 1
        self.communication_used += float(
            action.startswith(("QUERY ", "INFORM ", "PROPOSE "))
        )

        if self.pending_query is not None:
            self._apply_inform(agent, action)
        elif self.pending_proposal is not None:
            self._apply_proposal_response(agent, action)
        elif self._required_give(agent) is not None:
            self._apply_give(agent, action)
        elif action.startswith("QUERY "):
            self._apply_query(agent, action)
        elif action.startswith("INFORM "):
            self._apply_proactive_inform(agent, action)
        elif action.startswith("PROPOSE GIVE "):
            self._apply_give_proposal(agent, action)
        elif action == "PROPOSE JOIN {EGO,P1}":
            self._apply_join_proposal(agent)
        elif action.startswith("ACT COMMIT "):
            self._apply_commit(agent, action)
        else:
            raise ValueError(f"unsupported self-play action {action!r}")

        if not self.done and self.total_turns >= self.config.max_total_turns:
            self._finish("turn_limit")
        info = self.diagnostics()
        info.update({"before": before, "agent": agent, "action": action})
        reward = 1.0 if self.done and self.terminal_success else 0.0
        return self._public_event(), reward, self.done, info

    def finish_invalid(self, reason: str = "invalid_action") -> dict[str, Any]:
        self._finish(reason)
        return self.diagnostics()

    def diagnostics(self) -> dict[str, float]:
        ego_success = self._goal_satisfied("EGO")
        all_success = all(self._goal_satisfied(agent) for agent in self.players)
        agreements_fulfilled = all(
            agreement.get("fulfilled", False) for agreement in self.agreements
        )
        return {
            "ego_goal_success": float(ego_success),
            "partner_goal_success": float(all_success and ego_success),
            "all_agent_goal_success": float(all_success),
            "agreements_fulfilled": float(agreements_fulfilled),
            "coalition_valid": float(self.join_coalition is not None),
            "communication_used": float(self.communication_used),
            "total_turns": float(self.total_turns),
            "terminal_success": float(self.done and self.terminal_success),
            "invalid_action": float(self.terminal_reason == "invalid_action"),
            "turn_limit": float(self.terminal_reason == "turn_limit"),
        }

    @property
    def terminal_success(self) -> bool:
        if self.instance.subtype == "collaboration":
            if self.join_coalition != frozenset(("EGO", "P1")):
                return False
            if set(self.committed) != set(self.join_coalition):
                return False
            pool = set().union(*(self.committed[agent] for agent in self.join_coalition))
            goal_success = self.goals["EGO"].issubset(pool)
        else:
            goal_success = self._goal_satisfied("EGO")
        return bool(goal_success and all(
            agreement.get("fulfilled", False) for agreement in self.agreements
        ))

    def _apply_query(self, agent: str, action: str) -> None:
        match = re.fullmatch(r"QUERY (\w+) (GOAL|HOLDINGS)", action)
        if match is None or match.group(1) not in self.players or match.group(1) == agent:
            raise ValueError(f"invalid QUERY action {action!r}")
        self.pending_query = {
            "requester": agent,
            "responder": match.group(1),
            "field": match.group(2),
        }
        self.current_agent = match.group(1)

    def _apply_inform(self, agent: str, action: str) -> None:
        assert self.pending_query is not None
        requester = self.pending_query["requester"]
        field = self.pending_query["field"]
        expected = self.goals[agent] if field == "GOAL" else self.holdings[agent]
        match = re.fullmatch(rf"INFORM {re.escape(requester)} {field} (\{{[^}}]*\}})", action)
        if match is None or self._parse_set(match.group(1)) != expected:
            raise ValueError("INFORM must truthfully answer the pending query")
        self.public_facts[agent][field.lower()] = set(expected)
        self.pending_query = None
        self.current_agent = requester

    def _apply_proactive_inform(self, agent: str, action: str) -> None:
        match = re.fullmatch(r"INFORM (\w+) (GOAL|HOLDINGS) (\{[^}]*\})", action)
        if match is None or match.group(1) not in self.players or match.group(1) == agent:
            raise ValueError(f"invalid INFORM action {action!r}")
        target, field, raw = match.groups()
        expected = self.goals[agent] if field == "GOAL" else self.holdings[agent]
        if self._parse_set(raw) != expected:
            raise ValueError("INFORM must truthfully disclose the actor's own state")
        self.public_facts[agent][field.lower()] = set(expected)
        self.current_agent = target

    def _apply_give_proposal(self, agent: str, action: str) -> None:
        match = re.fullmatch(
            r"PROPOSE GIVE \{giver=(\w+),receiver=(\w+),items=(\{[^}]*\})\}", action
        )
        if match is None:
            raise ValueError(f"invalid GIVE proposal {action!r}")
        giver, receiver, raw_items = match.groups()
        items = self._parse_set(raw_items)
        if (
            giver not in self.players
            or receiver not in self.players
            or receiver == giver
            or not items
            or agent not in {giver, receiver}
        ):
            raise ValueError("GIVE proposal has invalid participants or items")
        responder = receiver if giver == agent else giver
        self.pending_proposal = {
            "type": "GIVE",
            "proposer": agent,
            "responder": responder,
            "giver": giver,
            "receiver": receiver,
            "items": items,
        }
        self.current_agent = responder

    def _apply_join_proposal(self, agent: str) -> None:
        if set(self.players) != {"EGO", "P1"}:
            raise ValueError("Collaboration JOIN requires EGO and P1")
        receiver = "P1" if agent == "EGO" else "EGO"
        self.pending_proposal = {
            "type": "JOIN",
            "proposer": agent,
            "responder": receiver,
            "receiver": receiver,
            "coalition": frozenset(("EGO", "P1")),
        }
        self.current_agent = receiver

    def _apply_proposal_response(self, agent: str, action: str) -> None:
        assert self.pending_proposal is not None
        proposal = self.pending_proposal
        if action == "ACT REJECT":
            self.pending_proposal = None
            self.current_agent = proposal["proposer"]
            return
        if action != "ACT ACCEPT":
            raise ValueError("pending proposal requires ACT ACCEPT or ACT REJECT")
        if proposal["type"] == "GIVE":
            self.agreements.append({
                "type": "GIVE",
                "giver": proposal["giver"],
                "receiver": proposal["receiver"],
                "items": frozenset(proposal["items"]),
                "fulfilled": False,
            })
            giver = proposal["giver"]
            self.pending_proposal = None
            self.current_agent = giver
            return
        self.join_coalition = proposal["coalition"]
        self.agreements.append({
            "type": "JOIN",
            "coalition": proposal["coalition"],
            "fulfilled": False,
        })
        proposer = proposal["proposer"]
        self.pending_proposal = None
        self.current_agent = proposer

    def _apply_give(self, agent: str, action: str) -> None:
        agreement = self._required_give(agent)
        assert agreement is not None
        expected = f"ACT GIVE {_format_set(agreement['items'])} TO {agreement['receiver']}"
        if action != expected:
            raise ValueError("ACT GIVE must exactly match the accepted proposal")
        if not agreement["items"].issubset(self.holdings[agent]):
            raise ValueError("giver does not hold every proposed item")
        self.holdings[agent] -= set(agreement["items"])
        self.holdings[agreement["receiver"]].update(agreement["items"])
        agreement["fulfilled"] = True
        self.current_agent = agreement["receiver"]

    def _apply_commit(self, agent: str, action: str) -> None:
        match = re.fullmatch(r"ACT COMMIT (\{[^}]*\})", action)
        if match is None:
            raise ValueError(f"invalid COMMIT action {action!r}")
        committed = self._parse_set(match.group(1))
        if not committed.issubset(self.holdings[agent]):
            raise ValueError("an agent can commit only items it currently holds")
        if self.instance.subtype == "collaboration" and self.join_coalition is None:
            raise ValueError("JOIN must be accepted before collaboration COMMIT")
        self.committed[agent] = set(committed)
        if self.instance.subtype == "collaboration":
            remaining = [member for member in self.join_coalition if member not in self.committed]
            if remaining:
                self.current_agent = sorted(remaining)[0]
            else:
                for agreement in self.agreements:
                    if agreement["type"] == "JOIN":
                        agreement["fulfilled"] = True
                self._finish("goal_success" if self.terminal_success else "goal_failure")
        elif agent == "EGO":
            self._finish("goal_success" if self.terminal_success else "goal_failure")
        else:
            self.current_agent = "EGO"

    def _required_give(self, agent: str) -> dict[str, Any] | None:
        for agreement in self.agreements:
            if (
                agreement.get("type") == "GIVE"
                and not agreement.get("fulfilled")
                and agreement["giver"] == agent
            ):
                return agreement
        return None

    def _can_commit(self, agent: str) -> bool:
        if self.instance.subtype == "collaboration":
            return self.join_coalition is not None and agent in self.join_coalition
        return not any(
            not agreement.get("fulfilled") and agreement.get("giver") == agent
            for agreement in self.agreements
        )

    def _goal_satisfied(self, agent: str) -> bool:
        return self.goals[agent].issubset(self.holdings[agent])

    @staticmethod
    def _item_subsets(items: set[str]) -> tuple[frozenset[str], ...]:
        ordered = tuple(sorted(items))
        return tuple(
            frozenset(item for index, item in enumerate(ordered) if mask & (1 << index))
            for mask in range(1 << len(ordered))
        )

    def _parse_set(self, raw: str) -> frozenset[str]:
        if not raw.startswith("{") or not raw.endswith("}"):
            raise ValueError(f"invalid set {raw!r}")
        values = tuple(value.strip() for value in raw[1:-1].split(",") if value.strip())
        items = frozenset(values)
        if len(items) != len(values) or not items.issubset(set(self.items)):
            raise ValueError(f"invalid item set {raw!r}")
        return items

    def _parse_action(self, action: str) -> str:
        return _normalize_set_spacing(" ".join(action.strip().split()))

    def _snapshot(self) -> dict[str, Any]:
        return {
            "holdings": {agent: sorted(items) for agent, items in self.holdings.items()},
            "current_agent": self.current_agent,
            "pending_query": dict(self.pending_query) if self.pending_query else None,
            "pending_proposal": bool(self.pending_proposal),
        }

    def _public_event(self) -> str:
        if not self.public_history:
            return ""
        return self.public_history[-1]["action"]

    def _finish(self, reason: str) -> None:
        self.done = True
        self.terminal_reason = reason


class SelfPlayRunner:
    """Drive one self-play episode with one shared policy object."""

    def __init__(
        self,
        policy: SelfPlayPolicy,
        config: ItemGameConfig,
        *,
        instance_factory: Callable[[int, ItemGameConfig], ItemGameInstance] | None = None,
    ):
        self.policy = policy
        self.config = config
        self.instance_factory = instance_factory or (
            lambda seed, cfg: generate_instance(seed, config=cfg)
        )
        self.contexts: dict[str, list[dict[str, str]]] = {}

    def run_episode(self, seed: int) -> SelfPlayEpisodeResult:
        instance = self.instance_factory(seed, self.config)
        game = SelfPlayItemGame(instance, self.config)
        self.contexts = {agent: [] for agent in game.players}
        turns: list[dict[str, Any]] = []

        while not game.done:
            agent = game.current_agent
            observation = game.get_observation(agent)
            legal_actions = game.get_legal_actions(agent)
            if not legal_actions:
                game.finish_invalid("no_legal_action")
                turns.append({
                    "turn": game.total_turns,
                    "agent": agent,
                    "observation": observation,
                    "legal_actions": [],
                    "reason": "",
                    "action": "",
                    "raw_response": "",
                    "valid": False,
                })
                break

            raw_response = self.policy.generate(
                agent=agent,
                observation=observation,
                legal_actions=legal_actions,
                context=tuple(self.contexts[agent]),
            )
            raw_response = str(raw_response)
            reason, answer = self._parse_response(raw_response)
            canonical = _normalize_set_spacing(" ".join(answer.strip().split())) if answer else ""
            canonical_map = {action.lower(): action for action in legal_actions}
            action = canonical_map.get(canonical.lower())
            valid = action is not None
            self.contexts[agent].extend((
                {"role": "user", "content": observation},
                {"role": "assistant", "content": raw_response},
            ))
            record = {
                "turn": game.total_turns,
                "agent": agent,
                "observation": observation,
                "legal_actions": list(legal_actions),
                "reason": reason,
                "action": action or answer,
                "raw_response": raw_response,
                "valid": valid,
            }
            turns.append(record)
            if not valid:
                game.finish_invalid("invalid_action")
                break
            game.step(agent, action)

        terminal = {
            "done": game.done,
            "reason": game.terminal_reason,
            "current_agent": game.current_agent,
            "holdings": {agent: sorted(items) for agent, items in game.holdings.items()},
            "committed": {agent: sorted(items) for agent, items in game.committed.items()},
            "terminal_success": game.terminal_success,
        }
        return SelfPlayEpisodeResult(
            seed=seed,
            subtype=instance.subtype,
            ground_truth={
                "agents": list(instance.goals),
                "goals": {agent: sorted(goal) for agent, goal in instance.goals.items()},
                "initial_holdings": {
                    agent: sorted(items) for agent, items in instance.holdings.items()
                },
                "active_partner": instance.active_partner,
                "request_case": instance.request_case,
                "partner_roles": dict(instance.partner_roles),
                "partner_policies": dict(instance.partner_policies),
            },
            turns=turns,
            terminal=terminal,
            diagnostics=game.diagnostics(),
        )

    @staticmethod
    def _parse_response(response: str) -> tuple[str, str]:
        answer_match = re.search(
            r"<answer>\s*(.*?)\s*</answer>\s*$", response, re.DOTALL | re.IGNORECASE
        )
        reason_match = re.search(
            r"<reason>\s*(.*?)\s*</reason>", response, re.DOTALL | re.IGNORECASE
        )
        if answer_match is None:
            # Raw exact actions are useful for deterministic fake policies.
            return "", response.strip()
        return (reason_match.group(1).strip() if reason_match else "", answer_match.group(1).strip())


class HuggingFaceSelfPlayPolicy:
    """Small sequential HF policy wrapper; all agents share one model object."""

    def __init__(self, model_path: str, *, max_new_tokens: int = 1024, device: str = "auto"):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - exercised only on model machines
            raise RuntimeError("HuggingFaceSelfPlayPolicy requires torch and transformers") from exc
        self.max_new_tokens = max_new_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model_device = device if device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.bfloat16 if model_device.startswith("cuda") else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype=dtype, device_map="auto" if device == "auto" else None,
            trust_remote_code=True,
        )
        if device != "auto":
            self.model.to(model_device)
        self._torch = torch

    def generate(self, *, agent: str, observation: str, legal_actions: Sequence[str], context: Sequence[Mapping[str, str]]) -> str:
        system = (
            f"You are {agent} in a multi-agent Item Coalition Game. Keep your reasoning private. "
            "Use only the listed legal action. Return brief reasoning inside <reason>...</reason> "
            "and exactly one action inside <answer>...</answer>."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(dict(message) for message in context)
        messages.append({
            "role": "user",
            "content": observation + "\n\nLegal actions:\n" + "\n".join(legal_actions),
        })
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        generated = output[0, inputs["input_ids"].shape[-1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True)


def _build_config(subtype: str, max_total_turns: int) -> ItemGameConfig:
    if subtype == "collaboration":
        return ItemGameConfig(
            generator="pure_collaboration", subtype="collaboration",
            self_play=True, max_total_turns=max_total_turns,
        )
    return ItemGameConfig(
        generator="mixed_incentive", subtype=subtype,
        self_play=True, max_total_turns=max_total_turns,
    )


def main() -> None:  # pragma: no cover - integration entrypoint
    parser = argparse.ArgumentParser(description="Run test-only ItemGame model self-play")
    parser.add_argument("--model", required=True, help="local HuggingFace model directory")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=840000)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--max-total-turns", type=int, default=16)
    parser.add_argument(
        "--subtype", choices=("all", *SelfPlayItemGame.SUPPORTED_SUBTYPES), default="all"
    )
    parser.add_argument("--output", type=Path, default=Path("item_game_self_play.jsonl"))
    args = parser.parse_args()
    policy = HuggingFaceSelfPlayPolicy(args.model, max_new_tokens=args.max_new_tokens)
    subtypes = list(SelfPlayItemGame.SUPPORTED_SUBTYPES) if args.subtype == "all" else [args.subtype]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for subtype_index, subtype in enumerate(subtypes):
            config = _build_config(subtype, args.max_total_turns)
            runner = SelfPlayRunner(policy, config)
            for episode in range(args.episodes):
                seed = args.seed + subtype_index * 10000 + episode
                handle.write(json.dumps(runner.run_episode(seed).to_dict(), ensure_ascii=False) + "\n")
    print(f"wrote self-play results to {args.output}")


if __name__ == "__main__":
    main()
