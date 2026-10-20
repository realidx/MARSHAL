"""Exact finite-policy timing diagnostics; not a production game/solver change.

Run once into this versioned directory. Outputs cannot be overwritten.
"""
from fractions import Fraction as F
from hashlib import sha256
import importlib.util
from itertools import product
import json
from pathlib import Path
import platform
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "new/game_mechanism_design_20261021/verify_contract_witness.py"
VERSION = "game-free-investigation-timing-diagnostic-v1"
CONFIG = {
    "arithmetic": "fractions.Fraction; exhaustive deterministic policy enumeration",
    "investigation_budget": "one per player per game; only A has unknown preferences to query in these toys",
    "query_turn_cost": 0,
    "query_utility_cost": 0,
    "query_observation": "target/use public, exact answer private to A; answers persist",
    "response_objective": "own final utility, then other final utility",
    "fixed_target_control": "two players; fixed relevant pair; one final offer",
    "adaptive_target_control": {
        "players": 2,
        "B_type": "(b0,b1) uniform in {0,1}^2; B knows both bits",
        "logical_preferences": "in each pair exactly one project is WANT (+1), the other AVOID (-1); no neutral types",
        "query_menu": "any of four project preferences; complementary queries are equivalent and canonicalized to two bits",
        "public_event": "independent fair R in {0,1}; only pair R is feasible after revelation",
        "timeline": "optional early query -> public R -> optional late query if unused -> one offer or PASS -> B ACCEPT/REJECT -> terminal",
        "payoff": "accepted project gives A=1, B=+1/-1 according to preference; REJECT/PASS=(0,0)",
        "response": "B strictly accepts WANT, strictly rejects AVOID; no strategic continuation",
        "offers": "one final offer, unchanged by query timing; no rejection penalty",
        "query_before_event_can_be_conditioned_on": "no observations",
        "query_after_event_can_be_conditioned_on": "public R only; never hidden B bits",
    },
    "prior_contract_control": "original 3-contract/3-type/2-offer asymmetric toy, changing only query opportunity cost from one to zero; one query maximum",
    "training_configuration": "not applicable; no model, reward optimization, advantage, batching, validation or checkpoints",
}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def pack(x):
    if isinstance(x, F):
        return {"exact": str(x), "decimal": float(x)}
    if isinstance(x, dict):
        return {str(k): pack(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [pack(v) for v in x]
    return x


def enumerate_policies(relevant_pairs):
    """All policies respect A information sets, including off-path observations.

    B's terminal response is uniquely optimal: accept iff the offered member
    equals b[R]. PASS yields zero, so including it in every context makes the
    enumeration explicit rather than relying on its weak domination.
    """
    worlds = list(product((0, 1), (0, 1), relevant_pairs))
    weight = F(1, len(worlds))
    offers = (None, 0, 1)
    early, late, never = [], [], []
    contexts = list(product(relevant_pairs, (0, 1)))
    for q in (0, 1):
        for choices in product(offers, repeat=len(contexts)):
            policy = dict(zip(contexts, choices))
            value = sum((weight * (policy[(r, (b0, b1)[q])] == (b0, b1)[r])
                         for b0, b1, r in worlds), F(0))
            early.append({"query": q, "offer_policy": list(zip(contexts, choices)), "value": value})
    for targets in product((0, 1), repeat=len(relevant_pairs)):
        query_policy = dict(zip(relevant_pairs, targets))
        for choices in product(offers, repeat=len(contexts)):
            policy = dict(zip(contexts, choices))
            value = sum((weight * (policy[(r, (b0, b1)[query_policy[r]])] == (b0, b1)[r])
                         for b0, b1, r in worlds), F(0))
            late.append({"query_policy": list(query_policy.items()),
                         "offer_policy": list(zip(contexts, choices)), "value": value})
    for choices in product(offers, repeat=len(relevant_pairs)):
        policy = dict(zip(relevant_pairs, choices))
        value = sum((weight * (policy[r] == (b0, b1)[r]) for b0, b1, r in worlds), F(0))
        never.append({"offer_policy": list(policy.items()), "value": value})
    # Any randomized information-set policy is a mixture over these finite
    # pure plans; expectation cannot exceed their maximum against this unique
    # terminal responder. No hidden-world-specific action choice is permitted.
    return {
        "world_count": len(worlds),
        "policy_counts": {"early": len(early), "late": len(late), "never": len(never)},
        "early": max(early, key=lambda p: p["value"]),
        "late": max(late, key=lambda p: p["value"]),
        "never": max(never, key=lambda p: p["value"]),
        "mixed_policy_check": "all randomized plans are convex combinations of enumerated pure plans; same upper bounds",
    }


def main():
    for name in ("results.json", "pipeline_snapshot.json", "SNAPSHOT.json"):
        if (HERE / name).exists():
            raise FileExistsError(f"Closed diagnostic output exists: {name}; use a new version/directory")
    spec = importlib.util.spec_from_file_location("previous_contract_witness", OLD)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    no_query, _, _ = old.relaxed_no_query_upper_bound()
    free_query, policy = old.query_value(0)
    # The imported query_value returns the value of ONE remaining final offer.
    # Under a free query, implement it with the first of two offers; repeat the
    # same type-optimal contract after rejection. Each type gets its maximal
    # possible own payoff, so accepting now is an admissible full-horizon BR.
    # An accepted contract cannot give A more than the typewise maximum over
    # nonnegative-B projects: B can always reject everything to guarantee zero.
    upper = old.mean([max(old.final(t, j)[0] for j in old.ACTIONS) for t in range(3)])
    assert no_query == F(4, 3) and free_query == upper == F(5, 3)
    fixed = enumerate_policies((0,))
    adaptive = enumerate_policies((0, 1))
    assert fixed["early"]["value"] == fixed["late"]["value"] == 1
    assert fixed["never"]["value"] == F(1, 2)
    assert adaptive["early"]["value"] == F(3, 4)
    assert adaptive["late"]["value"] == 1
    assert adaptive["never"]["value"] == F(1, 2)
    assert dict(adaptive["late"]["query_policy"]) == {0: 0, 1: 1}
    results = {
        "version": VERSION,
        "status": "exact-rational-toy-timing-verified-not-native-certified",
        "original_contract_toy_free_query": {
            "best_no_query": no_query, "early_query_X_attained": free_query,
            "typewise_upper_bound_for_any_timing": upper,
            "conditional_contract_policy": policy,
            "conclusion": "querying X immediately is optimal; strict superiority to every delayed-query policy is NOT established",
        },
        "fixed_relevant_target": fixed,
        "later_public_information_selects_relevant_target": adaptive,
        "timing_gap_wait_minus_early": adaptive["late"]["value"] - adaptive["early"]["value"],
        "scope": "two independent finite toy mechanisms plus a free-cost modification of prior contract witness; NOT current alternating native game, not corpus prevalence or production equilibrium certification",
        "production_rules_changed": False, "model_called": False, "gpu_used": False,
    }
    with (HERE / "results.json").open("x") as f:
        json.dump(pack(results), f, ensure_ascii=False, indent=2)
        f.write("\n")
    snapshot = {
        "schema": 1, "diagnostic_version": VERSION,
        "active_training_version": "terminal-node-regret-grpo-readable-v8",
        "status": "completed-cpu-exact-enumeration-only",
        "actual_argv": sys.argv, "resolved_config": CONFIG,
        "source_manifest": {str(p.relative_to(ROOT)): digest(p) for p in (Path(__file__).resolve(), OLD)},
        "data_identity": "synthetic full supports and exact priors specified in resolved_config; no external corpus/selection/D",
        "model_identity": "not applicable; no model", "sampling_reward_contract": "exhaustive exact expectation; no Monte Carlo, GRPO, training reward or advantage",
        "runtime": {"python_executable": sys.executable, "python_version": platform.python_version(), "platform": platform.platform()},
        "results_sha256": digest(HERE / "results.json"),
    }
    with (HERE / "pipeline_snapshot.json").open("x") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(pack({"original_contract_early": free_query,
        "fixed": {k: fixed[k]["value"] for k in ("early", "late", "never")},
        "adaptive": {k: adaptive[k]["value"] for k in ("early", "late", "never")},
        "policy_counts": adaptive["policy_counts"], "status": results["status"]}), indent=2))


if __name__ == "__main__":
    main()
