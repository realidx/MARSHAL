"""CPU-only C/S and slice-length pilot on two-player BENAC O roots.

The default source re-screens already generated training-bank roots. A custom
--source can screen fresh oracle-certified roots. D for a real model is left to
the closed-loop probe; uniform play is a declared, model-independent
length-coverage probe.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from new.benac_slice_pilot.evaluate import expected_utility, uniform_probe_regrets
from new.benac_slice_pilot.metrics import masked_answer_value, optimal_value
from training.social_mixed.short_interaction import ShortInteraction


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples/social_mixed/interaction_bank_v1/tasks.jsonl"
HERE = Path(__file__).resolve().parent
TOL = 1e-8


def _stable(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def source_roots(path: Path = SOURCE):
    tasks = [json.loads(line) for line in path.read_text().splitlines() if line]
    return [task for task in tasks if task.get("training_mode") == "short_interaction"]


def complexity(task):
    return (
        len(task["input"]["game"]["goals"]),
        len(task["input"]["legal_actions"]),
        task["max_ego_decisions"],
        task["id"],
    )


def candidate_roots(tasks, per_mode: int):
    """A deterministic bounded scan of simple O roots with/without a query."""
    by_mode = {True: [], False: []}
    for task in tasks:
        has_query = any(action.get("action") == "INVESTIGATE" for action in task["input"]["legal_actions"])
        by_mode[has_query].append(task)
    for rows in by_mode.values():
        rows.sort(key=complexity)
    if per_mode <= 0:
        return sorted(tasks, key=complexity)
    return sorted(by_mode[True][:per_mode] + by_mode[False][:per_mode], key=complexity)


def _best_response(env, k):
    return optimal_value(
        env.episode, ego=env.ego, root_index=env.root,
        root_weights=env.weights, k=k,
    )


def analyze(task, *, max_nodes: int, seconds: float):
    env = ShortInteraction(task, max_decisions=3, max_nodes=max_nodes,
                           max_sweeps=128, seconds=seconds)
    tree = env.tree
    ego = env.ego
    root = tree.entries[env.root]
    max_k = env.max_decisions
    probe = uniform_probe_regrets(
        env.episode, ego=ego, root_index=env.root,
        root_weights=env.weights, max_k=max_k,
    )
    first = _best_response(env, 1)
    if abs(first["value"] - probe["oracle_value"]) > TOL:
        raise ValueError("Selected continuation is not a root best response")
    if len(first["root_action_values"]) != len(root.actions):
        raise AssertionError("Oracle action table has wrong length")
    if not np.allclose(first["root_action_values"],
                       [v[ego] for v in task["teacher"]["action_values"]], atol=TOL, rtol=0):
        raise ValueError("Recomputed root Q disagrees with the source teacher")
    for k in range(2, max_k + 1):
        kth = _best_response(env, k)
        if abs(kth["value"] - probe["oracle_value"]) > TOL:
            raise ValueError(f"Frozen reference is not a best response at k={k}")
        checked = expected_utility(
            env.episode, ego=ego, root_index=env.root,
            root_weights=env.weights, k=k, controlled_policy=kth["policy"],
        )
        if abs(checked - kth["value"]) > TOL:
            raise AssertionError(f"Best-response policy re-evaluation failed at k={k}")
    if min(probe["uniform_regret"]) < -TOL or min(probe["incremental_regret"]) < -TOL:
        raise AssertionError("Uniform probe regret must grow as ego controls more decisions")

    queries = []
    seen_slots = set()
    for ai, action in enumerate(first["root_actions"]):
        if action.get("action") != "INVESTIGATE":
            continue
        slot = (action["player"], action["goal"])
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        answer_mass = {
            name: float(sum(weight for weight, world in zip(env.weights, tree.worlds)
                            if world[slot[0]][slot[1]] == value))
            for value, name in ((1, "want"), (0, "neutral"), (-1, "avoid"))
        }
        by_k = []
        for k in range(1, max_k + 1):
            ablation = masked_answer_value(
                env.episode, ego=ego, root_index=env.root,
                root_weights=env.weights, query_slot=slot, k=k,
            )
            forced = ablation["full"]["root_action_values"][ai] - ablation["masked"]["root_action_values"][ai]
            if forced < -TOL:
                raise AssertionError("A private answer has negative conditional value")
            by_k.append(dict(k=k, S=ablation["S"],
                             S_given_query=max(0.0, forced),
                             query_Q_full=ablation["full"]["root_action_values"][ai],
                             query_Q_mask=ablation["masked"]["root_action_values"][ai]))
        queries.append(dict(slot=list(slot), root_action_index=ai,
                            answer_mass=answer_mass,
                            answer_support=sum(mass > TOL for mass in answer_mass.values()),
                            by_k=by_k))

    q = first["root_action_values"]
    return dict(
        id=task["id"], family=task.get("family"), split=task["split"],
        source=task.get("source", "existing interaction_bank_v1 O root"),
        ego=ego, goals=len(task["input"]["game"]["goals"]),
        n_actions_per_player=task["input"]["game"]["n_actions_per_player"],
        root_actions=first["root_actions"],
        tree_nodes=len(tree.entries), worlds=tree.w,
        max_ego_decisions=max_k,
        policy_sha256=tree.certificate["policy_sha256"],
        entry_world_weights=env.weights.tolist(),
        V_oracle=probe["oracle_value"],
        root_Q=q, root_C=first["root_action_regrets"],
        root_C_max=max(first["root_action_regrets"]),
        uniform_probe_regret_by_k=probe["uniform_regret"],
        uniform_probe_increment_by_k=probe["incremental_regret"],
        queries=queries,
    )


def _eligible_length(row, *, min_increment: float):
    for k, increment in enumerate(row["uniform_probe_increment_by_k"][1:], start=2):
        if increment > min_increment:
            return k
    return None


def _information_length(query, *, min_s: float):
    for metric in query["by_k"][1:]:
        if metric["S_given_query"] > min_s:
            return metric["k"]
    return None


def select(rows, *, min_c: float, min_increment: float, min_s: float, per_group: int):
    """Small nonredundant demonstration set, not a full training-bank recipe."""
    groups = {"action_only": [], "delayed_consequence": [],
              "information_positive": [], "information_zero_control": []}
    for row in rows:
        ordinary_length = _eligible_length(row, min_increment=min_increment)
        # A flat entrance action table does not imply a flat multi-decision
        # slice: the next actual ego decision may still change terminal value.
        if row["root_C_max"] <= min_c:
            if ordinary_length is not None:
                groups["delayed_consequence"].append((row, ordinary_length, None))
            continue
        if ordinary_length is not None and not row["queries"]:
            groups["action_only"].append((row, ordinary_length, None))
        for query in row["queries"]:
            if query["answer_support"] < 2:
                continue
            info_length = _information_length(query, min_s=min_s)
            if info_length is not None:
                groups["information_positive"].append((row, info_length, query))
            elif (ordinary_length is not None
                  and query["by_k"][-1]["S_given_query"] <= TOL
                  and query["by_k"][-1]["S"] <= TOL):
                groups["information_zero_control"].append((row, ordinary_length, query))

    selected = []
    for category, candidates in groups.items():
        candidates.sort(key=lambda item: (item[0]["goals"], item[0]["tree_nodes"],
                                          item[1], item[0]["id"],
                                          () if item[2] is None else tuple(item[2]["slot"])))
        used_families = set()
        chosen = []
        for row, k, query in candidates:
            if row["family"] in used_families:
                continue
            chosen.append((row, k, query))
            used_families.add(row["family"])
            if len(chosen) == per_group:
                break
        if len(chosen) < per_group:
            for row, k, query in candidates:
                if (row, k, query) in chosen:
                    continue
                chosen.append((row, k, query))
                if len(chosen) == per_group:
                    break
        for row, k, query in chosen:
            selected.append(dict(
                id=row["id"], category=category,
                single_decision_slice=dict(k=1, root_C_max=row["root_C_max"]),
                continuous_slice=dict(k=k, uniform_probe_increment=row["uniform_probe_increment_by_k"][k-1]),
                query_slot=None if query is None else query["slot"],
                S_given_query=None if query is None else query["by_k"][k-1]["S_given_query"],
                S_unconditional=None if query is None else query["by_k"][k-1]["S"],
                family=row["family"], policy_sha256=row["policy_sha256"],
            ))
    return selected, {group: len(items) for group, items in groups.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE,
                        help="JSONL of native two-player short O roots (default: existing interaction bank)")
    parser.add_argument("--per-mode", type=int, default=20,
                        help="Scan this many simplest query and nonquery roots; <=0 scans all")
    parser.add_argument("--per-group", type=int, default=2)
    parser.add_argument("--min-c", type=float, default=.1)
    parser.add_argument("--min-increment", type=float, default=.05)
    parser.add_argument("--min-s", type=float, default=.05)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--max-nodes", type=int, default=30000)
    parser.add_argument("--out", type=Path, default=HERE / "pilot_data")
    args = parser.parse_args(argv)
    source_path = args.source.resolve()
    source = source_roots(source_path)
    candidates = candidate_roots(source, args.per_mode)
    rows = []
    exclusions = []
    for index, task in enumerate(candidates, 1):
        try:
            row = analyze(task, max_nodes=args.max_nodes, seconds=args.seconds)
            rows.append(row)
            print(f"{index}/{len(candidates)} {task['id']} C={row['root_C_max']:.3f} "
                  f"queries={len(row['queries'])} nodes={row['tree_nodes']}", flush=True)
        except Exception as exc:
            exclusions.append(dict(id=task["id"], error_type=type(exc).__name__, reason=str(exc)))
            print(f"{index}/{len(candidates)} {task['id']} EXCLUDED {type(exc).__name__}: {exc}", flush=True)
    chosen, category_candidates = select(
        rows, min_c=args.min_c, min_increment=args.min_increment,
        min_s=args.min_s, per_group=args.per_group,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("candidates.jsonl", rows), ("selected.jsonl", chosen), ("exclusions.jsonl", exclusions)):
        (args.out / name).write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in data))
    summary = dict(
        version="benac-2p-consequence-slice-pilot-v1",
        game="native two-player BENAC private-investigation game; generally not zero-sum",
        source=str(source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path),
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        source_roots=len(source), scanned=len(candidates), certified=len(rows),
        excluded=len(exclusions), selected=len(chosen),
        selected_by_category=dict(Counter(item["category"] for item in chosen)),
        category_candidate_counts=category_candidates,
        parameters=dict(per_mode=args.per_mode, per_group=args.per_group,
                        min_c=args.min_c, min_increment=args.min_increment, min_s=args.min_s,
                        seconds=args.seconds, max_nodes=args.max_nodes),
        oracle="Selected certified native policy profile; opponent fixed on all branches; ego best response for controlled decisions",
        information="Mask one private query answer to ego on all controlled later information sets; same physical game and partner policy",
        length="First k actual ego decisions on every reached branch, then frozen ego reference policy",
        model_D="Not measured in this CPU-only builder; uniform probe is not a language model",
    )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
