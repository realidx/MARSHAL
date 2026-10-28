"""Generate fresh, bounded two-player BENAC roots before C/S screening.

The seed range is fixed in advance. Every attempted seed, including oracle
failures, appears in the source manifest or exclusion file; no regret or
information-value label is used to decide which roots enter the source.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from training.b_sft.build_bp_pilot import raw_fixture, topology
from training.b_sft.preference_contract import profile
from training.b_sft.prepare_no_catalogue_probe import expand_support, view
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.social_mixed.short_interaction import ShortInteraction


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXISTING = ROOT / "examples/social_mixed/interaction_bank_v1/tasks.jsonl"


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(stable(value).encode()).hexdigest()


def signature_input(inp):
    """Meaningful initial observation, independent of old prompt metadata."""
    keys = (
        "game", "player", "public_preferences", "own_preferences",
        "background_prior", "current_state", "imposed_setup",
        "voluntary_history", "private_results", "pending_offer",
    )
    return digest({key: inp.get(key) for key in keys})


def old_input_hashes():
    rows = (json.loads(line) for line in EXISTING.read_text().splitlines() if line)
    return {signature_input(row["input"]) for row in rows
            if row.get("paired_view") == "O" and row["input"]["game"]["n_players"] == 2}


def generate(seed: int, *, seconds: float, max_nodes: int):
    raw, _ = raw_fixture(seed)
    if raw["game"]["n_players"] != 2:
        raise ValueError("not_two_player")
    # Start after a preference-independent PASS. Two proposal turns remain for
    # ego, with possible offer responses counted as additional ego decisions.
    raw["game"]["round_robin"] = [1, 0, 0, 1]
    raw["background_prior"] = profile("balanced")
    setup = [dict(action="PASS")]
    raw, public, expansion = expand_support(raw)
    ego = raw["ego"]
    if ego != 0:
        raise ValueError("unexpected_ego")
    episode = PrivateEpisode(raw, setup, seconds=seconds,
                             max_nodes=max_nodes, max_sweeps=128)
    native = audit_native(episode.tree)
    own = raw["own_preferences"]
    inp = view(episode, public, ego, own, [], setup, [])
    choices = episode.choices(own)
    inp.update(background_prior=raw["background_prior"],
               legal_actions=choices["actions"],
               belief_source="history",
               supplied_belief=dict(known_preferences=[], unresolved_preferences=[],
                                    support="Infer from visible history."))
    sig = signature_input(inp)
    task = dict(
        id=sig[:20] + "-O", task="P", skill="history_action", paired_view="O",
        split="development", family=topology(raw), name_variant=0,
        training_mode="short_interaction", training_ready=False,
        source="fresh-seeded-native-2p-v1", generation_seed=seed,
        input_sha256=sig, input=inp,
        teacher=dict(policy_sha256=episode.tree.certificate["policy_sha256"],
                     action_values=choices["values"], native=native),
    )
    env = ShortInteraction(task, max_decisions=3, seconds=seconds,
                           max_nodes=max_nodes, max_sweeps=128)
    task["max_ego_decisions"] = env.max_decisions
    return task, dict(seed=seed, id=task["id"], input_sha256=sig,
                      family=task["family"], tree_nodes=len(env.tree.entries),
                      worlds=len(env.tree.worlds), max_ego_decisions=env.max_decisions,
                      expanded_worlds=expansion["new_worlds"],
                      policy_sha256=env.tree.certificate["policy_sha256"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-start", type=int, default=501)
    parser.add_argument("--seed-count", type=int, default=18)
    parser.add_argument("--max-roots", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--max-nodes", type=int, default=30000)
    parser.add_argument("--out", type=Path, default=HERE / "pilot_data_fresh")
    args = parser.parse_args(argv)
    if args.seed_start < 501 or args.seed_count <= 0 or args.max_roots <= 0:
        parser.error("use a positive bounded seed count, max roots, and seeds above the original 0–499 BP range")
    known = old_input_hashes()
    seen = set()
    tasks = []
    accepted = []
    excluded = []
    for seed in range(args.seed_start, args.seed_start + args.seed_count):
        if len(tasks) >= args.max_roots:
            break
        try:
            task, record = generate(seed, seconds=args.seconds, max_nodes=args.max_nodes)
            sig = task["input_sha256"]
            if sig in known:
                raise ValueError("duplicate_existing_observation")
            if sig in seen:
                raise ValueError("duplicate_within_fresh_batch")
            seen.add(sig)
            tasks.append(task)
            accepted.append(record)
            print(f"{seed} ACCEPTED {task['id']} nodes={record['tree_nodes']}", flush=True)
        except Exception as exc:
            excluded.append(dict(seed=seed, error_type=type(exc).__name__, reason=str(exc)))
            print(f"{seed} EXCLUDED {type(exc).__name__}: {exc}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out / "source_tasks.jsonl"
    source.write_text("".join(stable(task) + "\n" for task in tasks))
    (args.out / "source_exclusions.jsonl").write_text(
        "".join(stable(row) + "\n" for row in excluded))
    manifest = dict(
        version="fresh-seeded-native-2p-v1", generator="build_bp_pilot.raw_fixture",
        generation_design=dict(
            seed_rule="raw_fixture(seed), retain n_players=2 only",
            fixed_round_robin=[1, 0, 0, 1],
            imposed_setup=[dict(action="PASS")],
            public_prior="balanced (want/neutral/avoid weights 1/1/1)",
            support="expand_support restores the stated public generator support",
            game_rules="native two-player private-investigation BENAC; MENU disabled by raw_fixture",
        ),
        source=str(source.resolve().relative_to(ROOT) if source.resolve().is_relative_to(ROOT) else source.resolve()),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        seed_start=args.seed_start, seed_count=args.seed_count,
        max_roots=args.max_roots, stop_condition="first max_roots admissible roots or exhausted seed range",
        attempted=len(tasks) + len(excluded),
        accepted=len(tasks), excluded=len(excluded),
        exclusion_reasons=dict(Counter(row["reason"] for row in excluded)),
        existing_bank=EXISTING.relative_to(ROOT).as_posix(),
        existing_bank_sha256=hashlib.sha256(EXISTING.read_bytes()).hexdigest(),
        accepted_roots=accepted,
        criteria="n=2, public generator support, finite selected-policy oracle, two or three ego decisions, unique entrance observation; no C/S or model-label filtering",
        limitations="Development seed sample; native generator uses binary goals and the selected-policy reference, and failed oracle seeds are reported rather than scored.",
    )
    (args.out / "source_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: manifest[key] for key in ("source", "attempted", "accepted", "excluded", "source_sha256")}, sort_keys=True))
    return manifest


if __name__ == "__main__":
    main()
