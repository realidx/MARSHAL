"""Generate and audit B/P candidates with a fixed finite-private UCT partner.

Artifacts are local/ignored. B answers are exact for the declared finite prior
and deterministic policy. P answers are approximate proposals with separate
budget/seed/continuation validation, NOT certified optimal-action labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.mcts_oracle import Budget, PrivateUCT, VERSION, make_catalogues, stable_seed
from benac_p.private_game_pilot import apply
from benac_p.state import GameState


CELLS = {
    'n4_k2_g12_r4': GeneratorConfig(n_players=4, actions_per_player=2, n_goals=12, n_rounds=4),
    'n4_k3_g16_r6': GeneratorConfig(n_players=4, actions_per_player=3, n_goals=16, n_rounds=6),
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def kind(action):
    raw = action.to_dict()
    return raw.get('action', raw.get('response'))


def input_payload(oracle, node, domains, learner, own_type, history):
    # spec is sanitized; never export realization index, real seed or hidden rows.
    game = oracle.spec.public_dict()
    game.pop('seed', None)
    return dict(game=game, player_id=learner,
                own_preferences=list(oracle.catalogues[learner][own_type]),
                public_type_catalogues=oracle.catalogues,
                prior='Each player independently draws one uniformly distributed public candidate row; this is not the native generator preference prior.',
                partner_policy=dict(version=VERSION, budget=asdict(oracle.budget),
                    source='benac_p/mcts_oracle.py',
                    semantics='Deterministic information-limited UCT. Other players infer oracle types from public actions; learner actions are interventions. Simulation continuation is a 75/25 immediate-reference/random-category mixture at the default budget. It is not exact optimal play.'),
                history=list(history),
                state=dict(commitments=[[int(bool(node[0] & (1 << (oracle.offsets[p] + a))))
                                         for a in range(oracle.spec.n_actions_per_player[p])]
                                        for p in range(oracle.spec.n_players)],
                           turn_index=node[1], remaining_proposers=oracle.spec.round_robin[node[1]:]),
                pending_offer=None if node[2] is None else oracle.native_action((node[0], node[1], None), node[2]).offer.to_dict())


def make_game(seed, cell, profiles, budget):
    base = generate_game(seed, CELLS[cell])
    catalogues = make_catalogues(base.n_players, base.n_goals, seed, profiles)
    rng = random.Random(stable_seed((VERSION, 'realized-types', seed, cell)))
    realized = tuple(rng.randrange(profiles) for _ in range(base.n_players))
    spec = replace(base, menu_enabled=True,
                   private_preferences=np.asarray([catalogues[p][t] for p, t in enumerate(realized)]),
                   metadata={'audit_prior': 'independent_finite_ternary_catalogues_not_native'})
    return spec, PrivateUCT(spec, catalogues, budget), realized


def paired_reference_values(oracle, node, domains, ego, own, actions, samples, seed):
    values = {name: [] for name in actions}
    for repeat in range(samples):
        world_rng = random.Random(stable_seed((seed, repeat, 'world')))
        world = [world_rng.choice(d) for d in domains]
        world[ego] = own
        for name, action in actions.items():
            rng = random.Random(stable_seed((seed, repeat, 'continuation')))
            value = oracle.rollout_return(oracle.step(node, action), world, domains, ego, rng)
            values[name].append(value)
    return values


def difference_stats(first, second):
    differences = np.asarray(first, dtype=float) - np.asarray(second, dtype=float)
    mean = float(np.mean(differences))
    se = float(np.std(differences, ddof=1) / np.sqrt(len(differences))) if len(differences) > 1 else None
    return dict(n=len(differences), mean=mean, paired_standard_error=se,
                approximate_95_interval=None if se is None else [mean - 1.96 * se, mean + 1.96 * se])


def actual_oracle_values(oracle, node, domains, ego, own, actions, samples, seed):
    """Independent continuation audit under ACTUAL UCT partners and updating.

The first ego action is forced in both branches. Thereafter everyone uses
the frozen UCT candidate; ego actions are still interventions for filtering.
Paired hidden worlds are sampled from the root history-consistent support.
"""
    start = time.perf_counter()
    values = {name: [] for name in actions}
    for repeat in range(samples):
        rng = random.Random(stable_seed((seed, repeat, 'actual-world')))
        world = [rng.choice(d) for d in domains]
        world[ego] = own
        for name, action in actions.items():
            current = oracle.step(node, action)
            belief = domains
            while not oracle.terminal(current) and current[0] != oracle.full_mask:
                actor = oracle.actor(current)
                chosen = oracle.search(current, actor, world[actor], belief)['action']
                belief = oracle.update(current, chosen, belief, ego)
                assert all(world[p] in belief[p] for p in range(oracle.spec.n_players))
                current = oracle.step(current, chosen)
            values[name].append(float(oracle.utilities[ego][own, current[0]]))
    return dict(seconds=time.perf_counter() - start, rewards=values,
                difference=difference_stats(values['teacher'], values['reference']),
                continuation='Actual frozen UCT for all future actors; exact finite-type belief updates; not the cheap search rollout model.')


def audit_planning(oracle, snapshot, game_id, position, eval_samples, actual_samples):
    start = time.perf_counter()
    node, domains, ego, own = (snapshot[k] for k in ('node', 'domains', 'ego', 'own'))
    main = oracle.search(node, ego, own, domains)
    doubled = oracle.search(node, ego, own, domains, budget=replace(oracle.budget, simulations=oracle.budget.simulations * 2))
    reseeded = oracle.search(node, ego, own, domains, budget=replace(oracle.budget, salt=17))
    prior = oracle.search(node, ego, own, oracle.prior)
    reference = oracle.reference(node, own, domains)
    actions = dict(teacher=main['action'], doubled=doubled['action'], reseeded=reseeded['action'],
                   prior_only=prior['action'], reference=reference)
    values = paired_reference_values(oracle, node, domains, ego, own, actions,
                                     eval_samples, (game_id, position, 'heldout'))
    means = {name: float(np.mean(v)) for name, v in values.items()}
    comparisons = {name: difference_stats(values['teacher'], values[name])
                   for name in actions if name != 'teacher'}
    stable = main['action'] == doubled['action'] == reseeded['action']
    positive_reference_gap = comparisons['reference']['approximate_95_interval'][0] > 0
    # A candidate filter, not an optimality certificate or training-effect result.
    suitable = stable and positive_reference_gap
    identifier = f'{game_id}/p{position}'
    payload = input_payload(oracle, node, domains, ego, own, snapshot['history'])
    payload['partner_judgment'] = [
        dict(player_id=p,
             possible_joint_preferences=[list(oracle.catalogues[p][t]) for t in domains[p]],
             goals=[dict(goal_id=g, possible_preferences=oracle.semantic_support(domains, p, g))
                    for g in range(oracle.spec.n_goals)])
        for p in range(oracle.spec.n_players) if p != ego]
    payload['instruction'] = 'Choose a native action to improve your expected terminal utility. Use the history and evidence-supported partner judgment. No probabilities, Q values, or plan variables are required.'
    sample = dict(id=identifier, task='P', input=payload,
                  answer=oracle.native_action(node, main['action']).to_dict(),
                  label_status='approximate_search_demonstration',
                  candidate_filter_passed=suitable)
    stats = dict(id=identifier, phase='proposal' if node[2] is None else 'response',
                 turn=node[1], history_decisions=len(snapshot['history']),
                 legal_actions=len(main['actions']), root_action_coverage=main['root_action_coverage'],
                 search_seconds=main['seconds'], doubled_seconds=doubled['seconds'],
                 reseeded_seconds=reseeded['seconds'],
                 actions={name: oracle.native_action(node, action).to_dict() for name, action in actions.items()},
                 budget_action_agreement=main['action'] == doubled['action'],
                 seed_action_agreement=main['action'] == reseeded['action'],
                 prior_only_action_differs=main['action'] != prior['action'],
                 prior_only_is_consistency_ablation_not_valid_demonstration=True,
                 heldout_reference_continuation_means=means,
                 paired_differences=comparisons,
                 candidate_filter_passed=suitable,
                 candidate_filter='Same native action at base/doubled budget and changed search seed; independent cheap-continuation paired lower 95% bound above immediate reference. Exploratory, no multiple-comparison correction and not an optimum certificate.',
                 actual_continuation=None)
    if actual_samples:
        stats['actual_continuation'] = actual_oracle_values(
            oracle, node, domains, ego, own,
            {'teacher': main['action'], 'reference': reference}, actual_samples,
            (game_id, position, 'actual-check'))
    stats['total_seconds'] = time.perf_counter() - start
    return sample, stats


def audit_game(seed, cell, profiles, budget, eval_samples, actual_samples, positions=4):
    start = time.perf_counter()
    spec, oracle, realized = make_game(seed, cell, profiles, budget)
    game_id = f'{cell}_s{seed}'
    learner = spec.round_robin[0]
    node, domains, history, records, b_samples, snapshots = (0, 0, None), oracle.prior, [], [], [], []
    native, pending = GameState(spec), None
    b_elapsed, semantic_reductions, informative_actions, goal_update_count = [], 0, 0, 0
    independent_worlds = [world for world in __import__('itertools').product(*oracle.prior)
                          if world[learner] == realized[learner]]
    initial_worlds = len(independent_worlds)
    # Independent explicit-world filtering cross-check; not used by the policy.
    while not oracle.terminal(node):
        actor = oracle.actor(node)
        if actor == learner and len(oracle.actions(node)) > 1:
            snapshots.append(dict(node=node, domains=domains, ego=learner, own=realized[learner], history=list(history)))
        before, before_node = domains, node
        decision = oracle.search(node, actor, realized[actor], domains)
        chosen = decision['action']
        t0 = time.perf_counter()
        domains = oracle.update(node, chosen, domains, learner)
        label_seconds = time.perf_counter() - t0
        if actor != learner:
            predicted = {t: oracle.search(node, actor, t, before)['action'] for t in before[actor]}
            independent_worlds = [w for w in independent_worlds if predicted[w[actor]] == chosen]
            for p in range(spec.n_players):
                if p != learner:
                    assert set(domains[p]) == {w[p] for w in independent_worlds}
            b_elapsed.append(label_seconds)
            informative_actions += len(domains[actor]) < len(before[actor])
        assert all(realized[p] in domains[p] for p in range(spec.n_players))
        action = oracle.native_action(node, chosen)
        # Validate enumeration/transition via independent native implementation.
        pending = apply(native, pending, action)
        node = oracle.step(node, chosen)
        native_mask = sum(int(native.commitments[p, a]) << (oracle.offsets[p] + a)
                          for p in range(spec.n_players) for a in range(spec.n_actions_per_player[p]))
        assert node[:2] == (native_mask, native.turn_index)
        assert (node[2] is None) == (pending is None)
        history.append(dict(player_id=actor, action=action.to_dict()))
        records.append(dict(turn=before_node[1], player_id=actor, action=action.to_dict(),
                            kind=kind(action), policy='frozen_uct', learner_action_is_intervention=actor == learner,
                            search_seconds=decision['seconds'], root_action_coverage=decision['root_action_coverage'],
                            label_seconds=label_seconds, before_domains=before, after_domains=domains))
        if actor != learner:
            changed, unchanged = [], []
            for goal in range(spec.n_goals):
                old, new = oracle.semantic_support(before, actor, goal), oracle.semantic_support(domains, actor, goal)
                (changed if old != new else unchanged).append(goal)
                semantic_reductions += len(old) - len(new)
                goal_update_count += 1
                assert LABEL_FOR(spec.private_preferences[actor, goal]) in new
            # At most 2 changed and 1 unchanged queries per observed action;
            # export both before and after to teach updates and non-updates.
            selected = changed[:2] + unchanged[:1]
            for goal in selected:
                for when, at_node, at_domains, at_history in (
                    ('before', before_node, before, history[:-1]),
                    ('after', node, domains, history),
                ):
                    payload = input_payload(oracle, at_node, at_domains, learner, realized[learner], at_history)
                    payload.update(query=dict(player_id=actor, goal_id=goal),
                                   instruction='Report every preference still possible given this history and the declared partner policy. Do not guess the realized hidden preference. Learner actions do not eliminate types.')
                    b_samples.append(dict(id=f'{game_id}/b{len(records)-1}/g{goal}/{when}', task='B',
                        input=payload, answer=dict(possible_preferences=oracle.semantic_support(at_domains, actor, goal)),
                        label_status='exact_support_under_declared_finite_prior_and_policy',
                        source_event=len(records)-1, update_kind='shrinks' if goal in changed else 'unchanged'))
    assert native.is_terminal and native.terminal_rewards().tolist() == [int(oracle.utilities[p][realized[p], node[0]]) for p in range(spec.n_players)]
    rollout_seconds = time.perf_counter() - start
    selected = sorted(set(np.linspace(0, len(snapshots)-1, min(positions, len(snapshots)), dtype=int))) if snapshots else []
    p_samples, p_stats = [], []
    for position, index in enumerate(selected):
        sample, stats = audit_planning(oracle, snapshots[index], game_id, position, eval_samples,
                                      actual_samples if position == 0 else 0)
        p_samples.append(sample)
        p_stats.append(stats)
    result = dict(id=game_id, cell=cell, seed=seed, learner=learner, spec=spec.to_dict(include_private=True),
                  public_catalogues=oracle.catalogues, realized_types=realized,
                  prior_scope='Independent finite row catalogues, cyclic ternary triplets; goal preferences correlated within a player. Not the native full private prior.',
                  initial_hidden_worlds_given_own=initial_worlds,
                  final_hidden_worlds_given_own=len(independent_worlds),
                  native_replay_verified=True, independent_joint_support_verified=True,
                  terminal_rewards=native.terminal_rewards().tolist(),
                  terminal_commitments=native.public_state()['commitments'],
                  satisfied_goals=int(native.goal_satisfaction().sum()),
                  decisions=records, planning_audit=p_stats,
                  stats=dict(rollout_seconds=rollout_seconds, total_seconds=time.perf_counter()-start,
                             b_label_total_seconds=sum(b_elapsed), b_label_calls=len(b_elapsed),
                             b_label_max_seconds=max(b_elapsed, default=0),
                             b_samples=len(b_samples), p_samples=len(p_samples),
                             informative_oracle_actions=informative_actions,
                             goal_update_checks=goal_update_count, eliminated_semantic_possibilities=semantic_reductions,
                             oracle_search_calls=oracle.search_calls, oracle_search_seconds=oracle.search_seconds,
                             action_counts=dict(Counter(r['kind'] for r in records))))
    oracle.clear_caches()
    return result, b_samples, p_samples


def LABEL_FOR(value):
    return {1: 'want', 0: 'neutral', -1: 'avoid'}[int(value)]


def summarize(games, b_samples, p_samples):
    ps = [p for g in games for p in g['planning_audit']]
    checked = [p['actual_continuation'] for p in ps if p['actual_continuation']]
    return dict(version=VERSION, games=len(games), b_samples=len(b_samples), p_samples=len(p_samples),
                native_replay_passed=all(g['native_replay_verified'] for g in games),
                independent_joint_support_passed=all(g['independent_joint_support_verified'] for g in games),
                b_support_size_counts=dict(Counter(len(b['answer']['possible_preferences']) for b in b_samples)),
                b_update_pair_counts=dict(Counter(b['update_kind'] for b in b_samples if b['id'].endswith('/after'))),
                p_budget_agreements=sum(p['budget_action_agreement'] for p in ps),
                p_seed_agreements=sum(p['seed_action_agreement'] for p in ps),
                p_prior_only_action_changes=sum(p['prior_only_action_differs'] for p in ps),
                p_candidate_filter_passed=sum(p['candidate_filter_passed'] for p in ps),
                p_phase_counts=dict(Counter(p['phase'] for p in ps)),
                p_root_action_coverage_min=min((p['root_action_coverage'] for p in ps), default=None),
                actual_continuation_checks=len(checked),
                actual_continuation_mean_gaps=[c['difference']['mean'] for c in checked],
                actual_continuation_seconds=sum(c['seconds'] for c in checked),
                total_seconds=sum(g['stats']['total_seconds'] for g in games),
                per_game=[dict(id=g['id'], **g['stats']) for g in games])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('new/local_data/mcts_bp_audit_v1'))
    parser.add_argument('--games-per-cell', type=int, default=2)
    parser.add_argument('--seed', type=int, default=62000)
    parser.add_argument('--profiles', type=int, default=6)
    parser.add_argument('--simulations', type=int, default=1024)
    parser.add_argument('--eval-samples', type=int, default=256)
    parser.add_argument('--actual-samples', type=int, default=8)
    parser.add_argument('--positions', type=int, default=4)
    args = parser.parse_args(argv)
    if min(args.games_per_cell, args.eval_samples, args.positions) < 1 or args.actual_samples < 0:
        parser.error('Invalid audit counts')
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh directory; previous runs are immutable.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sources = ['mcts_oracle.py', 'mcts_bp_audit.py', 'state.py', 'schema.py', 'generator.py', 'private_game_pilot.py']
    manifest = dict(version=VERSION, configuration={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                    source_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources},
                    scope='Development B/P data audit; no LLM inference, training, or transfer evaluation. B exact only relative to the declared restricted prior and policy; P approximate.',
                    splits='Development only. No train/test claim. Future splits must group by source game.',
                    policy_budget=asdict(Budget(simulations=args.simulations)))
    write_json(args.output_dir / 'manifest.json', manifest)
    games, bs, ps = [], [], []
    for cell in CELLS:
        for offset in range(args.games_per_cell):
            print(f'START {cell} seed={args.seed+offset}', flush=True)
            game, b, p = audit_game(args.seed+offset, cell, args.profiles, Budget(simulations=args.simulations),
                                     args.eval_samples, args.actual_samples, args.positions)
            games.append(game); bs.extend(b); ps.extend(p)
            write_json(args.output_dir / 'games' / f'{game["id"]}.json', game)
            write_jsonl(args.output_dir / 'b_samples.jsonl', bs)
            write_jsonl(args.output_dir / 'p_candidates.jsonl', ps)
            write_json(args.output_dir / 'summary.json', summarize(games, bs, ps))
            print(json.dumps(dict(game=game['id'], **game['stats'])), flush=True)
    files = sorted(p for p in args.output_dir.rglob('*') if p.is_file())
    write_json(args.output_dir / 'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    print(json.dumps(summarize(games, bs, ps)), flush=True)


if __name__ == '__main__':
    main()
