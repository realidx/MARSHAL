"""Small native-game solver comparison; no dataset mutation or relaxed acceptance.

Run in the optional isolated PyGambit environment.  Gambit 16.4.1's dense
sequence-form tableau is guarded BEFORE allocation; skips are not timeouts.
"""
import argparse
from contextlib import contextmanager
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import file_hash, write_json, save_reference
import training.strategic_slices.equilibrium as eq


def dimensions(tree):
    cells = [sum(len(g) for i, g in tree.information_groups.items()
                 if tree.entries[i].actor == p) for p in range(tree.n)]
    sequences = [1 + sum(len(g) * len(tree.entries[i].actions)
                         for i, g in tree.information_groups.items()
                         if tree.entries[i].actor == p) for p in range(tree.n)]
    d = sum(cells) + tree.n + sum(sequences)
    return dict(information_sets=cells, sequences=sequences, tableau_dimension=d,
                single_double_matrix_bytes=8*d*(d+1),
                note='Gambit 16.4.1 efglcp.cc: ntot=ns1+ns2+ni1+ni2; one dense matrix only, not peak memory')


def export_efg(tree, path):
    """Duplicate native histories by world; share exactly original information cells."""
    if tree.n != 2 or tree.cutoff_leaves:
        raise ValueError('Requires a complete native two-player tree')
    mapping = {}; ids_by_world = {}; counters = [0, 0]
    for i, groups in tree.information_groups.items():
        player = tree.entries[i].actor
        ids_by_world[i] = np.zeros(tree.w, dtype=int)
        for cell, ids in enumerate(groups):
            counters[player] += 1
            mapping[(i, cell)] = counters[player]
            ids_by_world[i][ids] = counters[player]
    prior = [Fraction(float(w)).limit_denominator(10**12) for w in tree.world_weights]
    total = sum(prior); prior = [p/total for p in prior]
    assert np.allclose([float(p) for p in prior], tree.world_weights, atol=1e-12, rtol=0)
    outcomes = {}; count = 0
    with path.open('w') as f:
        f.write('EFG 2 R "Native terminal comparison" { "P0" "P1" }\n')
        f.write('c "world" 1 "" { ' + ' '.join(f'"w{w}" {p}' for w,p in enumerate(prior)) + ' } 0\n')
        for wi in range(tree.w):
            for i, entry in enumerate(tree.entries):
                count += 1
                if entry.actor is None:
                    payoff = tuple(float(v) for v in entry.payoff[wi])
                    if payoff not in outcomes: outcomes[payoff] = len(outcomes)+1
                    numbers = ' '.join(str(Fraction(v).limit_denominator(10**12)) for v in payoff)
                    f.write(f't "{i}" {outcomes[payoff]} "" {{ {numbers} }}\n')
                else:
                    actions = ' '.join(f'"a{a}"' for a in range(len(entry.actions)))
                    cell = ids_by_world[i][wi]
                    f.write(f'p "{i}" {entry.actor+1} {cell} "i{i}c{cell}" {{ {actions} }} 0\n')
    return mapping, dict(exported_nodes=count+1, distinct_outcomes=len(outcomes), efg_bytes=path.stat().st_size)


def validate_encoding(tree, game):
    """Independent readback of chance, all edges/payoffs, and information partitions."""
    assert game.is_perfect_recall
    assert len(game.root.children) == tree.w
    seen = {}; nodes = leaves = 0
    for wi, root in enumerate(game.root.children):
        assert abs(float(game.root.infoset.actions[wi].prob)-tree.world_weights[wi]) < 1e-12
        stack = [(0, root)]
        while stack:
            i, node = stack.pop(); entry = tree.entries[i]; nodes += 1
            assert node.label == str(i)
            if entry.actor is None:
                leaves += 1
                np.testing.assert_allclose([float(node.outcome[p]) for p in game.players], entry.payoff[wi], atol=1e-12, rtol=0)
                assert len(node.children) == 0
            else:
                assert node.player.number == entry.actor
                assert len(node.children) == len(entry.actions)
                assert [a.label for a in node.infoset.actions] == [f'a{a}' for a in range(len(entry.actions))]
                seen[(i, wi)] = node.infoset
                stack.extend(zip(entry.children, node.children))
    for i, groups in tree.information_groups.items():
        representatives = []
        for ids in groups:
            representative = seen[(i, int(ids[0]))]
            assert all(seen[(i, int(w))] == representative for w in ids)
            assert representative not in representatives
            assert len(representative.members) == len(ids)
            representatives.append(representative)
    return dict(nodes_checked=nodes+1, terminal_world_payoffs_checked=leaves, perfect_recall=True)


def import_profile(tree, game, profile):
    lookup = {info.label: info for player in game.players for info in player.infosets}
    counters = [0, 0]
    for i, groups in tree.information_groups.items():
        p = tree.entries[i].actor
        for ids in groups:
            counters[p] += 1
            info = lookup[f'i{i}c{counters[p]}']
            probabilities = np.array([float(profile[a]) for a in info.actions])
            tree.policy[i][:, ids] = probabilities[:, None]


def worker(a):
    out = a.output; out.mkdir(parents=True, exist_ok=True)
    result = dict(backend=a.backend, raw=str(a.raw), raw_sha256=file_hash(a.raw),
                  budget_seconds=a.budget, large_tree_ordered_sweeps=a.ordered_sweeps,
                  status='started', timings={}, D_run=False)
    start = time.monotonic(); result_path=out/'result.json'
    def checkpoint():
        result['elapsed_seconds'] = time.monotonic()-start
        write_json(result_path, result)
    @contextmanager
    def phase(name):
        result['phase'] = name; checkpoint(); t = time.monotonic()
        try: yield
        finally:
            result['timings'][name] = time.monotonic()-t; checkpoint()
    original = eq.certify_policy
    stats = dict(seconds=0., calls=0)
    def timed_certify(*args, **kwargs):
        t = time.monotonic()
        try: return original(*args, **kwargs)
        finally: stats['seconds'] += time.monotonic()-t; stats['calls'] += 1
    try:
        raw = json.loads(a.raw.read_text()); rules = PrivateInvestigationRules(raw)
        with phase('construction'):
            tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                world_weights=world_weights(rules.worlds, raw['background_prior']),
                lookahead_rr=3, max_nodes=160000, seconds=a.budget,
                large_tree_ordered_sweeps=a.ordered_sweeps)
        assert tree.n == 2 and not tree.cutoff_leaves
        result.update(nodes=len(tree.entries), worlds=tree.w,
                      proposal_schedule=list(rules.spec.round_robin), dimensions=dimensions(tree))
        if a.backend == 'current':
            eq.certify_policy = timed_certify
            with phase('solve_including_certification'): tree.solve()
            result['status'] = 'certified'
        else:
            import pygambit as gbt
            result['pygambit_version'] = gbt.__version__
            if result['dimensions']['tableau_dimension'] > a.max_dimension:
                result.update(status='dense_matrix_preflight_skip', max_tableau_dimension=a.max_dimension)
                return
            with phase('export'):
                _, metadata = export_efg(tree, out/'game.efg'); result.update(metadata)
            with phase('gambit_read'):
                game = gbt.read_efg(out/'game.efg')
            with phase('encoding_validation'):
                result['encoding_validation'] = validate_encoding(tree, game)
            with phase('lcp_search'):
                solved = gbt.nash.lcp_solve(game, rational=False, use_strategic=False, stop_after=1)
            result['returned_profiles'] = len(solved.equilibria)
            if not solved.equilibria:
                result['status'] = 'no_profile'; return
            with phase('profile_import'):
                import_profile(tree, game, solved.equilibria[0])
            # Independent certification has a separate explicit budget for both methods.
            tree.deadline = time.monotonic()+a.budget
            with phase('independent_certification'):
                accepted = original(tree)
            result['equilibrium_audit'] = tree.equilibrium_audit
            result['status'] = 'certified' if accepted else 'uncertified_reference'
            save_reference(out/'candidate.npz', tree)
            tree.values = tree.evaluate()
            if accepted: tree.certificate = accepted['certificate']
        tree.deadline = time.monotonic()+a.budget
        with phase('native_audit'): result['native_audit'] = tree.audit_native()
        if result['status'] == 'certified':
            result['certificate'] = tree.certificate
            save_reference(out/'reference.npz', tree)
    except Exception as exc:
        from examples.strategic_slices.retry_terminal_budgets import classify
        result.update(status=classify(str(exc)), reason=str(exc))
        traceback.print_exc()
    finally:
        eq.certify_policy = original
        result['current_internal_certification'] = stats
        if a.backend == 'current' and 'solve_including_certification' in result['timings']:
            result['timings']['search_and_wrapper_excluding_certification'] = result['timings']['solve_including_certification']-stats['seconds']
        checkpoint()
    print(result['status'], result['timings'], flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--backend', choices=['current', 'gambit'], required=True)
    p.add_argument('--budget', type=int, default=30)
    p.add_argument('--max-dimension', type=int, default=2500)
    p.add_argument('--ordered-sweeps', type=int, default=2)
    p.add_argument('--worker', action='store_true')
    a=p.parse_args()
    if a.worker: worker(a); return
    a.output.mkdir(parents=True, exist_ok=True)
    with (a.output/'worker.log').open('w') as log:
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-m', 'examples.strategic_slices.compare_sequence_solver',
                            *sys.argv[1:], '--worker'], stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1'))
            began = time.monotonic(); search_began = None
            while process.poll() is None:
                now = time.monotonic(); path = a.output/'result.json'
                try: progress = json.loads(path.read_text())
                except (FileNotFoundError, json.JSONDecodeError): progress = {}
                if progress.get('phase') == 'lcp_search':
                    if search_began is None: search_began = now
                    if now-search_began > a.budget:
                        raise subprocess.TimeoutExpired(process.args, a.budget)
                else: search_began = None
                if now-began > 2*a.budget+30:
                    raise subprocess.TimeoutExpired(process.args, 2*a.budget+30)
                time.sleep(.1)
            if process.returncode: raise subprocess.CalledProcessError(process.returncode, process.args)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            if process is not None and process.poll() is None:
                process.kill(); process.wait()
            path=a.output/'result.json'
            r=json.loads(path.read_text()) if path.exists() else {}
            r.update(status='hard_timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'worker_error',reason=str(exc))
            if isinstance(exc, subprocess.TimeoutExpired):
                r['hard_limit_seconds'] = exc.timeout
                r['elapsed_seconds'] = time.monotonic()-began
                if search_began is not None:
                    r['timings']['lcp_search_until_killed'] = time.monotonic()-search_began
            write_json(path,r)
    print(a.output, json.loads((a.output/'result.json').read_text())['status'], flush=True)


if __name__ == '__main__': main()
