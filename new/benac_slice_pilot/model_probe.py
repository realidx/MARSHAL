"""Probe selected two-player BENAC slices with a live OpenAI-compatible model.

The model controls its first k actual decisions on every reached branch.  The
certified reference policy controls the other player and resumes ego control
after k.  The same entrance world and random seed are paired across k=1 and
all longer feasible lengths.  Information arms force the selected root query,
then compare a visible versus hidden private answer at the remaining model
decision.  A one-decision response is scored by its exact oracle action regret;
longer trajectories use sampled terminal utility.
Protocol failures retain no fabricated game utility.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from training.b_sft.social_private_teacher import observed_slots
from training.b_sft.social_b_oracle import NAMES, canonical
from training.social_mixed.short_interaction import ShortInteraction, decision_request, decode_action


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "examples/social_mixed/interaction_bank_v1/tasks.jsonl"
TOL = 1e-8


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_seed(*parts) -> int:
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=False).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def mean_interval(values: list[float]) -> dict:
    """Normal 95% interval over independently seeded trajectory replicas."""
    if not values:
        return dict(n=0, mean=None, se=None, ci95=None)
    n = len(values)
    mean = float(np.mean(values))
    se = float(np.std(values, ddof=1) / math.sqrt(n)) if n > 1 else None
    ci = [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None
    return dict(n=n, mean=mean, se=se, ci95=ci)


def http_complete(args, payload: dict) -> dict:
    """Make one request; return transport and response errors as data."""
    body = dict(payload)
    body.update(model=args.model, max_tokens=args.max_tokens,
                temperature=args.temperature, top_p=args.top_p,
                top_k=args.top_k, repetition_penalty=1.0)
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("BENAC_P_VLLM_API_KEY") or "EMPTY"
    request = Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    start = time.monotonic()
    try:
        with urlopen(request, timeout=args.timeout) as response:
            raw = json.load(response)
        choice = raw["choices"][0]
        completion = dict(raw_message=choice["message"], finish_reason=choice.get("finish_reason"))
        if not isinstance(completion["raw_message"], dict):
            raise ValueError("Expected an assistant message object")
        return dict(status="ok", completion=completion, usage=raw.get("usage"),
                    elapsed_seconds=round(time.monotonic() - start, 3))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return dict(status="transport_failure", error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=round(time.monotonic() - start, 3))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return dict(status="response_failure", error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=round(time.monotonic() - start, 3))


def verify_environment(env: ShortInteraction, selected: dict, candidate: dict) -> None:
    if env.tree.certificate["policy_sha256"] != selected["policy_sha256"]:
        raise ValueError(f"Selected policy changed for {selected['id']}")
    if env.tree.certificate["policy_sha256"] != candidate["policy_sha256"]:
        raise ValueError(f"Candidate policy changed for {selected['id']}")
    root = env.tree.entries[env.root]
    actions = [action.to_dict() for action in root.actions]
    if actions != candidate["root_actions"]:
        raise ValueError(f"Root legal actions changed for {selected['id']}")
    if not np.allclose(env.weights, candidate["entry_world_weights"], atol=TOL, rtol=0):
        raise ValueError(f"Entry belief changed for {selected['id']}")
    value = float(np.dot(env.weights, env.tree.values[env.root][:, env.ego]))
    if not np.isclose(value, candidate["V_oracle"], atol=TOL, rtol=0):
        raise ValueError(f"Oracle reference value changed for {selected['id']}")
    q = [float(np.dot(env.weights, env.tree.values[child][:, env.ego])) for child in root.children]
    if not np.allclose(q, candidate["root_Q"], atol=TOL, rtol=0):
        raise ValueError(f"Root action values changed for {selected['id']}")


def _visible_input(env: ShortInteraction, node, entry, events: list[dict],
                   hidden_slot: tuple[int, int] | None = None) -> dict:
    actor = env.ego
    inp = deepcopy(env.task["input"])
    inp.update(
        current_state=node.state.public_state(),
        private_results=[dict(player=p, goal=g, preference=NAMES[value])
                         for p, g, value in node.state.private_results[actor]
                         if (p, g) != hidden_slot],
        pending_offer=None if node.pending is None else node.pending.to_dict(),
        voluntary_history=deepcopy(events),
        legal_actions=[action.to_dict() for action in entry.actions],
    )
    # decision_request renders the live action as a P history task with no
    # supplied belief. Keep the same fields on the input used by decode_action.
    inp["belief_source"] = "history"
    inp["supplied_belief"] = dict(known_preferences=[], unresolved_preferences=[], support="")
    return inp


def _mask_chronology(request: dict, inp: dict, selected: dict, ego: int) -> None:
    """Correct the private-access clause for the selected public query event."""
    from training.b_sft.social_named_probe import Names

    names = Names(inp, 0)
    player, goal = selected["query_slot"]
    ego_name = names.players[ego]
    event = f"{ego_name} investigated {names.players[player]} / {names.goals[goal]}. "
    original = event + f"The answer was delivered only to {ego_name}; it is not public. No commitments changed."
    replacement = (event + "The private answer for this investigation is unavailable to you for this decision; "
                   "it is not public. No commitments changed.")
    user_message = request["messages"][1]
    content = user_message["content"]
    if content.count(original) != 1:
        raise ValueError("Could not identify exactly one selected query event in the masked prompt")
    user_message["content"] = content.replace(original, replacement, 1)


def query_reference(selected: dict, candidate: dict) -> tuple[int, float, float]:
    """Identify the selected physical query and its conditional oracle value."""
    slot = selected.get("query_slot")
    if not isinstance(slot, list) or len(slot) != 2:
        raise ValueError(f"No selected query slot for {selected['id']}")
    k = selected["continuous_slice"]["k"]
    matches = [row for row in candidate["queries"] if row["slot"] == slot]
    if len(matches) != 1:
        raise ValueError(f"Selected query is missing or ambiguous for {selected['id']}")
    query = matches[0]
    action_index = query["root_action_index"]
    action = candidate["root_actions"][action_index]
    if action.get("action") != "INVESTIGATE" or [action["player"], action["goal"]] != slot:
        raise ValueError(f"Query action index changed for {selected['id']}")
    values = [row for row in query["by_k"] if row["k"] == k]
    if len(values) != 1:
        raise ValueError(f"Conditional query value missing for {selected['id']} k={k}")
    full = float(values[0]["query_Q_full"])
    masked = float(values[0]["query_Q_mask"])
    if not np.isclose(full - masked, selected["S_given_query"], atol=TOL, rtol=0):
        raise ValueError(f"Selected information value changed for {selected['id']}")
    return action_index, full, masked


def _observe_information(weights: np.ndarray, tree, action, actor: int, ego: int,
                         world, *, hidden_slot: tuple[int, int] | None) -> np.ndarray:
    """Update ego belief only for a private answer actually available to ego."""
    if actor != ego or action.get("action") != "INVESTIGATE":
        return weights
    slot = (action["player"], action["goal"])
    if slot == hidden_slot:
        return weights
    allowed = np.asarray([candidate[slot[0]][slot[1]] == world[slot[0]][slot[1]]
                          for candidate in tree.worlds], dtype=float)
    updated = weights * allowed
    if updated.sum() <= 0:
        raise AssertionError("Private answer eliminated the realized world")
    return updated / updated.sum()


def _oracle_action_index(env: ShortInteraction, index: int, world_index: int, rng) -> int:
    tree = env.tree
    ids = next(ids for ids in tree.information_groups[index] if world_index in ids)
    probabilities = np.asarray(tree.policy[index][:, world_index], dtype=float)
    # Reading the realized world chooses an information cell, never a distinct
    # action distribution for worlds indistinguishable to the acting player.
    np.testing.assert_allclose(tree.policy[index][:, ids],
                               np.repeat(probabilities[:, None], len(ids), axis=1),
                               atol=1e-8, rtol=0)
    return rng.choices(range(len(probabilities)), weights=probabilities)[0]


def rollout(env: ShortInteraction, selected: dict, candidate: dict, job: dict,
            args, complete_fn=http_complete) -> tuple[dict, list[dict]]:
    """Execute one native trajectory, preserving each actual model request."""
    tree = env.tree
    arm = job.get("arm", "normal")
    if arm not in ("normal", "information_full", "information_masked"):
        raise ValueError(f"Unknown model probe arm: {arm}")
    information_arm = arm != "normal"
    query_index, query_q, query_q_mask = (query_reference(selected, candidate)
                                         if information_arm else (None, None, None))
    hidden_slot = tuple(selected["query_slot"]) if arm == "information_masked" else None
    reference_value = query_q if information_arm else float(candidate["V_oracle"])
    rng = random.Random(job["rollout_seed"])
    world_index = rng.choices(range(len(env.weights)), weights=env.weights)[0]
    world = tree.worlds[world_index]
    index = env.root
    node = deepcopy(tree.entries[index].node)
    node.state.private_results = tuple(
        tuple((p, g, world[p][g]) for p, g in observed_slots(node, actor))
        for actor in range(tree.n)
    )
    events = deepcopy(env.task["input"].get("voluntary_history", []))
    calls = []
    root_action = None
    root_exact_regret = None
    followup_regret = None
    model_decisions = 0
    controlled_decisions = 0
    ego_decisions = 0
    belief_weights = np.asarray(env.weights, dtype=float).copy()
    status = "terminal"
    error = None
    k = job["k"]
    try:
        while tree.entries[index].actor is not None:
            entry = tree.entries[index]
            actor = entry.actor
            if actor == env.ego:
                ego_decisions += 1
            if information_arm and index == env.root:
                if actor != env.ego:
                    raise AssertionError("Forced query root is not an ego decision")
                action_index = query_index
                action = entry.actions[action_index].to_dict()
                root_action = deepcopy(action)
                controlled_decisions += 1
            elif actor == env.ego and controlled_decisions < k:
                inp = _visible_input(env, node, entry, events, hidden_slot)
                request = decision_request(inp)
                if arm == "information_masked":
                    _mask_chronology(request, inp, selected, env.ego)
                seed_family = "information" if information_arm else "normal"
                request["seed"] = stable_seed(args.seed, job["id"], job["replica"],
                                              seed_family, model_decisions)
                request["max_tokens"] = args.max_tokens
                result = complete_fn(args, request)
                call = dict(id=job["id"], category=selected["category"], arm=arm, k=k,
                            replica=job["replica"], decision=model_decisions,
                            rollout_seed=job["rollout_seed"], world_index=world_index,
                            request=request, response_status=result["status"],
                            finish_reason=(result.get("completion") or {}).get("finish_reason"),
                            completion=result.get("completion"), usage=result.get("usage"),
                            elapsed_seconds=result.get("elapsed_seconds"), error=result.get("error"))
                calls.append(call)
                if result["status"] != "ok":
                    status = result["status"]
                    error = result.get("error")
                    break
                completion = result["completion"]
                try:
                    action = decode_action(inp, completion)
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    status = "truncated" if completion.get("finish_reason") == "length" else "invalid_action"
                    error = f"{type(exc).__name__}: {exc}"
                    call["error"] = error
                    break
                lookup = {canonical(action.to_dict()): ai for ai, action in enumerate(entry.actions)}
                action_key = canonical(action)
                if action_key not in lookup:
                    status = "invalid_action"
                    error = "Decoded action is not legal at the reached native node"
                    call["error"] = error
                    break
                action_index = lookup[action_key]
                call["native_action"] = deepcopy(action)
                call["native_node_index"] = index
                if not information_arm and root_action is None:
                    root_action = deepcopy(action)
                    root_exact_regret = float(candidate["root_C"][action_index])
                if information_arm and followup_regret is None:
                    if belief_weights.sum() <= 0:
                        raise AssertionError("Follow-up belief has no support")
                    conditional = belief_weights / belief_weights.sum()
                    values = [float(np.dot(conditional, tree.values[child][:, env.ego]))
                              for child in entry.children]
                    followup_regret = max(0.0, max(values) - values[action_index])
                    call["followup_action_values"] = values
                    call["followup_C"] = followup_regret
                model_decisions += 1
                controlled_decisions += 1
            else:
                action_index = _oracle_action_index(env, index, world_index, rng)
                action = entry.actions[action_index].to_dict()
            if actor != env.ego:
                likelihood = np.asarray(tree.policy[index][action_index], dtype=float)
                belief_weights *= likelihood
                if belief_weights.sum() <= 0:
                    raise AssertionError("Partner action eliminated the realized world")
                belief_weights /= belief_weights.sum()
            node = env.episode.rules.step(node, entry.actions[action_index], realized_world=world)
            belief_weights = _observe_information(
                belief_weights, tree, action, actor, env.ego, world, hidden_slot=hidden_slot)
            events.append(deepcopy(action))
            index = entry.children[action_index]
            if node.state.public_state() != tree.entries[index].node.state.public_state():
                raise AssertionError("Native state diverged from certified tree")
        terminal_utility = (float(env.episode.rules.terminal_payoffs(node, world)[env.ego])
                            if status == "terminal" else None)
    except Exception as exc:
        status = "internal_failure"
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        terminal_utility = None
    result = dict(
        id=job["id"], category=selected["category"], arm=arm, k=k, replica=job["replica"],
        rollout_seed=job["rollout_seed"], world_index=world_index, status=status,
        model_decisions=model_decisions, controlled_decisions=controlled_decisions,
        ego_decisions=ego_decisions,
        root_action=root_action, root_exact_regret=root_exact_regret,
        followup_C=followup_regret, reference_value=reference_value,
        query_Q_mask=query_q_mask,
        terminal_utility=terminal_utility,
        sampled_terminal_regret=(float(reference_value - terminal_utility)
                                 if terminal_utility is not None else None),
        sampled_gap_to_masked_oracle=(float(query_q_mask - terminal_utility)
                                      if arm == "information_masked" and terminal_utility is not None else None),
        error=error,
    )
    for call in calls:
        call["trajectory_status"] = status
        call["terminal_utility"] = terminal_utility
        call["root_exact_regret"] = root_exact_regret
        call["followup_C"] = call.get("followup_C", followup_regret)
        call["reference_value"] = reference_value
        call["query_Q_mask"] = query_q_mask
        call["sampled_terminal_regret"] = result["sampled_terminal_regret"]
    return result, calls


def summarize(selected: list[dict], candidates: dict[str, dict], results: list[dict], protocol: dict) -> dict:
    by_job = {(row["id"], row["replica"], row["k"], row["arm"]): row for row in results}
    groups = []
    paired = []
    adjacent_length_pairs = []
    information_pairs = []
    for row in selected:
        task_id = row["id"]
        selected_k = row["continuous_slice"]["k"]
        normal_lengths = tuple(range(1, candidates[task_id]["max_ego_decisions"] + 1))
        arms = [(k, "normal") for k in normal_lengths]
        if row.get("query_slot") is not None and protocol["information_arms"]:
            arms += [(selected_k, "information_full"),
                     (selected_k, "information_masked")]
        for k, arm in arms:
            items = [r for r in results if r["id"] == task_id and r["k"] == k and r["arm"] == arm]
            terminal = [r for r in items if r["status"] == "terminal"]
            exact_root = [r["root_exact_regret"] for r in terminal if r.get("root_exact_regret") is not None]
            followup = [r["followup_C"] for r in terminal if r.get("followup_C") is not None]
            terminal_regret = [r["sampled_terminal_regret"] for r in terminal]
            query_q_mask = query_reference(row, candidates[task_id])[2] if arm != "normal" else None
            reference_value = (candidates[task_id]["V_oracle"] if arm == "normal"
                               else query_reference(row, candidates[task_id])[1])
            groups.append(dict(
                id=task_id, category=row["category"], arm=arm, k=k,
                selected_continuous_length=(k == selected_k),
                reference_value=reference_value, query_Q_mask=query_q_mask,
                oracle_S_given_query=(row["S_given_query"] if arm != "normal" else None),
                planned=len(items), statuses=dict(Counter(r["status"] for r in items)),
                completion_rate=len(terminal) / len(items) if items else None,
                D_exact_root=mean_interval(exact_root),
                followup_C=mean_interval(followup),
                D_terminal_mc=mean_interval(terminal_regret),
                gap_to_full_information_oracle_mc=mean_interval(terminal_regret),
                gap_to_masked_oracle_mc=mean_interval(
                    [r["sampled_gap_to_masked_oracle"] for r in terminal]
                    if arm == "information_masked" else []),
                terminal_utility=mean_interval([r["terminal_utility"] for r in terminal]),
            ))
        differences = []
        same_root = []
        for replica in {r["replica"] for r in results if r["id"] == task_id}:
            one = by_job.get((task_id, replica, 1, "normal"))
            many = by_job.get((task_id, replica, selected_k, "normal"))
            if one and many and one["status"] == many["status"] == "terminal":
                differences.append(one["terminal_utility"] - many["terminal_utility"])
                same_root.append(one["root_action"] == many["root_action"])
        paired.append(dict(id=task_id, category=row["category"],
                           k_continuous=selected_k, paired_terminal_increment=mean_interval(differences),
                           same_root_action_rate=(sum(same_root) / len(same_root) if same_root else None)))
        for lower, upper in zip(normal_lengths, normal_lengths[1:]):
            increments = []
            for replica in {r["replica"] for r in results if r["id"] == task_id}:
                short = by_job.get((task_id, replica, lower, "normal"))
                long = by_job.get((task_id, replica, upper, "normal"))
                if short and long and short["status"] == long["status"] == "terminal":
                    increments.append(short["terminal_utility"] - long["terminal_utility"])
            adjacent_length_pairs.append(dict(
                id=task_id, category=row["category"], k_short=lower, k_long=upper,
                paired_terminal_increment=mean_interval(increments),
            ))
        if row.get("query_slot") is not None and protocol["information_arms"]:
            differences = []
            valid_pairs = 0
            for replica in {r["replica"] for r in results if r["id"] == task_id}:
                full = by_job.get((task_id, replica, selected_k, "information_full"))
                masked = by_job.get((task_id, replica, selected_k, "information_masked"))
                if full and masked and full["status"] == masked["status"] == "terminal":
                    if full["world_index"] != masked["world_index"]:
                        raise AssertionError("Paired information arms sampled different worlds")
                    valid_pairs += 1
                    differences.append(full["terminal_utility"] - masked["terminal_utility"])
            information_pairs.append(dict(
                id=task_id, category=row["category"], k=selected_k,
                query_slot=row["query_slot"], oracle_S_given_query=row["S_given_query"],
                conditional_query_oracle_value=query_reference(row, candidates[task_id])[1],
                conditional_query_masked_oracle_value=query_reference(row, candidates[task_id])[2],
                paired_completed=valid_pairs,
                model_full_minus_masked_utility=mean_interval(differences),
            ))
    return dict(
        **protocol,
        processed_trajectories=len(results),
        trajectory_statuses=dict(Counter(r["status"] for r in results)),
        groups=groups, paired_comparisons=paired,
        adjacent_length_pairs=adjacent_length_pairs,
        information_pairs=information_pairs,
        trajectories=sorted(results, key=lambda r: (r["id"], r["replica"], r["k"], r["arm"])),
        estimands=dict(k1="Mean exact root C(action) among completed model trajectories",
                       continuous="V_oracle minus sampled native terminal utility; mean/SE/CI conditional on completed trajectories",
                       paired="Shorter-k terminal utility minus longer-k terminal utility under paired entrance-world and rollout seeds",
                       information="Physically force the selected root query in both arms; full reveals its private answer to the model, masked hides only that answer. Compare paired terminal utility. Both arms' sampled regret is a gap to the full-information conditional query oracle Q at k; the masked-oracle Q and S are reported separately.",
                       followup_C="Chosen follow-up action regret under reference continuation and the arm's available-information posterior at the reached public node"),
        note="Protocol failures have no game utility. A COMPLETE marker certifies processing coverage, not model success.",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE,
                        help="JSONL source of the selected native two-player roots")
    parser.add_argument("--selected", type=Path, default=HERE / "pilot_data/selected.jsonl")
    parser.add_argument("--candidates", type=Path, default=HERE / "pilot_data/candidates.jsonl")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicas", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=-1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--information-arms", action=argparse.BooleanOptionalAction, default=True,
                        help="Run paired forced-query full/masked arms on information roots (default: on)")
    args = parser.parse_args(argv)
    if not 1 <= args.replicas <= 512 or not 1 <= args.concurrency <= 64:
        parser.error("replicas must be 1–512 and concurrency 1–64")
    if args.max_tokens < 1 or args.timeout < 1 or not 0 <= args.temperature <= 2 or not 0 < args.top_p <= 1:
        parser.error("Invalid generation or timeout setting")
    if not args.base_url.strip() or not args.model.strip() or not args.checkpoint_hash.strip():
        parser.error("Server URL, model, and checkpoint hash must be nonempty")
    if args.output.exists():
        parser.error(f"Use a new output directory: {args.output}")

    source_path = args.source.resolve()
    selected = read_jsonl(args.selected)
    candidates = {row["id"]: row for row in read_jsonl(args.candidates)}
    tasks = {task["id"]: task for task in read_jsonl(source_path)
             if task.get("training_mode") == "short_interaction"}
    if not selected or len({row["id"] for row in selected}) != len(selected):
        raise ValueError("Selected panel must be nonempty with distinct task IDs")
    environments = {}
    for row in selected:
        task_id = row["id"]
        if task_id not in candidates or task_id not in tasks:
            raise ValueError(f"Selected root missing from candidate/source bank: {task_id}")
        if row["single_decision_slice"]["k"] != 1:
            raise ValueError(f"Expected a k=1 slice: {task_id}")
        k = row["continuous_slice"]["k"]
        if not 2 <= k <= tasks[task_id]["max_ego_decisions"]:
            raise ValueError(f"Invalid continuous length: {task_id}")
        env = ShortInteraction(tasks[task_id], max_decisions=3,
                               seconds=20, max_nodes=30000, max_sweeps=128)
        verify_environment(env, row, candidates[task_id])
        if args.information_arms and row.get("query_slot") is not None:
            query_reference(row, candidates[task_id])
        environments[task_id] = env

    selected_by_id = {row["id"]: row for row in selected}
    jobs = []
    for row in selected:
        k_long = row["continuous_slice"]["k"]
        arms = [("normal", k) for k in range(1, candidates[row["id"]]["max_ego_decisions"] + 1)]
        if args.information_arms and row.get("query_slot") is not None:
            arms += [("information_full", k_long), ("information_masked", k_long)]
        for replica in range(args.replicas):
            for arm, k in arms:
                jobs.append(dict(id=row["id"], arm=arm, k=k, replica=replica,
                                 rollout_seed=stable_seed(args.seed, row["id"], replica)))
    protocol = dict(
        version="benac-2p-closed-loop-model-probe-v2-information-arms",
        source=str(source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT)
                   else source_path), source_sha256=sha256(source_path),
        selected_sha256=sha256(args.selected), candidates_sha256=sha256(args.candidates),
        model=args.model, checkpoint_hash=args.checkpoint_hash,
        base_url=args.base_url, replicas=args.replicas, concurrency=args.concurrency,
        seed=args.seed, temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
        max_tokens=args.max_tokens, timeout=args.timeout,
        planned_roots=len(selected), planned_trajectories=len(jobs),
        normal_lengths_by_root={row["id"]: list(range(1, candidates[row["id"]]["max_ego_decisions"] + 1))
                                for row in selected},
        selected_continuous_lengths={row["id"]: row["continuous_slice"]["k"] for row in selected},
        information_arms=args.information_arms,
        information_mask_scope="Model-facing private answer at controlled decisions only; frozen oracle ego continuation has native information",
        paired_world_and_rollout_seed=True, selected_policy_partner=True,
        oracle_ego_after_k=True, utility="ego native terminal utility",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    results = []
    call_count = 0
    with (args.output / "calls.jsonl").open("w") as handle:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(rollout, environments[job["id"]],
                                   selected_by_id[job["id"]],
                                   candidates[job["id"]], job, args): job
                       for job in jobs}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    trajectory, calls = future.result()
                except Exception as exc:
                    trajectory = dict(**job, status="internal_failure", terminal_utility=None,
                                      error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
                    calls = []
                results.append(trajectory)
                for call in calls:
                    handle.write(json.dumps(call, ensure_ascii=False) + "\n")
                    call_count += 1
                handle.flush()
                if len(results) % 16 == 0 or len(results) == len(jobs):
                    print(f"processed {len(results)}/{len(jobs)} trajectories; {call_count} model calls", flush=True)
    summary = summarize(selected, candidates, results, protocol)
    summary["http_calls_recorded"] = call_count
    summary["calls_sha256"] = sha256(args.output / "calls.jsonl")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    processed = len(results) == len(jobs) and len({(r["id"], r["arm"], r["k"], r["replica"])
                                                      for r in results}) == len(jobs)
    complete = processed and all(r["status"] != "internal_failure" for r in results)
    if complete:
        (args.output / "COMPLETE.json").write_text(json.dumps(dict(
            version=protocol["version"], planned_trajectories=len(jobs),
            processed_trajectories=len(results), http_calls_recorded=call_count,
            checkpoint_hash=args.checkpoint_hash, calls_sha256=summary["calls_sha256"],
            summary_sha256=sha256(args.output / "summary.json"),
            includes_protocol_failures=True,
        ), indent=2, sort_keys=True) + "\n")
    else:
        raise RuntimeError("Some planned trajectories had internal failures; inspect summary.json")
    print(json.dumps(dict(processed_trajectories=len(results), statuses=summary["trajectory_statuses"],
                          calls=call_count, output=str(args.output)), indent=2))
    return summary


if __name__ == "__main__":
    main()
