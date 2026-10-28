"""Freeze structurally disjoint shared-parent train/dev/test game pools."""
import argparse
from collections import Counter
from copy import deepcopy
from itertools import combinations, permutations, product
import time

import numpy as np
from training.b_sft.preference_contract import profile, world_weights
from training.b_sft.social_private_teacher import PrivateEpisode, PrivateWindow, PrivateInvestigationRules, observed_slots, audit_native
from training.b_sft.shared_teacher import SearchLimit
from .common import VERSION, digest, stable, write_json, write_rows, file_hash, save_reference, seed_for
from .values import window_values, masked_answer_value


def structural_family(game):
    """Canonical topology under player/action/goal renaming, including schedule."""
    n = game['n_players']
    representations = []
    for players in permutations(range(n)):
        for coordinates in product(*(tuple(permutations(range(k))) for k in game['n_actions_per_player'])):
            goals = sorted((bool(g['binary']), tuple(sorted(
                (players[a['player_id']], coordinates[a['player_id']][a['action_id']])
                for a in g['required_actions']))) for g in game['goals'])
            counts = [0] * n
            for p in range(n):
                counts[players[p]] = game['n_actions_per_player'][p]
            representations.append(stable((counts, goals, [players[p] for p in game['round_robin']], game['max_changes'])))
    return digest(min(representations))[:20]


def with_multi_action_goal(raw, seed):
    """Add one native same-player requirement; preserve every other game field.

    This paired intervention uses a separate RNG, so preferences, support,
    prior, turn order, coordinates and binary/linear modes cannot drift with
    the topology change. Return a null change when no such addition is legal.
    It broadens structural coverage, not a guarantee of positive information.
    """
    result = deepcopy(raw)
    eligible = []
    for gi, goal in enumerate(raw['game']['goals']):
        occupied = {(a['player_id'], a['action_id']) for a in goal['required_actions']}
        for player in sorted({p for p, _ in occupied}):
            for action in range(raw['game']['n_actions_per_player'][player]):
                if (player, action) not in occupied:
                    eligible.append((gi, player, action))
    if not eligible:
        return result, None
    rng = np.random.default_rng(seed_for('multi-action-goal-v1', seed))
    gi, player, action = eligible[int(rng.integers(len(eligible)))]
    result['game']['goals'][gi]['required_actions'].append(dict(player_id=player, action_id=action))
    result['game']['goals'][gi]['required_actions'].sort(key=lambda a: (a['player_id'], a['action_id']))
    return result, dict(goal_id=raw['game']['goals'][gi]['goal_id'],
                        added_requirement=dict(player_id=player, action_id=action))


def sample_parent(seed, players, rounds=None, *, goal_structure='legacy'):
    if goal_structure not in ('legacy', 'multi_action'):
        raise ValueError('Unknown goal_structure')
    rng = np.random.default_rng(seed)
    coordinates = [2, 2] if players == 2 else [1, 1, 1]
    if players == 3 and rng.random() < .6:
        coordinates[int(rng.integers(3))] = 2
    possible = []
    for arity in range(2, players + 1):
        for owners in combinations(range(players), arity):
            possible.extend(tuple(zip(owners, acts)) for acts in product(*(range(coordinates[p]) for p in owners)))
    count = int(rng.integers(2, min(4, len(possible)) + 1))
    chosen = rng.choice(len(possible), count, replace=False)
    mode = int(rng.integers(3))
    goals = [dict(goal_id=g, required_actions=[dict(player_id=p, action_id=a) for p, a in possible[i]],
                  binary=mode == 0 or (mode == 2 and bool(rng.integers(2)))) for g, i in enumerate(chosen)]
    base = rng.choice([-1, 0, 1], size=(players, count))
    protected = set()
    for p in range(players):
        g = int(rng.integers(count)); base[p, g] = 1; protected.add((p, g))
    for g in range(count):
        p = int(rng.integers(players)); base[p, g] = 1; protected.add((p, g))
    eligible = [(p, g) for p in range(players) for g in range(count) if (p, g) not in protected]
    hidden = {eligible[i] for i in rng.permutation(len(eligible))[:min(3, len(eligible))]}
    types = {}
    for p in range(players):
        slots = [g for g in range(count) if (p, g) in hidden]
        rows = []
        for values in product([1, 0, -1], repeat=len(slots)):
            row = base[p].tolist()
            for g, v in zip(slots, values):
                row[g] = v
            rows.append(row)
        types[str(p)] = rows
    sampled_rounds = int(rng.choice([1, 2], p=[.8, .2])) if players == 2 else 1
    rounds = sampled_rounds if rounds is None else rounds
    if type(rounds) is not int or rounds < 1:
        raise ValueError('A positive round count is required')
    order = list(map(int, rng.permutation(players)))
    game = dict(n_players=players, n_actions_per_player=coordinates, goals=goals,
                round_robin=order * rounds, max_changes=1, menu_enabled=False)
    raw = dict(game=game, ego=0, own_preferences=types['0'][0], type_catalogues=types,
               background_prior=profile(['balanced', 'want_heavy', 'neutral_heavy', 'avoid_heavy'][seed % 4]))
    return with_multi_action_goal(raw, seed)[0] if goal_structure == 'multi_action' else raw


def entrances(tree, seed, trajectories=12, epsilon=.25):
    """All-player epsilon-reference reach; condition only on the entrant's view."""
    rng = np.random.default_rng(seed)
    cells = {}
    for _ in range(trajectories):
        wi = int(rng.choice(tree.w, p=tree.world_weights))
        world = tree.worlds[wi]
        index, history, reach = 0, [], tree.world_weights.copy()
        while tree.entries[index].actor is not None:
            entry = tree.entries[index]; ego = entry.actor
            slots = observed_slots(entry.node, ego)
            facts = [(p, g, world[p][g]) for p, g in slots]
            mask = np.array([w[ego] == world[ego] and all(w[p][g] == v for p, g, v in facts) for w in tree.worlds])
            weights = reach * mask
            weights /= weights.sum()
            key = digest((index, world[ego], facts))
            cells[key] = dict(root_index=index, ego=ego, own=list(world[ego]), private_results=facts,
                              history=list(history), entry_world_weights=weights.tolist())
            probs = (1 - epsilon) * tree.policy[index] + epsilon / len(entry.actions)
            ai = int(rng.choice(len(entry.actions), p=probs[:, wi]))
            reach *= probs[ai]
            reach /= reach.sum()
            history.append(ai); index = entry.children[ai]
    return sorted(cells.values(), key=lambda x: digest(x))


def measure_entrance(tree, entrance, parent_id, config):
    root, ego, weights = entrance['root_index'], entrance['ego'], entrance['entry_world_weights']
    curves = [dict(k=k, **window_values(tree, ego, root, weights, k)) for k in range(1, config['max_k'] + 1)]
    retained = []; previous_span = 0.0; previous_s = 0.0
    for metric in curves:
        span = metric['C_span']
        informative_extension = span - previous_span > config['min_increment']
        previous_span = span
        if span <= config['min_c']:
            continue
        information = []
        for ai, action in enumerate(tree.entries[root].actions):
            raw = action.to_dict()
            if raw.get('action') == 'INVESTIGATE':
                # A constant answer carries exactly zero information. Its
                # physical action/cost remains in every best/worst calculation.
                support = {w[raw['player']][raw['goal']] for w, mass in zip(tree.worlds, weights) if mass > 0}
                if len(support) <= 1:
                    s = conditional = 0.
                else:
                    result = masked_answer_value(tree, ego=ego, root_index=root, root_weights=weights,
                                                 query_slot=(raw['player'], raw['goal']), k=metric['k'])
                    s = result['S']
                    conditional = max(0., result['full']['root_action_values'][ai] - result['masked']['root_action_values'][ai])
                information.append(dict(slot=[raw['player'], raw['goal']], S=s, S_given_query=conditional))
        information_value = max((x['S'] for x in information), default=0.)
        behavior = None
        if config.get('measure_public_behavior', False):
            from .behavior_information import public_behavior_value
            behavior = public_behavior_value(tree, ego=ego, root_index=root,
                root_weights=weights, k=metric['k'], seconds=config.get('behavior_seconds', 5.))
            information_value = max(information_value, behavior['S'])
        informative_answer = information_value - previous_s > config['min_s']
        previous_s = information_value
        if metric['k'] > 1 and not informative_extension and not informative_answer:
            continue
        row = dict(entrance, parent_id=parent_id, k=metric['k'], V_star=metric['V_star'],
                   C_span=span, C_span_normalized=span / len(tree.rules.spec.goals),
                   length_curve=curves, information_values=information,
                   information_positive=information_value > config['min_s'])
        if behavior is not None:
            row.update(behavior_information=behavior,
                information_metric_version='query-plus-future-public-history-v1',
                S_query=max((x['S'] for x in information), default=0.),
                S_behavior=behavior['S'], S_max=information_value)
        row['id'] = digest((parent_id, entrance, metric['k']))[:24]
        retained.append(row)
    return retained, curves


def cap_slices(retained, config):
    # Round-robin lengths and player roles; positive/zero S are strata, not eligibility gates.
    pools = {}
    for row in retained:
        pools.setdefault((row['ego'], row['k'], row['information_positive']), []).append(row)
    selected = []
    while pools and len(selected) < config['slices_per_parent']:
        for key in sorted(list(pools), key=lambda k: (not k[2], k[0], k[1])):
            selected.append(pools[key].pop(0))
            if not pools[key]:
                del pools[key]
            if len(selected) == config['slices_per_parent']:
                break
    return selected


def select_slices(tree, parent_id, seed, config):
    candidates = entrances(tree, seed, config['entrance_trajectories'], config['reach_epsilon'])
    retained = []
    for entrance in candidates[:config['max_entrances']]:
        rows, _ = measure_entrance(tree, entrance, parent_id, config)
        retained.extend(rows)
    return cap_slices(retained, config), len(candidates)


def fixed_entrances(reference, seed, trajectories=12, epsilon=.25):
    """Native epsilon-reference paths without constructing a full action tree."""
    rng = np.random.default_rng(seed); cells = {}
    rules = reference.rules
    prior = reference.world_weights
    for _ in range(trajectories):
        wi = int(rng.choice(len(rules.worlds), p=prior)); world = rules.worlds[wi]
        node = rules.initial(); history = []; reach = prior.copy()
        while rules.actor(node) is not None:
            ego = rules.actor(node)
            facts = [(p, g, world[p][g]) for p, g in observed_slots(node, ego)]
            mask = np.array([w[ego] == world[ego] and all(w[p][g] == v for p, g, v in facts) for w in rules.worlds])
            weights = reach * mask; weights /= weights.sum()
            entrance = dict(root_index=0, ego=ego, own=list(world[ego]), private_results=facts,
                            history=list(history), entry_world_weights=weights.tolist(),
                            proposal_turn=node.state.turn_index)
            cells[digest((history, world[ego], facts))] = (entrance, node)
            actions = rules.actions(node)
            probs = (1 - epsilon) * reference.probabilities(node) + epsilon / len(actions)
            ai = int(rng.choice(len(actions), p=probs[:, wi]))
            reach *= probs[ai]; reach /= reach.sum()
            history.append(ai); node = rules._apply(node, actions[ai])
    # Round-robin focal roles and proposal rounds before the entrance cap.
    pools = {}
    for entrance, node in sorted(cells.values(), key=lambda pair: digest(pair[0])):
        pools.setdefault((entrance['proposal_turn'] // rules.spec.n_players, entrance['ego']), []).append((entrance, node))
    ordered = []
    while pools:
        for key in sorted(list(pools)):
            ordered.append(pools[key].pop(0))
            if not pools[key]:
                del pools[key]
    return ordered


def select_fixed_slices(reference, parent_id, seed, config):
    from .sparse import SparseWindow
    candidates = fixed_entrances(reference, seed, config['entrance_trajectories'], config['reach_epsilon'])
    retained = []; diagnostics = []; audits = []
    for entrance, node in candidates[:config['max_entrances']]:
        tree = SparseWindow(reference, node, entrance['ego'], entrance['entry_world_weights'],
                            config['max_k'], config['max_nodes'], config['solver_seconds'])
        rows, curves = measure_entrance(tree, entrance, parent_id, config)
        retained.extend(rows); audits.append(tree.audit_native())
        diagnostics.append(dict(ego=entrance['ego'], proposal_turn=entrance['proposal_turn'],
                                history=entrance['history'], nodes=len(tree.entries),
                                C_span_by_k=[c['C_span'] for c in curves],
                                V_star_by_k=[c['V_star'] for c in curves],
                                V_min_by_k=[c['V_min'] for c in curves]))
    return cap_slices(retained, config), len(candidates), diagnostics, audits


def build(output, config, reuse=None):
    from pathlib import Path
    source_files = list(Path(__file__).parent.glob('*.py'))
    source_start = {str(p.name): file_hash(p) for p in source_files}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'references').mkdir()
    parents = {s: [] for s in ('train', 'validation', 'test')}
    slices = {s: [] for s in parents}
    targets = {}
    for split in parents:
        total = config[split]
        three = round(total * config['three_player_fraction'])
        targets[split] = {2: total - three, 3: three}
    counts = {s: Counter() for s in parents}; families = Counter(); family_splits = {}; seen = set()
    positive_accepted = Counter()
    cached = {}
    candidate_pool = None
    if config.get('candidate_pool'):
        from pathlib import Path
        import json
        pool_path = Path(config['candidate_pool'])
        config['candidate_pool_sha256'] = file_hash(pool_path)
        candidate_pool = [json.loads(line) for line in pool_path.read_text().splitlines() if line.strip()]
    if reuse is not None:
        if config.get('reference_policy', 'synchronous') != 'synchronous':
            raise ValueError('Saved equilibrium references cannot be reused as a different reference policy')
        for line in (reuse / 'generation_log.jsonl').read_text().splitlines():
            record = __import__('json').loads(line)
            if record['status'] == 'accepted':
                raw = sample_parent(record['seed'], record['players'],
                                    config.get('three_player_rounds', 1) if record['players'] == 3 else None,
                                    goal_structure=config.get('goal_structure', 'legacy'))
                if digest(raw)[:24] == record['parent_id']:
                    cached[digest(raw)] = reuse / 'references' / (record['parent_id'] + '.npz')
    started = time.monotonic()
    with (output / 'generation_log.jsonl').open('w') as log:
        for attempt in range(config['max_attempts']):
            if all(counts[s][n] >= targets[s][n] for s in parents for n in (2, 3)):
                break
            seed = config['seed'] + attempt
            if candidate_pool is not None:
                if attempt >= len(candidate_pool):
                    break
                raw = candidate_pool[attempt]
                n = raw['game']['n_players']
                if n not in (2, 3):
                    raise ValueError('Candidate pool requires two/three-player parents')
                if all(counts[s][n] >= targets[s][n] for s in parents):
                    log.write(stable(dict(attempt=attempt, seed=seed, players=n, status='quota_or_duplicate')) + '\n')
                    continue
            else:
                n = min((n for n in (2, 3) if any(counts[s][n] < targets[s][n] for s in parents)),
                        key=lambda n: sum(counts[s][n] for s in parents) / max(1, sum(targets[s][n] for s in parents)))
                raw = sample_parent(seed, n, config.get('three_player_rounds', 1) if n == 3 else config.get('two_player_rounds'),
                                    goal_structure=config.get('goal_structure', 'legacy'))
            family = structural_family(raw['game'])
            # Freeze a whole family in the most underfilled player-count split.
            # Assignment uses only structural eligibility/quotas, never an LLM result.
            split = family_splits.get(family) or min((s for s in parents if counts[s][n] < targets[s][n]), key=lambda s: (
                counts[s][n] / max(1, targets[s][n]), digest((family, s))))
            row = dict(attempt=attempt, seed=seed, players=n, family=family, split=split,
                       rounds=len(raw['game']['round_robin']) // n,
                       reference_backend=config.get('reference_policy', 'synchronous'))
            identity = digest(raw)
            participants = {a['player_id'] for g in raw['game']['goals'] for a in g['required_actions']}
            if len(participants) != n:
                row['status'] = 'excluded'; row['reason'] = 'A player is absent from every public goal'
            elif counts[split][n] >= targets[split][n] or families[family] >= config['max_per_family'] or identity in seen:
                row['status'] = 'quota_or_duplicate'
            else:
                try:
                    origin = cached.get(identity)
                    parent_id = identity[:24]
                    fixed = config.get('reference_policy') == 'fixed-myopic-v1'
                    bounded = config.get('reference_policy') == 'bounded-next-own-v1'
                    candidate_started = time.monotonic()
                    if bounded:
                        from .bounded_data import select_bounded_slices
                        selected, entrance_count, diagnostic, references, prior = select_bounded_slices(
                            raw, parent_id, seed, config, output)
                        row['window_diagnostics'] = diagnostic
                        audit = {key: r['native_audit'] for key, r in references.items()}
                        policy_fields = dict(reference_backend='bounded-next-own-v1',
                            bounded_references=references, world_weights=prior)
                    elif fixed:
                        from .reference import FixedReference
                        reference = FixedReference(PrivateInvestigationRules(raw), raw['background_prior'])
                        selected, entrance_count, diagnostic, audit = select_fixed_slices(reference, parent_id, seed, config)
                        row['window_diagnostics'] = diagnostic
                        policy_fields = dict(reference_backend='fixed-myopic-v1', certificate=reference.certificate,
                                             reference_origin='Public fixed myopic rule; no equilibrium solve',
                                             world_weights=world_weights(reference.rules.worlds, raw['background_prior']).tolist())
                    elif origin is None:
                        tree = PrivateEpisode(raw, seconds=config['solver_seconds'], max_nodes=config['max_nodes'], max_sweeps=128).tree
                    else:
                        rules = PrivateInvestigationRules(raw)
                        tree = PrivateWindow(rules, rules.initial(), rules.worlds,
                            world_weights=world_weights(rules.worlds, raw['background_prior']),
                            seconds=max(15, config['solver_seconds']), max_nodes=config['max_nodes'], max_sweeps=128)
                        flat = np.load(origin, allow_pickle=False)['probabilities']; cursor = 0
                        for index, entry in enumerate(tree.entries):
                            if entry.actor is not None:
                                size = len(entry.actions) * tree.w
                                tree.policy[index] = flat[cursor:cursor + size].reshape(len(entry.actions), tree.w)
                                cursor += size
                        if cursor != len(flat):
                            raise ValueError('Cached policy shape mismatch')
                        before = [p.copy() if p is not None else None for p in tree.policy]
                        tree.solve()  # Independent fixed-point, deviation and privacy re-certification.
                        if any(not np.array_equal(a, b) for a, b in zip(before, tree.policy)):
                            raise ValueError('Previously certified policy changed')
                    if not fixed and not bounded:
                        selected, entrance_count = select_slices(tree, parent_id, seed, config)
                        audit = audit_native(tree)
                        filename = f'references/{parent_id}.npz'
                        save_reference(output / filename, tree)
                        policy_fields = dict(world_weights=tree.world_weights.tolist(), certificate=tree.certificate,
                                             reference_file=filename, reference_sha256=file_hash(output / filename),
                                             reference_origin=str(origin) if origin else 'fresh uniform-initialized solve')
                    if not selected:
                        raise ValueError('No consequential slice in sampled entrances')
                    has_positive = any(s['information_positive'] for s in selected)
                    remaining = config[split] - sum(counts[split].values())
                    deficit = config.get('min_positive_s_parents', 0) - positive_accepted[split]
                    if not has_positive and remaining <= deficit:
                        raise ValueError('Remaining split slots reserved for positive free-choice S coverage')
                    parent = dict(id=parent_id, family=family, split=split, seed=seed, players=n, raw=raw,
                                  native_audit=audit, entrances_sampled=entrance_count, slices=len(selected),
                                  **policy_fields)
                    parents[split].append(parent)
                    slices[split].extend(dict(s, split=split) for s in selected)
                    counts[split][n] += 1; families[family] += 1; family_splits[family] = split; seen.add(identity)
                    positive_accepted[split] += int(has_positive)
                    for kind, records in [('parents', parents[split]), ('slices', slices[split])]:
                        write_rows(output / f'{split}_{kind}.jsonl', records)
                    nodes = sum(d.get('nodes', 0) for d in diagnostic) if fixed or bounded else len(tree.entries)
                    row.update(status='accepted', parent_id=parent_id, slices=len(selected), nodes=nodes,
                               seconds=time.monotonic() - candidate_started)
                    print(stable(dict(attempt=attempt, accepted=sum(map(len, parents.values())), counts=counts)), flush=True)
                except (SearchLimit, ValueError, RecursionError) as exc:
                    row.update(status='excluded', reason=str(exc))
            log.write(stable(row) + '\n'); log.flush()
        files = {}
        for split in parents:
            for kind, rows in [('parents', parents[split]), ('slices', slices[split])]:
                name = f'{split}_{kind}.jsonl'; write_rows(output / name, rows)
                files[name] = dict(sha256=file_hash(output / name), rows=len(rows))
    complete = all(counts[s][n] == targets[s][n] for s in parents for n in (2, 3))
    positive_counts = {split: len({s['parent_id'] for s in rows if s['information_positive']})
                       for split, rows in slices.items()}
    complete = complete and all(v >= config.get('min_positive_s_parents', 0) for v in positive_counts.values())
    source_unchanged = all(file_hash(p) == source_start[p.name] for p in source_files)
    complete = complete and source_unchanged
    manifest = dict(version=VERSION, config=config, files=files, counts=counts, targets=targets,
                    families={s: len({p['family'] for p in ps}) for s, ps in parents.items()},
                    seconds=time.monotonic() - started, complete=complete,
                    sampling='Uniform parent, then uniform retained slice; no D weighting or adaptive curriculum.',
                    entry='Sampled all-player epsilon-reference trajectories; Bayes conditioning on public path, own type and own private answers.',
                    oracle=('Public fixed myopic information-limited policy; exact focal-window best/worst responses and native terminal tails; no equilibrium claim.'
                            if config.get('reference_policy') == 'fixed-myopic-v1'
                            else 'Selected certified synchronous best-response profile; no uniqueness claim.'),
                    selection='Both arms restricted to the same solvable parents with >=1 consequential sampled slice. All exclusions logged.',
                    split='Canonical topology including schedule, scoring modes and action counts; whole family assigned to underfilled player-count split, ties fixed by hash; no model results used.',
                    limitations=f"Small finite public-support games, 3-player {config.get('three_player_rounds', 1)}-round games; not unrestricted BENAC. Max-k windows may overlap within a parent.")
    manifest['positive_S_parents'] = positive_counts
    manifest['source_sha256'] = source_start
    manifest['source_unchanged_during_build'] = source_unchanged
    if config.get('reference_policy') == 'bounded-next-own-v1':
        from .bounded_data import CONTRACT
        manifest.update(training_contract=CONTRACT,
            entry='World-independent uniform native public prefixes; independently solve each entrance with public prior, then condition on own type/private answers.',
            oracle='All-player mixed private-information next-own cutoff profile; independent complete certification at 1e-8.')
    write_json(output / 'manifest.json', manifest)
    if not complete:
        raise RuntimeError('Incomplete dataset: parent quotas, positive-S coverage or stable source identity failed; inspect manifest and generation log.')
    write_json(output / 'COMPLETE.json', dict(manifest_sha256=file_hash(output / 'manifest.json')))
    return manifest


def main():
    from pathlib import Path
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--reuse-qualified', type=Path, help='Re-certify saved references from an interrupted build with this generator')
    cli.add_argument('--reference-policy', choices=['synchronous', 'fixed-myopic-v1', 'bounded-next-own-v1'], default='synchronous',
                     help='Explicit reference contract; fixed policy avoids the full equilibrium tree')
    cli.add_argument('--three-player-rounds', type=int, help='Defaults to 1 for synchronous, 2 for fixed-myopic-v1')
    cli.add_argument('--two-player-rounds', type=int)
    cli.add_argument('--candidate-pool', help='Optional JSONL of native parents with model-independent prescribed setup histories')
    cli.add_argument('--lookahead-rr', type=int, default=1)
    cli.add_argument('--lookahead-depths', type=int, nargs='+', help='Explicit depths to diagnose/select independently at every entrance')
    cli.add_argument('--max-joint-cells', type=int, default=4096)
    cli.add_argument('--max-joint-evaluations', type=int, default=160)
    cli.add_argument('--min-positive-s-parents', type=int,
                     help='Required positive free-choice S parents in each split; unmet coverage prevents COMPLETE')
    for name, default in [('train', 100), ('validation', 20), ('test', 40), ('max-attempts', 4000),
                          ('max-nodes', 30000), ('max-k', 3), ('max-entrances', 12),
                          ('entrance-trajectories', 12), ('slices-per-parent', 8), ('max-per-family', 8), ('seed', 20261002)]:
        cli.add_argument('--' + name, type=int, default=default)
    cli.add_argument('--three-player-fraction', type=float, default=.5)
    cli.add_argument('--solver-seconds', type=float, default=5)
    cli.add_argument('--reach-epsilon', type=float, default=.25)
    cli.add_argument('--min-c', type=float, default=.1)
    cli.add_argument('--min-increment', type=float, default=.05)
    cli.add_argument('--min-s', type=float, default=.05)
    config = vars(cli.parse_args()); output = config.pop('output').resolve(); reuse = config.pop('reuse_qualified')
    if config['min_positive_s_parents'] is None:
        config['min_positive_s_parents'] = int(config['reference_policy'] == 'bounded-next-own-v1')
    if config['three_player_rounds'] is None:
        config['three_player_rounds'] = (3 if config['reference_policy'] == 'bounded-next-own-v1' else
                                       2 if config['reference_policy'] == 'fixed-myopic-v1' else 1)
    if config['reference_policy'] == 'bounded-next-own-v1' and config['two_player_rounds'] is None:
        config['two_player_rounds'] = 3
    if any(config[k] < 1 for k in ('train', 'validation', 'test', 'max_attempts', 'max_nodes', 'max_k', 'max_entrances', 'entrance_trajectories', 'slices_per_parent', 'max_per_family')):
        cli.error('Counts and limits must be positive')
    if not 0 <= config['three_player_fraction'] <= 1 or not 0 < config['reach_epsilon'] <= 1:
        cli.error('Invalid player fraction or reach epsilon')
    if config['three_player_rounds'] < 1 or config['solver_seconds'] <= 0 or any(config[k] < 0 for k in ('min_c', 'min_increment', 'min_s')):
        cli.error('Solver budget must be positive and thresholds nonnegative')
    if min(config['lookahead_rr'], config['max_joint_cells'], config['max_joint_evaluations']) < 1 or config['min_positive_s_parents'] < 0:
        cli.error('Positive oracle limits and nonnegative coverage quota required')
    if config['lookahead_depths'] and min(config['lookahead_depths']) < 1:
        cli.error('Lookahead depths must be positive')
    if config['two_player_rounds'] is not None and config['two_player_rounds'] < 1:
        cli.error('Two-player rounds must be positive')
    manifest = build(output, config, reuse.resolve() if reuse else None)
    print(stable(dict(output=str(output), counts=manifest['counts'], families=manifest['families'])))


if __name__ == '__main__':
    main()
