"""Enumerate exact Tic-Tac-Toe decisions and score real model samples.

Build writes oracle labels separately from model requests. Score accepts raw
responses produced for those requests; it never substitutes a proxy policy for
the model whose decision distribution is being measured.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random


ROOT = Path(os.environ.get("MARSHAL_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


game = load_module("pilot_tictactoe_minimax", ROOT / "roll/agentic/env/tictactoe/minimax.py")
protocol = load_module("pilot_tictactoe_protocol", ROOT / "roll/agentic/tictactoe_protocol.py")

SYMBOL = {0: ".", 1: "X", -1: "O"}
MARK = {0: 1, 1: -1}
TOL = 1e-10


def board_text(board):
    return "".join(SYMBOL[cell] for cell in board)


def parse_board(text):
    if len(text) != 9 or any(ch not in ".XO" for ch in text):
        raise ValueError(f"Invalid board string: {text!r}")
    return tuple({".": 0, "X": 1, "O": -1}[ch] for ch in text)


def transformations(board):
    """All eight board symmetries, used only for sampling and deduplication."""
    for mirror in (False, True):
        for turns in range(4):
            transformed = [0] * 9
            for index, value in enumerate(board):
                row, col = divmod(index, 3)
                if mirror:
                    col = 2 - col
                for _ in range(turns):
                    row, col = col, 2 - row
                transformed[row * 3 + col] = value
            yield board_text(transformed)


def canonical_board(board):
    return min(transformations(board))


def opponent_immediate_wins(board, player):
    opponent = 1 - player
    mark = MARK[opponent]
    wins = []
    for action in game.legal_actions(board):
        candidate = list(board)
        candidate[action] = mark
        if game.winner(tuple(candidate)) == opponent:
            wins.append(action)
    return wins


def category(row):
    if row["decision_spread"] <= TOL:
        return "flat"
    if row["immediate_winning_actions"]:
        return "immediate_win"
    if row["opponent_immediate_winning_cells"]:
        return "immediate_threat"
    return "non_immediate_split"


def oracle_row(board, evaluator, outcome_evaluator):
    player = game.current_player(board)
    q = evaluator.action_values(board, player)
    q_outcome = outcome_evaluator.action_values(board, player)
    best = max(q.values())
    outcome_spread = max(q_outcome.values()) - min(q_outcome.values())
    immediate_wins = [a for a in q if game.winner(game.apply_action(board, a)) == player]
    actions = [
        dict(index=a, move=protocol.action_to_string(player, a), q=q[a],
             regret=max(0.0, best - q[a]), outcome_q=q_outcome[a],
             immediately_terminal=game.is_terminal(game.apply_action(board, a)))
        for a in q
    ]
    row = dict(board=board_text(board), canonical_board=canonical_board(board),
               player="X" if player == 0 else "O", ply=9 - board.count(0),
               value=best, actions=actions, optimal_actions=[a["index"] for a in actions if a["regret"] <= TOL],
               decision_spread=best - min(q.values()), outcome_spread=outcome_spread,
               uniform_action_expected_regret=sum(a["regret"] for a in actions) / len(actions),
               immediate_winning_actions=immediate_wins,
               opponent_immediate_winning_cells=opponent_immediate_wins(board, player))
    row["category"] = category(row)
    return row


def choose_panel(canonical_rows, per_category, seed):
    rng = random.Random(seed)
    selected = []
    for name in ("immediate_win", "immediate_threat", "non_immediate_split", "flat"):
        buckets = defaultdict(list)
        for row in canonical_rows:
            if row["category"] == name:
                buckets[(row["ply"], row["player"])].append(row)
        for bucket in buckets.values():
            rng.shuffle(bucket)
        keys = sorted(buckets)
        chosen = 0
        while chosen < per_category and any(buckets.values()):
            for key in keys:
                if buckets[key] and chosen < per_category:
                    selected.append(buckets[key].pop())
                    chosen += 1
    return sorted(selected, key=lambda row: row["board"])


def request_for(row):
    board = row["board"]
    rows = [f"{r} {' '.join(board[3*r:3*r+3])}" for r in range(3)]
    legal_moves = ", ".join(a["move"] for a in row["actions"])
    turn = (f"\n\nYou are player {row['player']}.\n\n"
            f"Board:\n  0 1 2\n{'\n'.join(rows)}\n\n"
            f"Legal moves:\n{legal_moves}")
    instruction = (
        "Choose exactly one legal move that maximizes your final game outcome:\n"
        "win is better than draw, and draw is better than loss.\n\n"
        "Analyze the strategy as concisely as possible and choose exactly one legal action.\n"
        "Do not enumerate every legal move or the complete game tree.\n\n"
        "Output exactly:\n"
        "<reason>one brief reason</reason>\n"
        "<answer><SYMBOL(row,column)></answer>\n\n"
        "Do not output anything else."
    )
    return dict(board=board, player=row["player"],
                messages=[dict(role="system", content="You are playing Tic-Tac-Toe."),
                          dict(role="user", content=instruction + turn)],
                legal_moves=[a["move"] for a in row["actions"]])


def write_jsonl(path, rows):
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path):
    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}") from exc


def build(args):
    if args.output.exists():
        raise ValueError(f"Output directory already exists: {args.output}")
    evaluator = game.ExactTicTacToeEvaluator(args.discount)
    outcome_evaluator = game.ExactTicTacToeEvaluator(1.0)
    boards = list(evaluator.reachable_boards())
    rows = [oracle_row(board, evaluator, outcome_evaluator) for board in boards if not game.is_terminal(board)]
    rows.sort(key=lambda row: row["board"])
    canonical_rows = [row for row in rows if row["board"] == row["canonical_board"]]
    panel = choose_panel(canonical_rows, args.per_category, args.seed)
    args.output.mkdir(parents=True)
    source_hashes = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in ("roll/agentic/env/tictactoe/minimax.py",
                         "roll/agentic/tictactoe_protocol.py",
                         "roll/agentic/env/tictactoe/env.py")
    }
    (args.output / "source_hashes.json").write_text(json.dumps(source_hashes, indent=2, sort_keys=True) + "\n")
    write_jsonl(args.output / "oracle_states.jsonl", rows)
    write_jsonl(args.output / "panel_oracle.jsonl", panel)
    write_jsonl(args.output / "panel_requests.jsonl", (request_for(row) for row in panel))
    summary = dict(oracle="ExactTicTacToeEvaluator", discount=args.discount,
                   outcome_discount=1.0, seed=args.seed, per_category=args.per_category,
                   reachable_boards=len(boards), nonterminal_decisions=len(rows),
                   canonical_decisions=len(canonical_rows), panel_decisions=len(panel),
                   categories_all=dict(Counter(row["category"] for row in rows)),
                   categories_canonical=dict(Counter(row["category"] for row in canonical_rows)),
                   categories_panel=dict(Counter(row["category"] for row in panel)),
                   positive_spread=sum(row["decision_spread"] > TOL for row in rows),
                   positive_outcome_spread=sum(row["outcome_spread"] > TOL for row in rows),
                   depth_only_spread=sum(row["decision_spread"] > TOL and row["outcome_spread"] <= TOL for row in rows),
                   source_hashes=source_hashes,
                   model_scored=False,
                   interpretation="Oracle consequences and structural tags only; no current-model difficulty or ranking yet.")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


def score(args):
    if args.output.exists():
        raise ValueError(f"Output directory already exists: {args.output}")
    panel = {row["board"]: row for row in read_jsonl(args.oracle_dir / "panel_oracle.jsonl")}
    samples = defaultdict(list)
    for record in read_jsonl(args.samples):
        board = record.get("board")
        if board not in panel:
            raise ValueError(f"Sample board is not in fixed panel: {board!r}")
        responses = record.get("responses", [record.get("response")])
        if not isinstance(responses, list) or any(not isinstance(x, str) for x in responses):
            raise ValueError(f"Responses must be strings for board {board!r}")
        samples[board].extend((response, record.get("finish_reason")) for response in responses)
    ranked = []
    for board, row in panel.items():
        if board not in samples:
            continue
        player = 0 if row["player"] == "X" else 1
        legal = {a["index"]: protocol.action_to_string(player, a["index"]) for a in row["actions"]}
        by_move = {a["move"]: a for a in row["actions"]}
        counts = Counter(None if finish_reason == "length" else protocol.recover_action(response, legal)
                         for response, finish_reason in samples[board])
        valid = sum(n for move, n in counts.items() if move is not None)
        invalid = counts[None]
        truncated = sum(finish_reason == "length" for _, finish_reason in samples[board])
        if valid:
            expected_regret = sum(count * by_move[move]["regret"] for move, count in counts.items() if move is not None) / valid
            error_rate = sum(count for move, count in counts.items() if move is not None and by_move[move]["regret"] > TOL) / valid
        else:
            expected_regret = None
            error_rate = None
        ranked.append(dict(board=board, player=row["player"], ply=row["ply"],
                           category=row["category"], decision_spread=row["decision_spread"],
                           sample_count=len(samples[board]), valid_samples=valid, invalid_samples=invalid,
                           truncated_samples=truncated,
                           invalid_rate=invalid / len(samples[board]),
                           action_counts={move: counts[move] for move in legal.values()},
                           expected_oracle_regret_valid=expected_regret,
                           error_rate_valid=error_rate,
                           rank_eligible=valid >= args.min_valid_samples))
    ranked.sort(key=lambda row: (not row["rank_eligible"],
                                 -(row["expected_oracle_regret_valid"] or 0), row["board"]))
    eligible = [row for row in ranked if row["rank_eligible"]]
    args.output.mkdir(parents=True)
    write_jsonl(args.output / "ranked.jsonl", ranked)
    summary = dict(model_id=args.model_id, temperature=args.temperature,
                   min_valid_samples=args.min_valid_samples,
                   panel_decisions=len(panel), sampled_decisions=len(ranked),
                   ranked_decisions=len(eligible),
                   total_samples=sum(row["sample_count"] for row in ranked),
                   invalid_samples=sum(row["invalid_samples"] for row in ranked),
                   truncated_samples=sum(row["truncated_samples"] for row in ranked),
                   ranked_categories=dict(Counter(row["category"] for row in eligible)),
                   top_20_categories=dict(Counter(row["category"] for row in eligible[:20])),
                   top_20=[dict(board=row["board"], category=row["category"],
                                expected_oracle_regret_valid=row["expected_oracle_regret_valid"],
                                error_rate_valid=row["error_rate_valid"])
                           for row in eligible[:20]],
                   interpretation="Model-relative regret among valid parsed legal actions; invalid outputs reported separately.")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="Enumerate exact decisions and freeze a probe panel")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--discount", type=float, default=0.9)
    build_parser.add_argument("--per-category", type=int, default=32)
    build_parser.add_argument("--seed", type=int, default=42)
    build_parser.set_defaults(func=build)
    score_parser = commands.add_parser("score", help="Rank the panel using raw model responses")
    score_parser.add_argument("--oracle-dir", type=Path, required=True)
    score_parser.add_argument("--samples", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    score_parser.add_argument("--model-id", required=True)
    score_parser.add_argument("--temperature", type=float, required=True)
    score_parser.add_argument("--min-valid-samples", type=int, default=8)
    score_parser.set_defaults(func=score)
    args = parser.parse_args()
    if args.command == "build" and args.per_category <= 0:
        parser.error("--per-category must be positive")
    if args.command == "score" and args.min_valid_samples <= 0:
        parser.error("--min-valid-samples must be positive")
    args.func(args)


if __name__ == "__main__":
    main()
