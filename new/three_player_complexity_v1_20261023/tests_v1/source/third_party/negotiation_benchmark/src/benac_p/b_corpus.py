"""Versioned 3/4-player answer-only B corpus and held-out 5-player OOD.

Generate independent sources, independently replay from model-visible fields,
select complete observation pairs, then export immutable split artifacts.
No LLM, probabilities, rationale labels, or GPU training are used here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
from itertools import product
import json
import multiprocessing
import os
import time
from pathlib import Path

import numpy as np

from benac_p.b_data_audit import audit_game, native_step_checked
from benac_p.b_data_validate import GROUNDED_SYSTEM, token_audit
from benac_p.b_oracle import CachedPrivateUCT
from benac_p.b_training_data import canonical, digest, payload, to_chat_sample
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.mcts_oracle import Budget
from benac_p.schema import ActionRef, GameSpec, Goal
from benac_p.state import GameState

VERSION = 'b-corpus-n345-v2'
SPLITS = ('train', 'validation', 'test', 'ood_test')
SYSTEM = GROUNDED_SYSTEM.replace(
    '- A goal is achieved only when ALL its required player/commitment pairs are\n'
    '  bound. Every player\'s terminal utility is the sum of THEIR OWN preference\n'
    '  values over achieved goals. A goal\'s requirements do not say who wants it.',
    '- Each goal declares binary. If true (ALL_OF), satisfaction is 1 only when\n'
    '  ALL required commitments are bound, otherwise 0. If false (LINEAR),\n'
    '  satisfaction is the fraction of its required commitments already bound.\n'
    '  Terminal utility is the sum of YOUR OWN preference value times satisfaction\n'
    '  over all goals. A goal\'s requirements do not say who wants it.'
).replace('Return the full nonempty possible preference set via SUBMIT_JUDGMENT. Brief\n'
          'reasoning is allowed, but probabilities, utilities, Q values and plan variables\n'
          'are not requested.',
          'Return only one SUBMIT_JUDGMENT tool call containing the full nonempty\n'
          'possible preference set. Do not output reasoning, probabilities, utilities,\n'
          'Q values or plan variables.')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(''.join(canonical(r) + '\n' for r in rows))
    temporary.replace(path)


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def structure_fingerprint(spec):
    """Conservative label-invariant refinement, not an exact isomorphism test.

    Identical/relabelled structures ALWAYS co-group. Nonisomorphic collisions
    may also co-group; this sacrifices data, never permits structural leakage.
    Goal scoring types are intentionally ignored so binary/linear variants
    of the same structure cannot cross splits. Avoids n!*(k!)^n enumeration.
    """
    colors, neighbors = [], []
    def add(kind):
        colors.append(kind)
        neighbors.append([])
        return len(colors)-1
    def edge(a, b):
        neighbors[a].append(b)
        neighbors[b].append(a)
    players = [add('player') for _ in range(spec.n_players)]
    actions = {}
    for p, count in enumerate(spec.n_actions_per_player):
        for a in range(count):
            actions[p, a] = add('commitment')
            edge(players[p], actions[p, a])
    for goal in spec.goals:
        node = add('goal')
        for a in goal.required_actions:
            edge(node, actions[a.player_id, a.action_id])
    # Fixed graph-size-dependent round count makes the digest relabel invariant.
    for _ in range(len(colors)):
        colors = [digest((c, sorted(colors[j] for j in neighbors[i]))) for i, c in enumerate(colors)]
    return digest(sorted(colors))


def plan_sources(train_games=100, validation_games=40, test_games=40, ood_games=40, seed=73000):
    plan = []
    for split, count in zip(SPLITS, (train_games, validation_games, test_games, ood_games)):
        visits = Counter()
        for i in range(count):
            n = 5 if split == 'ood_test' else (3, 4)[i % 2]
            j = i if n == 5 else i // 2
            k = (2, 3)[j % 2]
            fraction = (0.0, 0.5, 1.0)[(j // 2) % 3]
            goals, rounds = n * (k + 1), (4 if k == 2 else 6)
            cell = f'n{n}_k{k}_g{goals}_r{rounds}_l{round(100*fraction)}'
            learner = visits[cell] % n
            visits[cell] += 1
            cfg = GeneratorConfig(n_players=n, actions_per_player=k, n_goals=goals,
                                  n_rounds=rounds, linear_goal_fraction=fraction)
            plan.append(dict(index=len(plan), split=split, seed=seed+len(plan)*1000,
                             cell=cell, learner=learner, config=asdict(cfg)))
    return plan


def select_pairs(records, pairs, maximum):
    """Select whole pairs plus formation questions; never quota-truncate an endpoint."""
    if maximum < 8:
        raise ValueError('samples-per-game must be at least 8 to retain task groups')
    by_id = {r['id']: r for r in records}
    selected = {}
    initial = sorted((r for r in records if not r['input']['history']), key=lambda r: r['id'])
    for row in initial[:max(1, maximum//5)]:
        selected[row['id']] = row
    groups = {'maintain': [], 'update': []}
    seen = set()
    for pair in pairs:
        key = pair['before'], pair['after']
        if key in seen:
            continue
        seen.add(key)
        before, after = (by_id[x] for x in key)
        kind = 'maintain' if before['answer'] == after['answer'] else 'update'
        groups[kind].append(pair)
    def priority(pair):
        before, after = by_id[pair['before']], by_id[pair['after']]
        size = len(before['answer']['possible_preferences'])
        # Nontrivial two-value maintenance is especially informative, but retain
        # natural and lawful alternative branches rather than copying examples.
        return (size == 1, size != 2, not pair.get('natural', False), digest(pair))
    for group in groups.values():
        group.sort(key=priority)
    while any(groups.values()):
        for kind in ('maintain', 'update'):
            if not groups[kind]:
                continue
            pair = groups[kind].pop(0)
            missing = [i for i in (pair['before'], pair['after']) if i not in selected]
            if len(selected) + len(missing) <= maximum:
                selected.update((i, by_id[i]) for i in missing)
    # Do not fill the last odd slot with an orphaned after-question.
    selected_pairs = [p for p in pairs if p['before'] in selected and p['after'] in selected]
    selected_pairs = list({(p['before'], p['after']): p for p in selected_pairs}.values())
    return sorted(selected.values(), key=lambda r: r['id']), selected_pairs


def public_oracle(data, budget):
    """Construct the label oracle from LM-visible input ONLY, without seed/private realization."""
    game, prior = data['game'], data['public_prior']
    if len(prior) != game['n_players']:
        raise ValueError('Prior must describe every player')
    catalogues = []
    for player in range(game['n_players']):
        description = prior[player]
        if description['player_id'] != player:
            raise ValueError('Prior player order mismatch')
        if description.get('distribution') != ('Uniform independent background choice and independent uniform choice for each focal goal. '
                                                'null marks a focal slot, not a neutral preference.'):
            raise ValueError('This label oracle requires the declared uniform independent prior')
        goals = description['independent_goal_ids']
        if (len(set(goals)) != len(goals) or any(g < 0 or g >= len(game['goals']) for g in goals)
                or description['independent_goal_values'] != ['want', 'neutral', 'avoid']):
            raise ValueError('Invalid independent preference prior')
        rows = []
        for background in description['background_rows']:
            if (len(background) != len(game['goals']) or
                    any((v is not None if g in goals else v not in (-1, 0, 1)) for g, v in enumerate(background))):
                raise ValueError('Invalid background preference row')
            for values in product((1, 0, -1), repeat=len(goals)):
                row = list(background)
                for g, v in zip(goals, values):
                    if background[g] is not None:
                        raise ValueError('Independent slot must be null')
                    row[g] = v
                rows.append(tuple(row))
        catalogues.append(tuple(rows))
    prefs = np.zeros((game['n_players'], len(game['goals'])), dtype=np.int8)
    learner = data['learner_id']
    prefs[learner] = data['own_preferences']
    own = catalogues[learner].index(tuple(data['own_preferences']))
    spec = GameSpec(n_players=game['n_players'], n_actions_per_player=tuple(game['n_actions_per_player']),
                    goals=tuple(Goal(g['goal_id'], tuple(ActionRef(**a) for a in g['required_actions']), g['binary'])
                                for g in game['goals']), private_preferences=prefs,
                    round_robin=tuple(game['round_robin']), max_changes=game['max_changes'], seed=0,
                    forbidden_actions=game['forbidden_actions'], menu_enabled=game.get('menu_enabled', False))
    return CachedPrivateUCT(spec, catalogues, budget), own


def replay_public(records, budget):
    if not records:
        raise ValueError('Empty source')
    if len({r['source_id'] for r in records}) != 1:
        raise ValueError('Replay must contain exactly one source')
    first = records[0]['input']
    oracle, own = public_oracle(first, budget)
    learner, public = first['learner_id'], first['public_prior']
    cache = {(): ((0, 0, None), oracle.prior, GameState(oracle.spec), None)}
    try:
        for record in records:
            data, key = record['input'], ()
            for event in data['history']:
                next_key = key + (canonical(event),)
                if next_key not in cache:
                    node, domains, native, pending = cache[key]
                    if oracle.actor(node) != event['player_id']:
                        raise ValueError('History actor mismatch')
                    action = next(a for a in oracle.actions(node) if oracle.native_action(node, a).to_dict() == event['action'])
                    after = oracle.update(node, action, domains, learner)
                    clone = deepcopy(native)
                    new_pending, new_node, _ = native_step_checked(clone, pending, node, action, oracle)
                    cache[next_key] = new_node, after, clone, new_pending
                key = next_key
            node, domains, _, _ = cache[key]
            target, goal = data['query']['player_id'], data['query']['goal_id']
            if target == learner or goal not in public[target]['independent_goal_ids']:
                raise ValueError('Invalid independent partner query')
            expected = payload(oracle, public, node, learner, own, data['history'], target, goal)
            if canonical(data) != canonical(expected) or record['id'] != digest(data):
                raise ValueError('Public input reconstruction mismatch')
            answer = dict(possible_preferences=oracle.semantic_support(domains, target, goal))
            if record['answer'] != answer:
                raise ValueError('Gold failed independent public-history replay')
        return dict(verified_questions=len(records), verified_prefixes=len(cache),
                    partner_realization_used=False, stored_certificates_used=False,
                    label_semantics='exact support under declared finite prior and deterministic policy')
    finally:
        oracle.clear_caches()


def chat(record):
    sample = to_chat_sample(record)
    sample['messages'][0]['content'] = SYSTEM
    sample['allow_reasoning'] = False
    return sample


def export_dataset(root, bundles, tokenizer_dir, max_length, max_new_tokens):
    roots = defaultdict(list)
    structures, ids = {}, set()
    all_pairs, split_summary = [], {}
    for bundle in bundles:
        split, fingerprint = bundle['split'], bundle['game']['topology']
        if fingerprint in structures and structures[fingerprint] != split:
            raise ValueError('Structure crossed splits')
        structures[fingerprint] = split
        for row in bundle['selected']:
            if row['id'] in ids:
                raise ValueError('Duplicate input across sources')
            ids.add(row['id'])
            roots[split].append(row)
        all_pairs.extend(bundle['pairs'])
    all_samples = [chat(r) for split in SPLITS for r in roots[split]]
    lengths = token_audit(all_samples, tokenizer_dir)
    too_long = [r for r in lengths['records'] if r['total_tokens'] > max_length or r['prompt_tokens'] + max_new_tokens > max_length]
    write_json(root/'token_lengths.json', lengths)
    if too_long:
        write_json(root/'overlength.json', too_long)
        raise ValueError(f'{len(too_long)} samples exceed generation/training budget; no truncation or silent filtering. '
                         'Use a new configuration with sufficient max-length or smaller games.')
    for split in SPLITS:
        rows = roots[split]
        samples = [chat(r) for r in rows]
        pairs = [p for p in all_pairs if p['source_id'] in {r['source_id'] for r in rows}]
        write_jsonl(root/f'{split}.jsonl', samples)
        write_jsonl(root/f'{split}_prompts.jsonl', [dict(id=s['id'], source_id=s['source_id'],
                                                      messages=s['messages'][:-1], tools=s['tools']) for s in samples])
        write_jsonl(root/f'{split}_gold.jsonl', [dict(id=r['id'], source_id=r['source_id'], answer=r['answer']) for r in rows])
        write_jsonl(root/f'{split}_pairs.jsonl', pairs)
        by_id = {r['id']: r for r in rows}
        kind_counts = Counter('maintain' if by_id[p['before']]['answer'] == by_id[p['after']]['answer'] else 'update' for p in pairs)
        split_summary[split] = dict(sources=len({r['source_id'] for r in rows}), samples=len(rows),
                                   formation=sum(not r['input']['history'] for r in rows), pairs=dict(kind_counts),
                                   all_pair_endpoints_present=True,
                                   answers=dict(Counter('|'.join(r['answer']['possible_preferences']) for r in rows)),
                                   players=dict(Counter(r['input']['game']['n_players'] for r in rows)))
    write_jsonl(root/'update_pairs.jsonl', all_pairs)
    write_json(root/'summary.json', dict(version=VERSION, complete=True, splits=split_summary,
                                       source_and_structure_disjoint=True, training_started=False,
                                       posterior_probabilities_exported=False, reasoning_targets=False,
                                       limitations=['Finite background prior, not full independent native preference space',
                                                    'Five-player OOD also scales goals and history',
                                                    'Single fixed budgeted MCTS policy, no second-order ToM']))
    files = [p for p in root.rglob('*') if p.is_file() and p.name not in ('checksums.json', 'READY.json') and not p.name.endswith('.tmp')]
    write_json(root/'checksums.json', {str(p.relative_to(root)): checksum(p) for p in files})
    write_json(root/'READY.json', dict(complete=True, checksums_sha256=checksum(root/'checksums.json')))


# Only this exact preceding scheduler is eligible for transparent resume migration.
# Oracle, scoring, selection, tokenizer and all configuration hashes still must match.
SERIAL_SCHEDULER_SHA256 = 'ea3336b19fb88e987409fe9820b6354198d65cff4714a4e01c0aebb1cde8b7d6'


def resume_matches(previous, current):
    previous = deepcopy(previous)
    if previous['source_sha256'].get('b_corpus.py') == SERIAL_SCHEDULER_SHA256:
        previous['source_sha256']['b_corpus.py'] = current['source_sha256']['b_corpus.py']
    return canonical(previous) == canonical(current)


def load_bundle(directory):
    hashes = json.loads((directory/'complete.json').read_text())
    if set(hashes) != {'all_questions.jsonl', 'bundle.json'}:
        raise ValueError('Invalid source completion marker')
    for name, expected in hashes.items():
        if checksum(directory/name) != expected:
            raise ValueError('Completed source was modified')
    return json.loads((directory/'bundle.json').read_text())


def generate_source(job):
    item, seed, directory, budget, settings = job
    cfg = GeneratorConfig(**item['config'])
    marker = directory/'complete.json'
    started = time.monotonic()
    print('GENERATE', item['split'], item['cell'], seed, flush=True)
    game, raw, _, updates = audit_game(seed, item['cell'], budget, settings['backgrounds'], 2,
                                      settings['max_branches'], 24, config=cfg, learner_id=item['learner'],
                                      topology_fn=structure_fingerprint)
    selected, pairs = select_pairs(raw, updates, settings['samples_per_game'])
    game['stats'].update(selected_samples=len(selected),
                         selected_support_sizes=dict(Counter(len(r['answer']['possible_preferences']) for r in selected)),
                         selected_complete_pairs=len(pairs), selection='whole-pairs-and-formation-v2')
    print('PUBLIC_REPLAY', game['source_id'], len(selected), flush=True)
    verification = replay_public(selected, budget)
    bundle = dict(split=item['split'], game=game, selected=selected, pairs=pairs, verification=verification)
    write_jsonl(directory/'all_questions.jsonl', raw)
    write_json(directory/'bundle.json', bundle)
    write_json(marker, {name: checksum(directory/name) for name in ('all_questions.jsonl', 'bundle.json')})
    print('SOURCE_DONE', item['index'], game['source_id'],
          round(time.monotonic()-started, 2), 'seconds', flush=True)
    return item['index']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--tokenizer-dir', type=Path, required=True)
    parser.add_argument('--train-games', type=int, default=100)
    parser.add_argument('--validation-games', type=int, default=40)
    parser.add_argument('--test-games', type=int, default=40)
    parser.add_argument('--ood-games', type=int, default=40)
    parser.add_argument('--seed', type=int, default=73000)
    parser.add_argument('--samples-per-game', type=int, default=32)
    parser.add_argument('--simulations', type=int, default=1024)
    parser.add_argument('--backgrounds', type=int, default=6)
    parser.add_argument('--max-branches', type=int, default=6)
    parser.add_argument('--max-length', type=int, default=8192)
    parser.add_argument('--generation-max-new-tokens', type=int, default=128)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--workers', type=int, default=1, help='Independent CPU processes; may change on resume')
    args = parser.parse_args(argv)
    if min(args.train_games, args.validation_games, args.test_games, args.ood_games) < 1:
        parser.error('Each split needs at least one source game')
    if args.samples_per_game < 8 or args.backgrounds < 3 or args.backgrounds % 3 or args.max_branches < 1:
        parser.error('Invalid sample/background/branch limits')
    if args.max_length <= args.generation_max_new_tokens or args.generation_max_new_tokens < 1:
        parser.error('Invalid token budget')
    if args.workers < 1:
        parser.error('--workers must be positive')
    budget = Budget(simulations=args.simulations)
    plan = plan_sources(args.train_games, args.validation_games, args.test_games, args.ood_games, args.seed)
    config = {k: str(v.resolve()) if isinstance(v, Path) else v for k, v in vars(args).items() if k not in ('resume', 'workers')}
    sources = ('b_corpus.py', 'b_training_data.py', 'b_data_audit.py', 'b_data_validate.py', 'b_oracle.py',
               'mcts_oracle.py', 'generator.py', 'schema.py', 'state.py', 'private_game_pilot.py', 'diagnose_protocol.py')
    manifest = dict(version=VERSION, configuration=config, plan=plan, budget=asdict(budget),
                    source_sha256={name: checksum(Path(__file__).with_name(name)) for name in sources},
                    tokenizer_sha256={name: checksum(args.tokenizer_dir/name) for name in
                                      ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja')
                                      if (args.tokenizer_dir/name).exists()},
                    topology_grouping='conservative unlabeled graph refinement, ignoring goal scoring type')
    root = args.output_dir
    if args.resume:
        if not resume_matches(json.loads((root/'manifest.json').read_text()), manifest):
            parser.error('Resume configuration, source code, or tokenizer changed; use a fresh directory')
        if (root/'READY.json').exists():
            parser.error('Corpus already complete; immutable output')
    elif root.exists() and any(root.iterdir()):
        parser.error('Use a fresh output directory or explicit --resume')
    root.mkdir(parents=True, exist_ok=True)
    write_json(root/'manifest.json', manifest)
    bundles, structures, jobs = {}, {}, []
    # Reserve topology in original plan order before dispatch. Worker completion
    # order cannot affect seeds, split isolation, selection or exported row order.
    for item in plan:
        directory = root/'sources'/f"source-{item['index']:04d}"
        cfg = GeneratorConfig(**item['config'])
        for attempt in range(1000):
            seed = item['seed'] + attempt
            fingerprint = structure_fingerprint(generate_game(seed, cfg))
            if fingerprint not in structures:
                break
        else:
            raise RuntimeError('Could not find a new structure within seed allocation')
        structures[fingerprint] = item['split']
        if (directory/'complete.json').exists():
            bundle = load_bundle(directory)
            if bundle['game']['topology'] != fingerprint or bundle['split'] != item['split']:
                raise ValueError('Completed source does not match deterministic plan')
            bundles[item['index']] = bundle
        else:
            jobs.append((item, seed, directory, budget, vars(args)))
    def progress():
        write_json(root/'progress.json', dict(completed_sources=len(bundles),
                                             planned_sources=len(plan), workers=args.workers))
        print('PROGRESS', len(bundles), '/', len(plan), flush=True)
    progress()
    if args.workers == 1:
        results = map(generate_source, jobs)
        for index in results:
            bundles[index] = load_bundle(root/'sources'/f'source-{index:04d}')
            progress()
    elif jobs:
        # Each process runs scalar/tree workloads; avoid BLAS oversubscription.
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                     'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            os.environ[name] = '1'
        with multiprocessing.get_context('spawn').Pool(min(args.workers, len(jobs))) as pool:
            for index in pool.imap_unordered(generate_source, jobs, chunksize=1):
                bundles[index] = load_bundle(root/'sources'/f'source-{index:04d}')
                progress()
    bundles = [bundles[item['index']] for item in plan]
    export_dataset(root, bundles, args.tokenizer_dir, args.max_length, args.generation_max_new_tokens)
    print((root/'summary.json').read_text(), flush=True)


if __name__ == '__main__':
    main()
