"""Generate, certify, deduplicate and split a B-only development corpus.

Game structure remains native. Every queried goal is independently varied
within each private background. Lawful counterfactual action branches supplement
natural observations; neither search failures nor policy changes become labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from benac_p.b_training_data import (
    VERSION, OPTIONS, SamplePool, aggregate_scores, canonical, digest,
    independence_certificate, make_game, payload, select_balanced, to_chat_sample,
)
from benac_p.mcts_bp_audit import CELLS, write_json, write_jsonl
from benac_p.mcts_oracle import Budget
from benac_p.private_game_pilot import apply
from benac_p.sft_data_audit import topology_hash
from benac_p.state import GameState


def explicit_worlds(prior, learner, own):
    others = [p for p in range(len(prior)) if p != learner]
    positions = np.indices(tuple(len(prior[p]) for p in others), dtype=np.int16).reshape(len(others), -1).T
    worlds = np.full((len(positions), len(prior)), own, dtype=np.int16)
    for column, player in enumerate(others):
        worlds[:, player] = np.asarray(prior[player])[positions[:, column]]
    return worlds


def mask_of(native, oracle):
    return sum(int(native.commitments[p, a]) << (oracle.offsets[p] + a)
               for p in range(oracle.spec.n_players) for a in range(oracle.spec.n_actions_per_player[p]))


def native_step_checked(native, pending, node, action, oracle):
    translated = oracle.native_action(node, action)
    new_pending = apply(native, pending, translated)
    new_node = oracle.step(node, action)
    assert new_node[:2] == (mask_of(native, oracle), native.turn_index)
    assert (new_node[2] is None) == (new_pending is None)
    return new_pending, new_node, translated.to_dict()


def support_record(pool, oracle, public_prior, source, node, domains, learner, own,
                   history, target, goal, origin, certificate):
    answer = dict(possible_preferences=oracle.semantic_support(domains, target, goal))
    assert answer['possible_preferences']
    return pool.add(source, payload(oracle, public_prior, node, learner, own, history, target, goal),
                    answer, origin, certificate)


def choose_branches(oracle, domains, actor, focal, groups, actual_action, maximum):
    chosen = [actual_action]
    ranked = sorted(groups, key=lambda action: digest(action))
    # Explicitly seek partial updates and non-updates before adding singleton cases.
    for desired in (2, 3, 1):
        for goal in focal:
            matches = [a for a in ranked if len({oracle.catalogues[actor][t][goal] for t in groups[a]}) == desired]
            if matches and matches[0] not in chosen:
                chosen.append(matches[0])
    chosen.extend(a for a in ranked if a not in chosen)
    return chosen[:maximum]


def audit_game(seed, cell, budget, backgrounds=6, focal_count=2, max_branches=6, per_size=24,
               *, config=None, learner_id=None, explicit_world_limit=200000, topology_fn=topology_hash):
    start = time.perf_counter()
    spec, oracle, actual, focal, public_prior = make_game(seed, cell, budget, backgrounds, focal_count, config=config)
    source = f'{cell}_s{seed}'
    learner = spec.round_robin[0] if learner_id is None else learner_id
    if not 0 <= learner < spec.n_players:
        raise ValueError('Invalid learner role')
    own = actual[learner]
    cert = independence_certificate(oracle.catalogues, focal)
    original_world_count = math.prod(len(d) for p, d in enumerate(oracle.prior) if p != learner)
    worlds = explicit_worlds(oracle.prior, learner, own) if original_world_count <= explicit_world_limit else None
    node, domains, history = (0, 0, None), oracle.prior, []
    native, pending, pool = GameState(spec), None, SamplePool()
    trace, certificates, pairs, known_controls = [], [], [], set()
    natural_transitions, branch_transitions = Counter(), Counter()
    first_singleton, interventions = {}, 0
    label_seconds, enumerated_rows = 0.0, 0
    minimum_root_coverage = 1.0
    for player in range(spec.n_players):
        if player == learner:
            continue
        for goal in focal[player]:
            support_record(pool, oracle, public_prior, source, node, domains, learner, own,
                           history, player, goal, dict(kind='initial', event=-1),
                           dict(kind='prior_cartesian_certificate', independence=cert[player]))
    while not oracle.terminal(node):
        event = len(trace)
        actor = oracle.actor(node)
        before, before_node = domains, node
        main = oracle.search(node, actor, actual[actor], domains)
        chosen = main['action']
        minimum_root_coverage = min(minimum_root_coverage, main['root_action_coverage'])
        groups = {}
        clock = time.perf_counter()
        if actor != learner:
            for t in before[actor]:
                prediction = oracle.search(node, actor, t, before)
                minimum_root_coverage = min(minimum_root_coverage, prediction['root_action_coverage'])
                groups.setdefault(prediction['action'], []).append(t)
            enumerated_rows += len(before[actor])
            assert set(t for group in groups.values() for t in group) == set(before[actor])
            assert sum(map(len, groups.values())) == len(before[actor])
            assert chosen in groups and actual[actor] in groups[chosen]
            certificate_id = f'{source}/event{event}'
            certificates.append(dict(id=certificate_id, node=node, domains=before, actor=actor,
                queried_goals=focal[actor],
                mapping=[dict(action=oracle.native_action(node, a).to_dict(), compatible_type_ids=ts)
                         for a, ts in groups.items()],
                exhaustive=True, no_timeout_labels=True))
            kept = tuple(groups[chosen])
            domains = tuple(kept if p == actor else d for p, d in enumerate(before))
            if worlds is not None:
                worlds = worlds[np.isin(worlds[:, actor], kept)]
                for p in range(spec.n_players):
                    if p != learner:
                        assert set(domains[p]) == set(map(int, np.unique(worlds[:, p])))
            assert all(actual[p] in domains[p] for p in range(spec.n_players))
            label_seconds += time.perf_counter() - clock
            before_ids = {}
            for goal in focal[actor]:
                old = oracle.semantic_support(before, actor, goal)
                new = oracle.semantic_support(domains, actor, goal)
                natural_transitions[f'{len(old)}->{len(new)}'] += 1
                if len(new) == 1:
                    first_singleton.setdefault(f'{actor}:{goal}', node[1])
                include = len(old) > 1 or (actor, goal) not in known_controls
                if include:
                    if len(old) == 1:
                        known_controls.add((actor, goal))
                    before_ids[goal] = support_record(pool, oracle, public_prior, source, node, before, learner, own,
                        history, actor, goal, dict(kind='natural', event=event, when='before'),
                        dict(public_prefix=event, support_type_ids=before[actor]))
            for branch in choose_branches(oracle, before, actor, focal[actor], groups, chosen, max_branches):
                branch_native = deepcopy(native)
                _, branch_node, raw = native_step_checked(branch_native, pending, node, branch, oracle)
                branch_history = history + [dict(player_id=actor, action=raw)]
                branch_domains = tuple(tuple(groups[branch]) if p == actor else d for p, d in enumerate(before))
                is_natural = branch == chosen
                # A legal alternative world differs only in this actor's row.
                witness = list(actual)
                witness[actor] = groups[branch][0]
                assert all(witness[p] in before[p] for p in range(spec.n_players))
                for goal, before_id in before_ids.items():
                    old = oracle.semantic_support(before, actor, goal)
                    new = oracle.semantic_support(branch_domains, actor, goal)
                    assert set(new) <= set(old)
                    branch_transitions[f'{len(old)}->{len(new)}'] += 1
                    after_id = support_record(pool, oracle, public_prior, source, branch_node, branch_domains,
                        learner, own, branch_history, actor, goal,
                        dict(kind='natural' if is_natural else 'counterfactual', event=event, when='after',
                             transition=f'{len(old)}->{len(new)}', action=raw,
                             conditional_action_probability=len(groups[branch])/len(before[actor])),
                        dict(action_partition=certificate_id, support_type_ids=groups[branch],
                             legal_prefix_replayed=True, witness_type_ids=witness))
                    pairs.append(dict(before=before_id, after=after_id, source_id=source,
                                      natural=is_natural, transition=f'{len(old)}->{len(new)}'))
        else:
            # Own actions are interventions even when sampled from this UCT.
            domains = before
        pending, node, raw = native_step_checked(native, pending, node, chosen, oracle)
        history.append(dict(player_id=actor, action=raw))
        if actor == learner and interventions < 2:
            for target in range(spec.n_players):
                if target == learner:
                    continue
                for goal in focal[target]:
                    before_id = support_record(pool, oracle, public_prior, source, before_node, before, learner, own,
                        history[:-1], target, goal, dict(kind='intervention', event=event, when='before'),
                        dict(kind='learner_action_is_not_likelihood'))
                    after_id = support_record(pool, oracle, public_prior, source, node, domains, learner, own,
                        history, target, goal, dict(kind='intervention', event=event, when='after'),
                        dict(kind='learner_action_is_not_likelihood'))
                    assert pool.records[before_id]['answer'] == pool.records[after_id]['answer']
                    pairs.append(dict(before=before_id, after=after_id, source_id=source,
                                      natural=True, transition='intervention_unchanged'))
            interventions += 1
        trace.append(dict(event=event, turn=before_node[1], player_id=actor, action=raw,
                          before_domains=before, after_domains=domains, search_seconds=main['seconds']))
        if event % 8 == 0:
            print(json.dumps(dict(source=source, event=event, turn=node[1],
                                  remaining_types=list(map(len, domains)), elapsed=round(time.perf_counter()-start, 2))), flush=True)
    assert native.is_terminal
    np.testing.assert_allclose(native.terminal_rewards(),
                               [int(oracle.utilities[p][t, node[0]]) / oracle.utility_scale for p, t in enumerate(actual)],
                               rtol=0, atol=1e-12)
    records = list(pool.records.values())
    selected = select_balanced(records, per_size)
    selected_ids = {r['id'] for r in selected}
    stats = dict(source_id=source, seconds=time.perf_counter()-start, b_extra_seconds=label_seconds,
                 exhaustive_row_evaluations=enumerated_rows, search_calls=oracle.search_calls,
                 search_seconds=oracle.search_seconds, initial_hidden_worlds=original_world_count,
                 final_hidden_worlds=math.prod(len(d) for p, d in enumerate(domains) if p != learner), raw_unique_samples=len(records),
                 deduplicated_attempts=pool.duplicate_attempts, selected_samples=len(selected),
                 raw_support_sizes=dict(Counter(len(r['answer']['possible_preferences']) for r in records)),
                 selected_support_sizes=dict(Counter(len(r['answer']['possible_preferences']) for r in selected)),
                 natural_transitions=dict(natural_transitions), exported_branch_transitions=dict(branch_transitions),
                 first_focal_singleton_turns=first_singleton,
                 root_action_coverage_min=minimum_root_coverage,
                 full_update_pairs=len(pairs), selected_complete_pairs=sum(p['before'] in selected_ids and p['after'] in selected_ids for p in pairs),
                 native_replay_verified=True, explicit_joint_support_verified=worlds is not None,
                 factorized_support_used=True,
                 independence_certified=True, terminal_rewards=native.terminal_rewards().tolist())
    game = dict(source_id=source, cell=cell, seed=seed, spec=spec.to_dict(include_private=True),
                topology=topology_fn(spec), learner=learner, focal_goals=focal,
                public_prior=public_prior, catalogues=oracle.catalogues, realized_type_ids=actual,
                independence_certificate=cert, trace=trace, action_partitions=certificates, stats=stats)
    if config is not None:
        game['generation_config'] = asdict(config)
    oracle.clear_caches()
    return game, records, selected, pairs


def write_dataset(output, games, pool, selected, pairs, expected_games):
    source_split = {}
    topology_split = {}
    for index, game in enumerate(games):
        # Four sequential seeds per cell: first two train, third validation,
        # fourth test. A repeated topology inherits its first source's split.
        slot = index % 4
        proposed = ('train', 'train', 'validation', 'test')[slot]
        split = topology_split.setdefault(game['topology'], proposed)
        source_split[game['source_id']] = split
    split_rows = {name: [r for r in selected if source_split[r['source_id']] == name]
                  for name in ('train', 'validation', 'test')}
    all_ids = [r['id'] for r in selected]
    assert len(all_ids) == len(set(all_ids)), 'Cross-source duplicate inputs require source clustering'
    for name, rows in split_rows.items():
        write_jsonl(output / f'b_{name}.jsonl', rows)
        write_jsonl(output / f'b_{name}_chat.jsonl', [to_chat_sample(r) for r in rows])
    write_jsonl(output / 'b_all_unique.jsonl', pool)
    write_jsonl(output / 'update_pairs.jsonl', pairs)
    train_counts = Counter(tuple(r['answer']['possible_preferences']) for r in split_rows['train'])
    majority = list(train_counts.most_common(1)[0][0]) if train_counts else OPTIONS
    baselines = {name: dict(always_all=aggregate_scores(rows, lambda _: OPTIONS),
                            train_majority=aggregate_scores(rows, lambda _: majority))
                 for name, rows in split_rows.items()}
    complete = len(games) == expected_games
    summary = dict(version=VERSION, complete=complete, games=len(games), expected_games=expected_games,
                   training_started=False, source_split=source_split,
                   splits={name: dict(sources=sorted({r['source_id'] for r in rows}), samples=len(rows),
                                      support_sizes=dict(Counter(len(r['answer']['possible_preferences']) for r in rows)))
                           for name, rows in split_rows.items()},
                   source_and_topology_disjoint=True, global_input_duplicates=0,
                   raw_unique_samples=len(pool), selected_samples=len(selected),
                   per_game=[g['stats'] for g in games], baselines=baselines,
                   policy_generalization='Not evaluated: labels and data use one explicitly fixed partner policy.',
                   readiness='Data-mechanism audit only; no LLM B accuracy or GPU SFT validation yet.')
    write_json(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('new/local_data/b_independent_focal_v1'))
    parser.add_argument('--seed', type=int, default=63000)
    parser.add_argument('--games-per-cell', type=int, choices=(4,), default=4)
    parser.add_argument('--simulations', type=int, default=1024)
    parser.add_argument('--backgrounds', type=int, default=6)
    parser.add_argument('--focal-goals', type=int, default=2)
    parser.add_argument('--max-branches', type=int, default=6)
    parser.add_argument('--per-size', type=int, default=24)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh output directory; completed runs are immutable.')
    if min(args.max_branches, args.per_size) < 1:
        parser.error('Branch and sample limits must be positive.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(simulations=args.simulations)
    sources = ('b_training_data.py', 'b_data_audit.py', 'b_oracle.py', 'mcts_oracle.py',
               'mcts_bp_audit.py', 'state.py', 'schema.py', 'generator.py', 'private_game_pilot.py',
               'sft_data_audit.py', 'diagnose_protocol.py')
    write_json(args.output_dir / 'manifest.json', dict(version=VERSION,
        configuration={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        fixed_policy_budget=asdict(budget),
        source_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources},
        scope='B-only development corpus. Independent focal goals within finite backgrounds. No claim of native full-prior coverage, training success, or transfer.',
        selection='All sequential source seeds retained. Lawful action-branch augmentation, deduplication and per-source support-size quotas.',
        splits='Four seeds per cell: train/train/validation/test; any identical canonical goal topology is kept in one split.'))
    games, pool, selected, pairs = [], [], [], []
    for cell in CELLS:
        for offset in range(args.games_per_cell):
            print('START', cell, args.seed+offset, flush=True)
            game, raw, picked, updates = audit_game(args.seed+offset, cell, budget, args.backgrounds,
                args.focal_goals, args.max_branches, args.per_size)
            games.append(game); pool.extend(raw); selected.extend(picked); pairs.extend(updates)
            write_json(args.output_dir / 'games' / f'{game["source_id"]}.json', game)
            summary = write_dataset(args.output_dir, games, pool, selected, pairs,
                                    args.games_per_cell * len(CELLS))
            print(json.dumps(game['stats']), flush=True)
    files = sorted(p for p in args.output_dir.rglob('*') if p.is_file())
    write_json(args.output_dir / 'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
