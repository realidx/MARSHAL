"""Paired, model-independent diagnostics for an all-player RR cutoff oracle.

This is an oracle experiment, not a training dataset or a training reward
recipe. Every search leaf scores the commitments already made there. There
is no fixed-myopic opponent, terminal rollout or hidden fallback solver.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import time

import numpy as np

from training.b_sft.preference_contract import world_weights
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_private_teacher import PrivateInvestigationRules, observed_slots
from .bounded import BoundedPrivateWindow, LEAF_OBJECTIVE, VERSION, resolve_horizon
from .bounded_cache import BoundedProblemCache
from .build import cap_slices, entrances, measure_entrance, sample_parent
from .common import digest, stable, write_json


THRESHOLDS = (0., .01, .05, .1)
NUMERIC_TOL = 1e-9


def uniform_prefix(rules, seed, completed_rr=1):
    """Reach a public RR boundary using legal, world-independent actions.

    The random policy selects a native legal action uniformly, including
    OFFER responses and INVESTIGATE. No realized preference world is sampled
    or supplied. Since legality is public and the policy ignores private
    information, the likelihood of this prefix is constant across worlds;
    its public posterior is exactly the source prior. Query answers are still
    part of each investigator's information partition in the later solve.
    """
    if type(completed_rr) is not int or completed_rr < 0:
        raise ValueError('completed_rr must be a nonnegative integer')
    rng = np.random.default_rng(seed)
    node = rules.initial()
    end = min(rules.spec.n_players * completed_rr, len(rules.spec.round_robin))
    history, prefix = [], []
    likelihood = 1.
    while rules.actor(node) is not None and (node.state.turn_index < end or node.pending is not None):
        actions = rules.actions(node)
        index = int(rng.integers(len(actions)))
        likelihood /= len(actions)
        history.append(index)
        prefix.append(actions[index].to_dict())
        node = rules._apply(node, actions[index])
    if node.pending is not None:
        raise AssertionError('Uniform prefix left an unfinished offer')
    return node, dict(history=history, actions=prefix, completed_proposal_turns=node.state.turn_index,
                      completed_rr=node.state.turn_index / rules.spec.n_players,
                      generation_policy='Uniform over native legal actions, independent of every private type and query answer',
                      world_independent_public_likelihood=likelihood,
                      public_posterior_equals_source_prior=True)


def count_bounded_nodes(rules, root, lookahead_rr, horizon_mode='rr-plus-next-own-proposal-v1'):
    """Count exact unfolded history nodes without constructing a strategy tree.

    Memoization identifies physical states ONLY to count how many histories
    their identical legal successors generate. Every parent sums the whole
    successor count, so transpositions are counted again in the unfolded
    history tree. No beliefs, information sets, payoffs or strategies are
    merged or reused by the actual solver.
    """
    horizon = resolve_horizon(rules, root, lookahead_rr, horizon_mode)
    cutoff = horizon['cutoff']
    memo = {}

    def count(node):
        key = (node.state.turn_index, node.state.snapshot_commitments(), node.pending,
               node.state.investigation_used)
        if key not in memo:
            leaf = node.state.is_terminal or (node.state.turn_index >= cutoff and node.pending is None)
            memo[key] = 1 if leaf else 1 + sum(count(rules._apply(node, action))
                                              for action in rules.actions(node))
        return memo[key]

    return dict(unfolded_public_history_nodes=count(root),
                physical_states_used_only_for_counting=len(memo), **horizon,
                strategy_transpositions_merged=False)


def root_entrances(tree):
    """Exhaust every information cell of the actual actor at the search root."""
    entry = tree.entries[0]
    if entry.actor is None:
        return []
    ego = entry.actor
    rows = []
    for ids in tree.information_groups[0]:
        weights = np.zeros(tree.w)
        weights[ids] = tree.world_weights[ids]
        weights /= weights.sum()
        world = tree.worlds[int(ids[0])]
        facts = [(p, g, world[p][g]) for p, g in observed_slots(entry.node, ego)]
        rows.append(dict(root_index=0, ego=ego, own=list(world[ego]), private_results=facts,
                         history=[], entry_world_weights=weights.tolist(), exhaustive_root_cell=True))
    return rows


def metric_entrances(tree, seed, config):
    """Measure exhaustive root cells plus a bounded sample of reachable cells."""
    sampled = ([] if config['max_entrances'] == 0 else
               entrances(tree, seed, config['entrance_trajectories'], config['reach_epsilon']))
    roots = root_entrances(tree)
    seen = {digest((e['root_index'], e['own'], e['private_results'])) for e in roots}
    additional = []
    for entrance in sampled:
        key = digest((entrance['root_index'], entrance['own'], entrance['private_results']))
        if key not in seen:
            seen.add(key)
            additional.append(entrance)
        if len(additional) >= config['max_entrances']:
            break
    cells = roots + additional
    for entrance in cells:
        node = tree.entries[entrance['root_index']].node
        fresh = resolve_horizon(tree.rules, node, tree.lookahead_rr, tree.horizon_mode)
        next_own = fresh['next_own_proposal_index']
        entrance.update(absolute_cutoff=tree.cutoff,
                        remaining_proposal_turns=tree.cutoff - node.state.turn_index,
                        fresh_entrance_cutoff=fresh['cutoff'],
                        next_own_proposal_index=next_own,
                        next_own_proposal_included=next_own is not None and next_own < tree.cutoff,
                        shares_original_root_cutoff=True,
                        evaluation_scope=('Certified original search-root information cell'
                                          if entrance['root_index'] == 0 else
                                          'Internal entrance evaluated under original root profile and cutoff; not independently replanned'))
    return cells, dict(exhaustive_root_cells=len(roots),
                       sampled_reachable_cells=len(sampled),
                       measured_sampled_cells=len(additional),
                       internal_entrances_are_independently_replanned=False)


def classify_failure(exc):
    if isinstance(exc, ValueError):
        return 'invalid_problem'
    message = str(exc).lower()
    if 'node budget' in message:
        return 'node_budget'
    if 'wall budget' in message or 'time' in message:
        return 'time_budget'
    if 'cycled' in message or 'cycle' in message:
        return 'policy_cycle'
    if 'sweep budget' in message or 'did not converge' in message:
        return 'sweep_budget'
    return 'certification_failed'


def measure_case(raw, phase, root, prefix, lookahead_rr, seed, config, cache=None):
    """Solve one paired case; failures return no invented oracle metrics."""
    started = time.monotonic()
    rules = PrivateInvestigationRules(raw)
    prior = world_weights(rules.worlds, raw['background_prior'])
    row = dict(seed=seed, players=rules.spec.n_players,
               parent_rounds=len(rules.spec.round_robin) // rules.spec.n_players,
               phase=phase, lookahead_rr=lookahead_rr, parent_id=digest(raw)[:24], raw=raw,
               prefix=prefix, root_public_state=root.state.public_state(),
               root_pending_offer=None if root.pending is None else root.pending.to_dict(),
               source_worlds=rules.worlds, global_world_prior=prior.tolist(),
               diagnostic_only=True, training_reward_unspecified=True,
               reference_backend=VERSION, leaf_objective=LEAF_OBJECTIVE,
               all_player_same_solver=True, full_enumeration=True,
               horizon_mode=config.get('horizon_mode', 'rr-plus-next-own-proposal-v1'),
               solver_mode=config.get('solver_mode', 'equilibrium'),
               equilibrium_epsilon=config.get('epsilon', 1e-8),
               source_all_players_participate=len({a['player_id'] for g in raw['game']['goals']
                                                  for a in g['required_actions']}) == rules.spec.n_players,
               certificate=None)
    stage = 'count'
    tree = None
    try:
        stamp = time.monotonic()
        row.update(count_bounded_nodes(rules, root, lookahead_rr, row['horizon_mode']))
        row['count_seconds'] = time.monotonic() - stamp
        if row['unfolded_public_history_nodes'] > config['max_nodes']:
            row.update(status='unavailable', failure_stage='preflight', failure_kind='node_budget',
                       reason='Exact unfolded public-history count exceeds the configured node budget; strategy tree was not constructed',
                       strategy_tree_constructed=False)
            return row
        stage = 'build'
        stamp = time.monotonic()
        row['strategy_tree_constructed'] = True
        solver_kwargs = dict(lookahead_rr=lookahead_rr, horizon_mode=row['horizon_mode'],
                             solver_mode=row['solver_mode'], epsilon=row['equilibrium_epsilon'],
                             max_nodes=config['max_nodes'], seconds=config['solver_seconds'],
                             max_sweeps=config['max_sweeps'], max_candidates=config.get('max_candidates', 6))
        cache = BoundedProblemCache() if cache is None else cache
        stage = 'solve'
        result = cache.solve(rules, root, rules.worlds, world_weights=prior, raw=raw, **solver_kwargs)
        tree = result.tree
        row.update(build_seconds=result.build_seconds, solve_seconds=result.solve_seconds,
                   cache=result.evidence(), nodes=len(tree.entries),
                   strategy_tree_constructed=True)
        if row['nodes'] != row['unfolded_public_history_nodes']:
            raise AssertionError('Exact counting and complete enumeration disagree')
        if tree.certificate is None or not tree.certificate.get('verified'):
            raise AssertionError('Solver returned without a verified certificate')
        row['certificate'] = tree.certificate
        if config.get('cache_replay', False) and result.answer_stored:
            replay = cache.solve(rules, root, rules.worlds, world_weights=prior, raw=raw, **solver_kwargs)
            if not replay.cache_hit or replay.tree.reference_identity() != tree.reference_identity():
                raise AssertionError('An exact replay failed certified-problem identity')
            row['cache_replay'] = replay.evidence()
        elif config.get('cache_replay', False):
            row['cache_replay_skipped'] = 'Certified problem exceeded bounded cache storage limits'
        stage = 'audit'
        stamp = time.monotonic()
        row['native_audit'] = tree.audit_native()
        row['audit_seconds'] = time.monotonic() - stamp
        stage = 'metrics'
        stamp = time.monotonic()
        cells, sampling = metric_entrances(tree, seed, config)
        all_retained, metrics = [], []
        for entrance in cells:
            retained, curves = measure_entrance(tree, entrance, row['parent_id'], config)
            all_retained.extend(retained)
            metrics.append(dict(entrance=entrance, length_curve=curves,
                                max_C_span=max(c['C_span'] for c in curves),
                                retained_slice_count=len(retained)))
        spans = [m['max_C_span'] for m in metrics]
        all_info = [v for retained in all_retained for v in retained['information_values']]
        row.update(status='measured', sampling=sampling, entrances=metrics,
                   retained_slices=all_retained, selected_slices=cap_slices(all_retained, config),
                   retained=len(all_retained), measured_entrances=len(metrics),
                   exact_zero_C_entrances=sum(abs(s) <= NUMERIC_TOL for s in spans),
                   max_C_span=max(spans, default=0.),
                   above_threshold={str(t): sum(s > max(t, NUMERIC_TOL) for s in spans) for t in THRESHOLDS},
                   root_above_threshold={str(t): sum(m['max_C_span'] > max(t, NUMERIC_TOL)
                                                     for m in metrics if m['entrance'].get('exhaustive_root_cell'))
                                         for t in THRESHOLDS},
                   max_private_S=max((v['S'] for v in all_info), default=0.),
                   max_S_given_query=max((v['S_given_query'] for v in all_info), default=0.),
                   private_information_query_measurements=len(all_info),
                   metrics_seconds=time.monotonic() - stamp)
    except (SearchLimit, ValueError) as exc:
        stage = getattr(exc, 'bounded_cache_failure_stage', stage)
        row.update(status='unavailable', failure_stage=stage, failure_kind=classify_failure(exc), reason=str(exc))
        if getattr(exc, 'bounded_candidate_audit', None) is not None:
            row['failed_candidate_audit'] = exc.bounded_candidate_audit
        row.setdefault(stage + '_seconds', time.monotonic() - stamp)
        if tree is not None:
            row['nodes'] = len(tree.entries)
        # Only successful solve-and-certify can set this field. In particular,
        # a timed-out/cycling profile is never copied as an oracle certificate.
        if stage in ('count', 'build', 'solve'):
            row['certificate'] = None
    finally:
        row['seconds'] = time.monotonic() - started
    return row


def summarize(rows, config):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['players'], row['lookahead_rr'], row['phase'])].append(row)
    summary = dict(diagnostic_only=True, training_reward_unspecified=True,
                   reference_backend=VERSION, leaf_objective=LEAF_OBJECTIVE,
                   all_player_same_solver=True, config=config, total_cases=len(rows), groups=[])
    for (n, rr, phase), cases in sorted(groups.items()):
        measured = [r for r in cases if r['status'] == 'measured']
        certified = [r for r in cases if r['certificate'] is not None]
        query_measured = [r for r in measured if r['private_information_query_measurements'] > 0]
        summary['groups'].append(dict(
            players=n, lookahead_rr=rr, proposal_turns=n * rr, phase=phase,
            horizon_mode=config.get('horizon_mode', 'rr-plus-next-own-proposal-v1'),
            actual_proposal_turns_min=min(r.get('actual_proposal_turns', 0) for r in cases),
            actual_proposal_turns_max=max(r.get('actual_proposal_turns', 0) for r in cases),
            attempted_parents=len(cases), certified_parents=len(certified), measured_parents=len(measured),
            unavailable_by_kind=dict(Counter(r['failure_kind'] for r in cases if r['status'] != 'measured')),
            unavailable_by_stage=dict(Counter(r['failure_stage'] for r in cases if r['status'] != 'measured')),
            accepted_signal_parent_denominator=len(measured),
            parents_with_retained_signal=sum(r['retained'] > 0 for r in measured),
            measured_entrance_denominator=sum(r['measured_entrances'] for r in measured),
            exact_zero_C_entrances=sum(r['exact_zero_C_entrances'] for r in measured),
            entrance_counts_above_threshold={str(t): sum(r['above_threshold'][str(t)] for r in measured)
                                             for t in THRESHOLDS},
            parents_above_C_threshold={str(t): sum(r['max_C_span'] > max(t, NUMERIC_TOL) for r in measured)
                                      for t in THRESHOLDS},
            private_S_parent_denominator=len(query_measured),
            parents_above_private_S_threshold={str(t): sum(r['max_private_S'] > max(t, NUMERIC_TOL)
                                                          for r in query_measured) for t in THRESHOLDS},
            parents_above_S_given_query_threshold={str(t): sum(r['max_S_given_query'] > max(t, NUMERIC_TOL)
                                                             for r in query_measured) for t in THRESHOLDS},
            exact_unfolded_nodes=sum(r.get('unfolded_public_history_nodes', 0) for r in cases),
            enumerated_nodes=sum(r.get('nodes', 0) for r in cases),
            seconds=sum(r['seconds'] for r in cases)))
    summary['interpretation'] = (
        'Failures have no C/S label and are excluded from signal denominators, but reported separately. '
        'C/S use cutoff commitment utility and the certified all-player selected profile in this truncated game. '
        'They are not full-original-game terminal values, model reward diversity or a chosen training reward. '
        'After-1-RR roots are reachable exogenous uniform-policy setups shared across depths, not trajectories '
        'claimed to have been generated by the selected oracle profile. '
        'Private S is measured only for consequential retained slices under the declared C/increment thresholds; '
        'zero when no such query was measured is not an exhaustive information-value claim.')
    return summary


def diagnose(output, seeds=12, seed=20261002, players=(2, 3), parent_rounds=3,
             lookahead_rr=(1,), solver_seconds=60, max_nodes=400000,
             max_sweeps=128, max_k=3, max_entrances=6, entrance_trajectories=6,
             reach_epsilon=.25, parent_factory=sample_parent,
             horizon_mode='rr-plus-next-own-proposal-v1', solver_mode='equilibrium',
             epsilon=1e-8, max_candidates=6, cache_replay=False):
    if (any(type(v) is not int or v < 1 for v in (seeds, parent_rounds, max_nodes, max_sweeps,
                                                max_k, entrance_trajectories, max_candidates))
            or type(max_entrances) is not int or max_entrances < 0
            or parent_rounds < 2 or not players or any(n not in (2, 3) for n in players)
            or not lookahead_rr or any(type(r) is not int or r < 1 for r in lookahead_rr)
            or len(set(players)) != len(players) or len(set(lookahead_rr)) != len(lookahead_rr)
            or not np.isfinite(solver_seconds) or solver_seconds <= 0
            or not np.isfinite(reach_epsilon) or not 0 < reach_epsilon <= 1
            or horizon_mode not in ('rr', 'rr-plus-next-own-proposal-v1')
            or solver_mode not in ('synchronous', 'equilibrium')
            or not np.isfinite(epsilon) or epsilon <= 0 or max_candidates < 2
            or type(cache_replay) is not bool):
        raise ValueError('Positive budgets, 2/3 players, unique positive RR depths, parent_rounds >= 2 and 0 < epsilon <= 1 required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = dict(seeds=seeds, seed=seed, players=list(players), parent_rounds=parent_rounds,
                  lookahead_rr=list(lookahead_rr), solver_seconds=solver_seconds, max_nodes=max_nodes,
                  max_sweeps=max_sweeps, max_k=max_k, max_entrances=max_entrances,
                  entrance_trajectories=entrance_trajectories, reach_epsilon=reach_epsilon,
                  horizon_mode=horizon_mode, solver_mode=solver_mode, epsilon=epsilon,
                  max_candidates=max_candidates, cache_replay=cache_replay,
                  min_c=.1, min_increment=.05, min_s=.05, slices_per_parent=8)
    write_json(output / 'config.json', dict(config, diagnostic_only=True, training_reward_unspecified=True))
    rows = []
    cache = BoundedProblemCache()
    with (output / 'cases.jsonl').open('w') as handle:
        for candidate in range(seed, seed + seeds):
            for n in players:
                raw = parent_factory(candidate, n, parent_rounds)
                rules = PrivateInvestigationRules(raw)
                initial, no_prefix = uniform_prefix(rules, candidate, 0)
                later, prefix = uniform_prefix(rules, candidate, 1)
                for phase, root, reached in [('initial', initial, no_prefix), ('after_1rr', later, prefix)]:
                    for rr in lookahead_rr:
                        record = measure_case(raw, phase, root, reached, rr, candidate, config, cache)
                        rows.append(record)
                        handle.write(stable(record) + '\n')
                        handle.flush()
                        write_json(output / 'summary.json', summarize(rows, config))
                        print(f"seed={candidate} n={n} phase={phase} RR={rr} status={record['status']} "
                              f"kind={record.get('failure_kind', '-')} depth={record.get('actual_proposal_turns')} "
                              f"nodes={record.get('unfolded_public_history_nodes')} "
                              f"C={record.get('max_C_span')} seconds={record['seconds']:.3f}", flush=True)
    summary = summarize(rows, config)
    summary['cache'] = cache.stats()
    write_json(output / 'summary.json', summary)
    write_json(output / 'COMPLETE.json', dict(diagnostic_only=True, training_reward_unspecified=True,
                                             cases=len(rows), reference_backend=VERSION))
    return summary


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--seeds', type=int, default=12)
    cli.add_argument('--seed', type=int, default=20261002)
    cli.add_argument('--players', type=int, nargs='+', default=[2, 3])
    cli.add_argument('--parent-rounds', type=int, default=3)
    cli.add_argument('--lookahead-rr', type=int, nargs='+', default=[1])
    cli.add_argument('--solver-seconds', type=float, default=60)
    cli.add_argument('--max-nodes', '--maxnodes', type=int, default=400000)
    cli.add_argument('--max-sweeps', type=int, default=128)
    cli.add_argument('--max-k', type=int, default=3)
    cli.add_argument('--max-entrances', type=int, default=6)
    cli.add_argument('--entrance-trajectories', type=int, default=6)
    cli.add_argument('--reach-epsilon', type=float, default=.25)
    cli.add_argument('--horizon-mode', choices=['rr', 'rr-plus-next-own-proposal-v1'],
                     default='rr-plus-next-own-proposal-v1')
    cli.add_argument('--solver-mode', choices=['synchronous', 'equilibrium'], default='equilibrium')
    cli.add_argument('--epsilon', type=float, default=1e-8)
    cli.add_argument('--max-candidates', type=int, default=6)
    cli.add_argument('--cache-replay', action='store_true',
                     help='Repeat successful identical problems to measure certified-answer reuse; no extra C/S labels')
    args = vars(cli.parse_args())
    try:
        diagnose(**args)
    except ValueError as exc:
        cli.error(str(exc))


if __name__ == '__main__':
    main()
