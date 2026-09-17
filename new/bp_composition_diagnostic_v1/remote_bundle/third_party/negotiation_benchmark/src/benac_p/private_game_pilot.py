"""Development feasibility audit: full-private native games, NOT SFT labels.

Native rollouts use explicitly named sampling policies. Separate root-search
probes use a much narrower binary finite-profile prior, never the native prior.
All generated data defaults to a gitignored local directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import signal
import time

import numpy as np

from benac_p.endgame import Endgame, PartnerDecision, SearchLimit
from benac_p.endgame_partner import RationalPartner, immediate_reference
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.schema import MenuOffer, OfferProposal, PassProposal, response_actions
from benac_p.state import GameState
from benac_p.sft_data_audit import action_kind, choose_by_kind, decode_action, rng_for, write_json


VERSION = 'private-game-feasibility-v1'
CELLS = {
    'n3_k2_g8_r2': GeneratorConfig(n_players=3, actions_per_player=2, n_goals=8, n_rounds=2),
    'n4_k2_g8_r2': GeneratorConfig(n_players=4, actions_per_player=2, n_goals=8, n_rounds=2),
    'n4_k2_g12_r4': GeneratorConfig(n_players=4, actions_per_player=2, n_goals=12, n_rounds=4),
    'n4_k3_g16_r6': GeneratorConfig(n_players=4, actions_per_player=3, n_goals=16, n_rounds=6),
}


def decision_view(state, actor, own, pending=None):
    """Explicit information boundary, also used by the rollout policies."""
    return PartnerDecision(actor, state.public_state(), tuple(map(int, own)),
                           state.legal_proposals() if pending is None else response_actions(pending),
                           None if pending is None else pending.to_dict())


def apply(state, pending, action):
    if pending is not None:
        if action not in response_actions(pending):
            raise ValueError('Illegal response')
        state.resolve_offer(pending, action)
        return None
    if action not in state.legal_proposals():
        raise ValueError('Illegal proposal')
    if isinstance(action, PassProposal):
        state.apply_pass()
        return None
    return action.offer


def rollout(spec, policy, seed):
    state, pending, records = GameState(spec), None, []
    rng = rng_for(VERSION, seed, policy)
    while not state.is_terminal:
        actor = state.current_proposer() if pending is None else pending.partner_id
        view = decision_view(state, actor, spec.private_preferences[actor], pending)
        action = (choose_by_kind(view.legal_actions, rng) if policy == 'category_random'
                  else immediate_reference(view))
        before = state.snapshot_commitments()
        turn = state.turn_index
        pending = apply(state, pending, action)
        changed = before != state.snapshot_commitments()
        records.append(dict(turn=turn, actor=actor, action=action.to_dict(),
                            kind=action_kind(action), legal_actions=len(view.legal_actions),
                            commitments_changed=changed))
    # Independent replay of every explicit decision from the original zero state.
    replay, pending = GameState(spec), None
    for record in records:
        pending = apply(replay, pending, decode_action(record['action']))
    assert pending is None and replay.is_terminal
    assert replay.public_state() == state.public_state()
    changed_turns = [r['turn'] + 1 for r in records if r['commitments_changed']]
    last_change = max(changed_turns, default=0)
    return dict(policy=policy, policy_is_terminal_rational_oracle=False,
                history_replay_verified=True, decisions=records,
                terminal_commitments=state.public_state()['commitments'],
                terminal_rewards=state.terminal_rewards().tolist(),
                commitment_changing_decisions=len(changed_turns),
                last_commitment_change_turn=last_change,
                trailing_turns_without_commitment_change=len(spec.round_robin)-last_change,
                goals_satisfied=int(state.goal_satisfaction().sum()))


def structure(spec):
    mixed, degrees = 0, []
    for player, count in enumerate(spec.n_actions_per_player):
        for action in range(count):
            goals = [g.goal_id for g in spec.goals if any(
                a.player_id == player and a.action_id == action for a in g.required_actions)]
            degrees.append(len(goals))
            # A structural conflict opportunity, NOT a reachable strategic witness.
            mixed += sum(1 in spec.private_preferences[p, goals] and -1 in spec.private_preferences[p, goals]
                         for p in range(spec.n_players))
    return dict(initial_proposal_actions=len(GameState(spec).legal_proposals()),
                commitment_goal_degrees=degrees,
                mixed_sign_player_commitment_pairs=int(mixed),
                unconstrained_hidden_worlds_given_own=str(3 ** (spec.n_goals*(spec.n_players-1))),
                exact_native_prior_enumerated=False)


def binary_catalogues(spec, seed):
    """Auxiliary prior only: two complementary complete rows per player.

    All players and all goals are uncertain, but within-player goal values are
    deliberately correlated and neutral is absent. Do not export as native B/P
    supervision. Each row has a WANT; no possible world has an all-neutral goal.
    """
    rng = rng_for(VERSION, seed, 'binary-profile-probe')
    result = {}
    for player in range(spec.n_players):
        while True:
            row = tuple(rng.choice((-1, 1)) for _ in spec.goals)
            if 1 in row and -1 in row:
                break
        result[player] = (row, tuple(-v for v in row))
    return result


class ProbeTimeout(RuntimeError):
    pass


@contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise ProbeTimeout('Wall-clock budget exceeded; no action label emitted.')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def oracle_probe(spec, seed, visibility, task, seconds, max_nodes):
    types = binary_catalogues(spec, seed)
    ego = spec.round_robin[0]
    target = (ego + 1) % spec.n_players
    if visibility == 'only_target_private':
        types = {p: rows if p == target else (rows[0],) for p, rows in types.items()}
    own = types[ego][0]
    partner = RationalPartner(spec, types, learner=ego, max_nodes=max_nodes)
    start = time.monotonic()
    result = dict(visibility=visibility, task=task, ego=ego,
                  prior='auxiliary_binary_complementary_full_profiles_not_native_prior',
                  type_catalogues={str(p): rows for p, rows in types.items()},
                  hidden_worlds_given_own=int(np.prod([len(r) for p, r in types.items() if p != ego])),
                  status='pending', action_labels=None,
                  learner_actions_are_interventions=True)
    try:
        with deadline(seconds):
            if task == 'partner_root_action':
                chosen = partner(decision_view(GameState(spec), ego, own))
                result.update(status='exact_under_auxiliary_prior', action_labels=[chosen.to_dict()])
            else:
                search = Endgame(spec, ego, own, {p: r for p, r in types.items() if p != ego},
                                 partner, max_nodes=max_nodes, max_remaining_turns=len(spec.round_robin))
                q = search.q_values(search.initial())
                best = max(v for _, v in q)
                optimal = [a.to_dict() for a, v in q if best-v < 1e-9]
                result.update(status='exact_under_auxiliary_prior', action_labels=optimal,
                              legal_actions=len(q), all_actions_tied=len(optimal)==len(q),
                              action_value_range=best-min(v for _, v in q))
    except (ProbeTimeout, SearchLimit) as exc:
        result.update(status='timeout' if isinstance(exc, ProbeTimeout) else 'node_limit',
                      error=str(exc), action_labels=None)
    result['elapsed_seconds'] = time.monotonic()-start
    return result


def summarize(games):
    result = {}
    for cell in CELLS:
        selected = [g for g in games if g['cell'] == cell]
        if not selected:
            continue
        item = dict(games=len(selected), initial_proposal_actions=selected[0]['structure']['initial_proposal_actions'],
                    mean_mixed_sign_pairs=float(np.mean([g['structure']['mixed_sign_player_commitment_pairs'] for g in selected])),
                    policies={}, oracle_probes={})
        for policy in ('category_random', 'immediate_reference'):
            rows = [t for g in selected for t in g['rollouts'] if t['policy']==policy]
            item['policies'][policy] = dict(
                trajectories=len(rows), replay_verified=sum(t['history_replay_verified'] for t in rows),
                mean_commitment_changes=float(np.mean([t['commitment_changing_decisions'] for t in rows])),
                mean_trailing_unchanged_turns=float(np.mean([t['trailing_turns_without_commitment_change'] for t in rows])),
                action_counts=dict(Counter(r['kind'] for t in rows for r in t['decisions'])))
        for task in ('partner_root_action', 'ego_root_planning'):
            for visibility in ('only_target_private', 'all_private'):
                rows = [p for g in selected for p in g['oracle_probes'] if p['task']==task and p['visibility']==visibility]
                item['oracle_probes'][task+'/'+visibility] = dict(Counter(p['status'] for p in rows))
        result[cell] = item
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('new/local_data/private_game_pilot'))
    parser.add_argument('--games-per-cell', type=int, default=10)
    parser.add_argument('--probe-games-per-cell', type=int, default=2)
    parser.add_argument('--probe-seconds', type=float, default=2)
    parser.add_argument('--max-nodes', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=61000)
    args = parser.parse_args(argv)
    if args.games_per_cell < 1 or not 0 <= args.probe_games_per_cell <= args.games_per_cell or args.probe_seconds <= 0 or args.max_nodes < 1:
        parser.error('Invalid positive audit budgets.')
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh output directory; audit runs are immutable.')
    games = []
    manifest = dict(version=VERSION, seed=args.seed, games_per_cell=args.games_per_cell,
                    probe_games_per_cell=args.probe_games_per_cell, probe_seconds=args.probe_seconds,
                    max_nodes=args.max_nodes, cells={k: asdict(v) for k, v in CELLS.items()},
                    source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                   (Path(__file__).parent / f for f in ('private_game_pilot.py','sft_data_audit.py','endgame_diagnose.py','endgame.py','endgame_partner.py','generator.py','schema.py','state.py'))},
                    purpose='development_feasibility_only', model_calls=0, training_started=False,
                    native_prior='Original generator .4/.2/.4 draws with rejection constraints; not an unconditioned independent prior.',
                    native_rollouts='Own preferences only; no B or P labels. Random and immediate policies are not active terminal-rational partners.',
                    oracle_probe_prior='Separate independent per-player two-row complementary binary catalogues. Not native independent goal preferences.')
    write_json(args.output_dir/'manifest.json', manifest)
    for cell, config in CELLS.items():
        for index in range(args.games_per_cell):
            seed = args.seed + index
            spec = replace(generate_game(seed, config), menu_enabled=True)
            game = dict(cell=cell, seed=seed, split='development_only', source_spec=spec.to_dict(include_private=True),
                        structure=structure(spec),
                        rollouts=[rollout(spec, policy, seed) for policy in ('category_random','immediate_reference')],
                        oracle_probes=[])
            if index < args.probe_games_per_cell:
                for task in ('partner_root_action','ego_root_planning'):
                    for visibility in ('only_target_private','all_private'):
                        probe = oracle_probe(spec, seed, visibility, task, args.probe_seconds, args.max_nodes)
                        game['oracle_probes'].append(probe)
                        print(cell, seed, task, visibility, probe['status'], flush=True)
            write_json(args.output_dir/'games'/cell/f'{seed}.json', game)
            games.append(game)
    write_json(args.output_dir/'summary.json', summarize(games))
    write_json(args.output_dir/'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                                              for p in sorted(args.output_dir.rglob('*.json'))})
    print(f'Completed {len(games)} source configurations; no SFT labels or model results. {args.output_dir}', flush=True)


if __name__ == '__main__':
    main()
