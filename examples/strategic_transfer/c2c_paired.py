"""Prepare and run a matched focal-agent evaluation in Cooperate to Compete.

The upstream C2C batch schedule shuffles all four models.  This runner builds an
explicit schedule where only model slot zero changes between conditions, and
selects shuffle seeds so the focal agent's commander and secret-objective type
are balanced.  Using the same plan for both conditions guarantees matched board,
seat, objective, and counterparty assignments.
"""

from __future__ import annotations

import argparse
import importlib
import json
import multiprocessing as mp
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


C2C_COMMIT = "2f7eb4a163d21e139a3ea8b9f7d625b470594f00"
COMMANDERS = ("Commander Red", "Commander Blue", "Commander Green", "Commander Yellow")
OBJECTIVES = ("northwest_southeast", "southwest_northeast")
FOCAL_SLOT = "__FOCAL__"
PROMISING_PAIRED_DIFFERENCE = 0.06
PROMISING_NET_PAIRED_WINS = 3
OPERATIONAL_RATE_BALANCE_TOLERANCE = 0.05


@dataclass(frozen=True)
class PairSpec:
    pair_id: int
    board_seed: int
    shuffle_seed: int
    focal_seat: int
    focal_objective: str


def focal_assignment(board_seed: int, shuffle_seed: int) -> tuple[int, str]:
    """Return the commander index and objective assigned to model-list slot 0.

    C2C first shuffles models onto named commanders with ``shuffle_seed``.  Its
    ``Game`` constructor then shuffles the agent list with ``board_seed`` before
    objectives are dealt.  Both permutations are needed to predict the focal
    commander's objective.
    """
    indexed_models = list(range(4))
    random.Random(shuffle_seed).shuffle(indexed_models)
    focal_seat = indexed_models.index(0)

    participant_order = list(range(4))
    random.Random(board_seed).shuffle(participant_order)
    focal_deal_position = participant_order.index(focal_seat)

    objectives = [OBJECTIVES[0], OBJECTIVES[0], OBJECTIVES[1], OBJECTIVES[1]]
    random.Random(shuffle_seed + 99999).shuffle(objectives)
    assigned = [objectives.pop() for _ in range(4)]
    return focal_seat, assigned[focal_deal_position]


def build_plan(num_pairs: int, seed_base: int, num_boards: int) -> list[PairSpec]:
    """Create a deterministic plan balanced over seat and objective type."""
    if num_pairs < 1:
        raise ValueError("num_pairs must be positive")
    if num_boards < 1:
        raise ValueError("num_boards must be positive")

    plan: list[PairSpec] = []
    candidate = seed_base + 50000
    for pair_idx in range(num_pairs):
        board_seed = seed_base + (pair_idx % num_boards)
        target_seat = pair_idx % 4
        target_objective = OBJECTIVES[(pair_idx // 4) % 2]
        while True:
            seat, objective = focal_assignment(board_seed, candidate)
            if seat == target_seat and objective == target_objective:
                break
            candidate += 1
        plan.append(
            PairSpec(
                pair_id=pair_idx + 1,
                board_seed=board_seed,
                shuffle_seed=candidate,
                focal_seat=seat,
                focal_objective=objective,
            )
        )
        candidate += 1
    return plan


def write_plan(
    path: Path,
    plan: Sequence[PairSpec],
    counterparties: Sequence[str],
    seed_base: int,
) -> None:
    if len(counterparties) != 3:
        raise ValueError("exactly three counterparty models are required")
    payload = {
        "schema_version": 1,
        "c2c_commit": C2C_COMMIT,
        "seed_base": seed_base,
        "focal_slot": 0,
        "model_slots": [FOCAL_SLOT, *counterparties],
        "pairs": [asdict(item) for item in plan],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"unsupported plan schema in {path}")
    slots = payload.get("model_slots")
    if not isinstance(slots, list) or len(slots) != 4 or slots[0] != FOCAL_SLOT:
        raise ValueError("plan must contain one focal slot followed by three counterparties")
    return payload


def condition_worker_configs(
    plan: dict[str, Any],
    focal_model: str,
    output_dir: Path,
    max_turns: int,
) -> list[dict[str, Any]]:
    model_assignment = [focal_model, *plan["model_slots"][1:]]
    configs: list[dict[str, Any]] = []
    for item in plan["pairs"]:
        # Keep C2C's native game_ prefix so its released analysis pipeline
        # discovers these directories without a conversion or custom loader.
        game_id = f"game_{int(item['pair_id']):03d}"
        configs.append(
            {
                "game_id": game_id,
                "game_dir": str(output_dir / game_id),
                "board_seed": int(item["board_seed"]),
                "shuffle_seed": int(item["shuffle_seed"]),
                "model_assignment": model_assignment,
                "max_turns": max_turns,
                "llm_max_retries": 6,
                "llm_backoff_base_s": 2.0,
                "llm_backoff_max_s": 90.0,
                "llm_jitter_s": 0.5,
                "comparison_target_index": int(item["focal_seat"]),
                "resume": False,
                "start_step": 0,
            }
        )
    return configs


def _import_c2c_worker(c2c_dir: Path):
    if not (c2c_dir / "c2c" / "experiments" / "run_batch.py").is_file():
        raise FileNotFoundError(f"C2C not found at {c2c_dir}; run examples/strategic_transfer/setup_c2c.sh")
    sys.path.insert(0, str(c2c_dir))
    module = importlib.import_module("c2c.experiments.run_batch")
    return module._run_game_worker


def _latest_state(game_dir: Path) -> dict[str, Any] | None:
    state_files = list((game_dir / "game_states").glob("*/game_state.json"))
    if not state_files:
        return None

    def state_key(path: Path) -> tuple[int, int, int]:
        name = path.parent.name
        if name == "turn_0_init":
            return (0, -1, 0)
        parts = name.split("_")
        numbers = [int(p) for p in parts if p.isdigit()]
        return (numbers[0] if numbers else 0, numbers[1] if len(numbers) > 1 else 99, len(numbers))

    latest = max(state_files, key=state_key)
    return json.loads(latest.read_text(encoding="utf-8"))


def summarize_condition(condition_dir: Path) -> dict[str, Any]:
    manifest_path = condition_dir / "condition_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    focal_model = manifest["focal_model"]
    max_turns = int(manifest["max_turns"])
    rows = []
    for game in manifest["games"]:
        game_dir = condition_dir / game["game_id"]
        state = _latest_state(game_dir)
        error_path = game_dir / "error.json"
        completed_turns = len(list((game_dir / "game_states").glob("turn_*_player_*/game_state.json")))
        focal_commander = COMMANDERS[int(game["focal_seat"])]
        error = json.loads(error_path.read_text()) if error_path.exists() else None
        evaluated = bool(state and (state.get("game_over") or completed_turns >= max_turns * 4) and error is None)
        rows.append(
            {
                "pair_id": game["pair_id"],
                "focal_commander": focal_commander,
                "winner": state.get("winner") if state else None,
                "focal_win": bool(state and state.get("winner") == focal_commander),
                "game_over": bool(state and state.get("game_over")),
                "evaluated": evaluated,
                "error": error,
            }
        )
    completed = [row for row in rows if row["evaluated"]]
    wins = sum(row["focal_win"] for row in completed)
    errors = sum(row["error"] is not None for row in rows)
    return {
        "condition": manifest["condition"],
        "focal_model": focal_model,
        "games_planned": len(rows),
        "games_completed": len(completed),
        "completion_rate": len(completed) / len(rows) if rows else None,
        "errors": errors,
        "error_rate": errors / len(rows) if rows else None,
        "focal_objective_completions": wins,
        "focal_objective_completion_rate": wins / len(completed) if completed else None,
        "rows": rows,
    }


def compare_conditions(base_dir: Path, treatment_dir: Path) -> dict[str, Any]:
    base = summarize_condition(base_dir)
    treatment = summarize_condition(treatment_dir)
    base_rows = {row["pair_id"]: row for row in base.pop("rows")}
    treatment_rows = {row["pair_id"]: row for row in treatment.pop("rows")}
    shared = sorted(set(base_rows) & set(treatment_rows))
    paired = [
        {
            "pair_id": pair_id,
            "base_completion": base_rows[pair_id]["focal_win"],
            "treatment_completion": treatment_rows[pair_id]["focal_win"],
        }
        for pair_id in shared
        if base_rows[pair_id]["evaluated"] and treatment_rows[pair_id]["evaluated"]
    ]
    gains = sum(row["treatment_completion"] and not row["base_completion"] for row in paired)
    losses = sum(row["base_completion"] and not row["treatment_completion"] for row in paired)
    paired_difference = (
        sum(row["treatment_completion"] - row["base_completion"] for row in paired) / len(paired)
        if paired
        else None
    )
    net_paired_wins = gains - losses
    completion_rate_difference = treatment["completion_rate"] - base["completion_rate"]
    error_rate_difference = treatment["error_rate"] - base["error_rate"]
    operational_rates_balanced = (
        abs(completion_rate_difference) <= OPERATIONAL_RATE_BALANCE_TOLERANCE
        and abs(error_rate_difference) <= OPERATIONAL_RATE_BALANCE_TOLERANCE
    )
    effect_promising = bool(
        paired_difference is not None
        and (
            paired_difference >= PROMISING_PAIRED_DIFFERENCE
            or net_paired_wins >= PROMISING_NET_PAIRED_WINS
        )
    )
    return {
        "primary_outcome": "focal_secret_objective_completion_by_50_round_horizon",
        "base": base,
        "treatment": treatment,
        "completed_pairs": len(paired),
        "discordant_treatment_completions": gains,
        "discordant_base_completions": losses,
        "net_paired_wins": net_paired_wins,
        "paired_completion_rate_difference": paired_difference,
        "completion_rate_difference": completion_rate_difference,
        "error_rate_difference": error_rate_difference,
        "operational_rates_balanced": operational_rates_balanced,
        "screening_rule": {
            "paired_difference_threshold": PROMISING_PAIRED_DIFFERENCE,
            "net_paired_wins_threshold": PROMISING_NET_PAIRED_WINS,
            "operational_rate_balance_tolerance": OPERATIONAL_RATE_BALANCE_TOLERANCE,
            "effect_promising": effect_promising,
            "promising_for_expansion": effect_promising and operational_rates_balanced,
        },
        "paired_rows": paired,
    }


def _write_condition_manifest(
    output_dir: Path,
    condition: str,
    focal_model: str,
    plan_path: Path,
    configs: Sequence[dict[str, Any]],
    max_turns: int,
) -> None:
    plan = load_plan(plan_path)
    games = []
    for pair, cfg in zip(plan["pairs"], configs):
        games.append(
            {
                "game_id": cfg["game_id"],
                "pair_id": pair["pair_id"],
                "board_seed": pair["board_seed"],
                "shuffle_seed": pair["shuffle_seed"],
                "focal_seat": pair["focal_seat"],
                "focal_objective": pair["focal_objective"],
                "model_assignment": cfg["model_assignment"],
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "condition_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "condition": condition,
                "focal_model": focal_model,
                "plan": str(plan_path),
                "c2c_commit": plan["c2c_commit"],
                "max_turns": max_turns,
                "games": games,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    output_dir = Path(args.output_dir).resolve() / args.condition
    configs = condition_worker_configs(plan, args.focal_model, output_dir, args.max_turns)
    _write_condition_manifest(output_dir, args.condition, args.focal_model, plan_path, configs, args.max_turns)
    if args.dry_run:
        print(json.dumps({"condition_dir": str(output_dir), "games": len(configs)}, indent=2))
        return

    worker = _import_c2c_worker(Path(args.c2c_dir).resolve())
    if args.num_workers == 1:
        for cfg in configs:
            worker(cfg)
    else:
        with mp.get_context("spawn").Pool(args.num_workers) as pool:
            pool.map(worker, configs)


def _prepare(args: argparse.Namespace) -> None:
    plan = build_plan(args.num_pairs, args.seed_base, args.num_boards)
    write_plan(Path(args.output), plan, args.counterparty_model, args.seed_base)
    counts = Counter((item.focal_seat, item.focal_objective) for item in plan)
    print(
        json.dumps(
            {"output": args.output, "pairs": len(plan), "strata": {str(k): v for k, v in counts.items()}}, indent=2
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="write a paired, stratified seed plan")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--num-pairs", type=int, default=50)
    prepare.add_argument("--num-boards", type=int, default=50)
    prepare.add_argument("--seed-base", type=int, default=26042026)
    prepare.add_argument("--counterparty-model", action="append", required=True)
    prepare.set_defaults(func=_prepare)

    run = sub.add_parser("run-condition", help="run one focal model on a prepared plan")
    run.add_argument("--plan", required=True)
    run.add_argument("--condition", choices=("base", "treatment"), required=True)
    run.add_argument("--focal-model", required=True)
    run.add_argument("--output-dir", default="runs/c2c_marshal_poc")
    run.add_argument("--c2c-dir", default="third_party/cooperate-to-compete")
    run.add_argument("--max-turns", type=int, default=50)
    run.add_argument("--num-workers", type=int, default=1)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=_run)

    summarize = sub.add_parser("summarize", help="score completed paired conditions")
    summarize.add_argument("--base-dir", required=True)
    summarize.add_argument("--treatment-dir", required=True)
    summarize.add_argument("--output")

    def do_summarize(args: argparse.Namespace) -> None:
        result = compare_conditions(Path(args.base_dir), Path(args.treatment_dir))
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        print(rendered, end="")

    summarize.set_defaults(func=do_summarize)
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "prepare" and len(args.counterparty_model) != 3:
        raise SystemExit("--counterparty-model must be supplied exactly three times")
    args.func(args)


if __name__ == "__main__":
    main()
