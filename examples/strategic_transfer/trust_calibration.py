"""Persistent-source trust-calibration diagnostic.

Each episode has twelve decisions in three surface domains.  Four named sources
persist across rounds: a reliable aligned source, a noisy aligned source, an
adversarial source, and a source that switches from reliable to adversarial at
the midpoint.  The hidden option and reports are generated before any model is
called, so base and treatment checkpoints can be evaluated on identical JSONL
episodes.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


SOURCE_NAMES = ("Atlas", "Beacon", "Cipher", "Delta")
OPTION_IDS = ("A", "B", "C", "D")
DOMAINS = ("routing", "procurement", "software_allocation")


@dataclass(frozen=True)
class Report:
    source: str
    option: str
    correct: bool
    behavior: str


@dataclass(frozen=True)
class Round:
    index: int
    domain: str
    scenario: str
    options: dict[str, str]
    correct_option: str
    reports: tuple[Report, ...]


@dataclass(frozen=True)
class Episode:
    episode_id: int
    seed: int
    switch_round: int
    rounds: tuple[Round, ...]


@dataclass(frozen=True)
class Decision:
    choice: str
    reliability: dict[str, float]
    raw_response: str = ""


class Policy(Protocol):
    def decide(self, episode: Episode, round_: Round, history: Sequence[dict[str, Any]]) -> Decision: ...


def _scenario(domain: str, episode_id: int, round_index: int, options: dict[str, str]) -> str:
    if domain == "routing":
        return (
            f"Choose the only open route for shipment R{episode_id}-{round_index}. "
            f"Candidate corridors: {', '.join(f'{k}={v}' for k, v in options.items())}."
        )
    if domain == "procurement":
        return (
            f"Choose the only supplier meeting all constraints for order P{episode_id}-{round_index}. "
            f"Candidates: {', '.join(f'{k}={v}' for k, v in options.items())}."
        )
    return (
        f"Choose the only compatible compute pool for deployment S{episode_id}-{round_index}. "
        f"Candidates: {', '.join(f'{k}={v}' for k, v in options.items())}."
    )


def _option_labels(domain: str, episode_id: int, round_index: int) -> dict[str, str]:
    prefixes = {
        "routing": ("North", "East", "South", "West"),
        "procurement": ("Aster", "Birch", "Cobalt", "Dune"),
        "software_allocation": ("Pool-Ibis", "Pool-Lynx", "Pool-Oryx", "Pool-Wren"),
    }[domain]
    return {key: f"{value}-{(episode_id * 7 + round_index) % 19}" for key, value in zip(OPTION_IDS, prefixes)}


def _wrong_option(rng: random.Random, correct: str) -> str:
    return rng.choice([option for option in OPTION_IDS if option != correct])


def _source_report(
    rng: random.Random,
    source: str,
    correct: str,
    accuracy: float,
    behavior: str,
) -> Report:
    is_correct = rng.random() < accuracy
    option = correct if is_correct else _wrong_option(rng, correct)
    return Report(source=source, option=option, correct=is_correct, behavior=behavior)


def generate_episode(seed: int, episode_id: int, num_rounds: int = 12, switch: bool = True) -> Episode:
    if num_rounds < 4:
        raise ValueError("num_rounds must be at least four")
    rng = random.Random(seed)
    switch_round = num_rounds // 2 + 1
    rounds: list[Round] = []
    for round_index in range(1, num_rounds + 1):
        domain = DOMAINS[(round_index - 1) % len(DOMAINS)]
        correct = rng.choice(OPTION_IDS)
        options = _option_labels(domain, episode_id, round_index)
        delta_switched = switch and round_index >= switch_round
        reports = (
            _source_report(rng, "Atlas", correct, 0.90, "aligned_reliable"),
            _source_report(rng, "Beacon", correct, 0.55, "aligned_noisy"),
            _source_report(rng, "Cipher", correct, 0.10, "adversarial"),
            _source_report(
                rng,
                "Delta",
                correct,
                0.10 if delta_switched else 0.85,
                "adversarial" if delta_switched else "aligned_reliable",
            ),
        )
        rounds.append(
            Round(
                index=round_index,
                domain=domain,
                scenario=_scenario(domain, episode_id, round_index, options),
                options=options,
                correct_option=correct,
                reports=reports,
            )
        )
    return Episode(episode_id=episode_id, seed=seed, switch_round=switch_round, rounds=tuple(rounds))


def generate_suite(num_episodes: int, seed_base: int, num_rounds: int = 12, switch: bool = True) -> list[Episode]:
    return [
        generate_episode(seed_base + episode_id - 1, episode_id, num_rounds=num_rounds, switch=switch)
        for episode_id in range(1, num_episodes + 1)
    ]


def save_suite(path: Path, episodes: Sequence[Episode]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            handle.write(json.dumps(asdict(episode)) + "\n")


def load_suite(path: Path) -> list[Episode]:
    episodes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        rounds = []
        for round_item in item["rounds"]:
            reports = tuple(Report(**report) for report in round_item["reports"])
            rounds.append(Round(**{**round_item, "reports": reports}))
        episodes.append(Episode(**{**item, "rounds": tuple(rounds)}))
    return episodes


def _empirical_reliability(history: Sequence[dict[str, Any]]) -> dict[str, float]:
    correct = {source: 1.0 for source in SOURCE_NAMES}
    total = {source: 2.0 for source in SOURCE_NAMES}
    for row in history:
        truth = row["correct_option"]
        for report in row["reports"]:
            total[report["source"]] += 1
            correct[report["source"]] += float(report["option"] == truth)
    return {source: correct[source] / total[source] for source in SOURCE_NAMES}


class ScriptedPolicy:
    """Dependency-free smoke policy; it is not an experimental baseline."""

    def __init__(self, mode: str, seed: int = 0):
        if mode not in {"oracle", "majority", "random"}:
            raise ValueError(f"unknown scripted mode {mode}")
        self.mode = mode
        self.rng = random.Random(seed)

    def decide(self, episode: Episode, round_: Round, history: Sequence[dict[str, Any]]) -> Decision:
        reliability = _empirical_reliability(history)
        if self.mode == "oracle":
            choice = round_.correct_option
        elif self.mode == "random":
            choice = self.rng.choice(OPTION_IDS)
        else:
            votes = {option: 0 for option in OPTION_IDS}
            for report in round_.reports:
                votes[report.option] += 1
            choice = max(OPTION_IDS, key=lambda option: (votes[option], -OPTION_IDS.index(option)))
        return Decision(choice=choice, reliability=reliability, raw_response=self.mode)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"response does not contain a JSON object: {text[:200]}")
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value


class OpenAICompatiblePolicy:
    def __init__(
        self,
        api_base: str,
        model: str,
        api_key: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
        retries: int = 3,
    ):
        self.url = api_base.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries

    def decide(self, episode: Episode, round_: Round, history: Sequence[dict[str, Any]]) -> Decision:
        transcript = []
        for row in history:
            transcript.append(
                {
                    "round": row["round"],
                    "reports": {report["source"]: report["option"] for report in row["reports"]},
                    "your_choice": row["choice"],
                    "revealed_correct_option": row["correct_option"],
                }
            )
        reports = {report.source: report.option for report in round_.reports}
        prompt = {
            "task": round_.scenario,
            "options": round_.options,
            "persistent_source_reports": reports,
            "previous_rounds_with_feedback": transcript,
            "instructions": (
                "Choose one option using the reports and prior feedback. Source identities persist, but their "
                "reliability or incentives may change. Return only JSON with keys choice and reliability. "
                "choice must be A, B, C, or D. reliability must map Atlas, Beacon, Cipher, and Delta to your "
                "current probability from 0 to 1 that each source reports the correct option."
            ),
        }
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a decision-maker learning which persistent information sources to trust.",
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    response_body = json.loads(response.read().decode("utf-8"))
                raw = response_body["choices"][0]["message"]["content"]
                parsed = _extract_json(raw)
                choice = str(parsed["choice"]).upper()
                if choice not in OPTION_IDS:
                    raise ValueError(f"invalid choice {choice}")
                reliability = {source: float(parsed["reliability"][source]) for source in SOURCE_NAMES}
                if any(not 0 <= value <= 1 for value in reliability.values()):
                    raise ValueError("reliability values must lie in [0, 1]")
                return Decision(choice=choice, reliability=reliability, raw_response=raw)
            except (KeyError, TypeError, ValueError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"model call failed after {self.retries} attempts: {last_error}")


def run_episode(episode: Episode, policy: Policy) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for round_ in episode.rounds:
        decision = policy.decide(episode, round_, history)
        row = {
            "episode_id": episode.episode_id,
            "seed": episode.seed,
            "switch_round": episode.switch_round,
            "round": round_.index,
            "domain": round_.domain,
            "scenario": round_.scenario,
            "options": round_.options,
            "reports": [asdict(report) for report in round_.reports],
            "correct_option": round_.correct_option,
            "choice": decision.choice,
            "reliability": decision.reliability,
            "raw_response": decision.raw_response,
        }
        history.append(row)
    return history


def score_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot score an empty run")
    accuracy = sum(row["choice"] == row["correct_option"] for row in rows) / len(rows)
    brier_terms = []
    source_agreement: dict[str, list[float]] = {source: [] for source in SOURCE_NAMES}
    adversary_hits = 0
    episode_last: dict[int, dict[str, Any]] = {}
    for row in rows:
        reports = {report["source"]: report for report in row["reports"]}
        for source in SOURCE_NAMES:
            probability = float(row["reliability"][source])
            outcome = float(reports[source]["correct"])
            brier_terms.append((probability - outcome) ** 2)
            source_agreement[source].append(float(row["choice"] == reports[source]["option"]))
        true_accuracy = {
            source: 0.90 if source == "Atlas" else 0.55 if source == "Beacon" else 0.10 for source in SOURCE_NAMES
        }
        if row["round"] < row["switch_round"]:
            true_accuracy["Delta"] = 0.85
        predicted_worst = min(SOURCE_NAMES, key=lambda source: row["reliability"][source])
        true_worst = min(SOURCE_NAMES, key=true_accuracy.get)
        adversary_hits += predicted_worst == true_worst
        episode_last[row["episode_id"]] = row

    adaptation_delays = []
    recovery_values = []
    delta_reliance_changes = []
    for episode_id in sorted(episode_last):
        episode_rows = [row for row in rows if row["episode_id"] == episode_id]
        switch_round = episode_rows[0]["switch_round"]
        pre = [row for row in episode_rows if row["round"] < switch_round]
        post = [row for row in episode_rows if row["round"] >= switch_round]
        detected = next((row["round"] for row in post if row["reliability"]["Delta"] < 0.5), None)
        adaptation_delays.append((detected - switch_round) if detected is not None else None)
        early = post[:2]
        late = post[-2:]
        recovery_values.append(
            sum(row["choice"] == row["correct_option"] for row in late) / len(late)
            - sum(row["choice"] == row["correct_option"] for row in early) / len(early)
        )
        pre_agreement = sum(
            row["choice"] == next(r["option"] for r in row["reports"] if r["source"] == "Delta") for row in pre
        ) / len(pre)
        post_agreement = sum(
            row["choice"] == next(r["option"] for r in row["reports"] if r["source"] == "Delta") for row in post
        ) / len(post)
        delta_reliance_changes.append(post_agreement - pre_agreement)

    finite_delays = [delay for delay in adaptation_delays if delay is not None]
    return {
        "decisions": len(rows),
        "episodes": len(episode_last),
        "accuracy": accuracy,
        "decision_regret": 1.0 - accuracy,
        "fraction_oracle_gap_recovered": (accuracy - 0.25) / 0.75,
        "unreliable_source_identification_accuracy": adversary_hits / len(rows),
        "reliability_brier_score": sum(brier_terms) / len(brier_terms),
        "mean_rounds_to_detect_delta_switch": sum(finite_delays) / len(finite_delays) if finite_delays else None,
        "delta_switch_detection_rate": len(finite_delays) / len(adaptation_delays),
        "mean_post_switch_recovery": sum(recovery_values) / len(recovery_values),
        "mean_delta_reliance_change": sum(delta_reliance_changes) / len(delta_reliance_changes),
        "source_choice_agreement": {source: sum(values) / len(values) for source, values in source_agreement.items()},
    }


def save_rows(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--output", required=True)
    generate.add_argument("--num-episodes", type=int, default=50)
    generate.add_argument("--num-rounds", type=int, default=12)
    generate.add_argument("--seed-base", type=int, default=26042026)
    generate.add_argument("--no-switch", action="store_true")

    run = sub.add_parser("run")
    run.add_argument("--suite", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--scripted", choices=("oracle", "majority", "random"))
    run.add_argument("--api-base")
    run.add_argument("--api-key", default="EMPTY")
    run.add_argument("--model")
    run.add_argument("--temperature", type=float, default=0.2)

    score = sub.add_parser("score")
    score.add_argument("--input", required=True)
    score.add_argument("--output")
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        episodes = generate_suite(args.num_episodes, args.seed_base, args.num_rounds, not args.no_switch)
        save_suite(Path(args.output), episodes)
        print(json.dumps({"output": args.output, "episodes": len(episodes)}, indent=2))
        return
    if args.command == "run":
        if args.scripted:
            policy: Policy = ScriptedPolicy(args.scripted)
        else:
            if not args.api_base or not args.model:
                raise SystemExit("model runs require --api-base and --model (or use --scripted for a smoke run)")
            policy = OpenAICompatiblePolicy(args.api_base, args.model, args.api_key, args.temperature)
        rows = [row for episode in load_suite(Path(args.suite)) for row in run_episode(episode, policy)]
        save_rows(Path(args.output), rows)
        print(json.dumps(score_rows(rows), indent=2))
        return
    result = score_rows(load_rows(Path(args.input)))
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
