"""Whole original pool: restore baseline, re-solve binding OFFER-quota games.

No new parents, no changed priors/queries/goals, no model calls or slice labels.
One-round references are reused under an explicit game-equivalence proof.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import gc
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import unittest

import numpy as np

from new.offer_budget_mechanism_20261021.research import (
    OfferQuotaRules, assert_factorized, contingent_values, audit_quota,
)
from training.b_sft.social_terminal_teacher import Investigate
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import certify_policy, solve_equilibrium
from training.strategic_slices.oracle_consistent import oracle_reach
from training.strategic_slices.pipeline_versions import registered_snapshot
from training.strategic_slices.terminal_candidates import restore_reference

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'original-100-offer-quota-terminal-study-v1'
TOL = 1e-8


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def write(p, obj):
    with p.open('x') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def source_defaults(function):
    return {k: v.default for k,v in inspect.signature(function).parameters.items()
            if v.default is not inspect.Parameter.empty}


def metrics(tree, analysis_seconds):
    """Same full-vector BR convention for both sides of the comparison."""
    reach, histories = oracle_reach(tree)
    rows = []
    for ego in range(tree.n):
        tree.deadline = time.monotonic() + analysis_seconds
        first = list(tree.rules.spec.round_robin).index(ego)
        full = contingent_values(tree, ego)
        prohibited = contingent_values(tree, ego, forbid_queries=True)
        _, oracle_br = tree.response(ego)
        np.testing.assert_allclose(full[0], oracle_br, atol=1e-9, rtol=0)
        masked = {}
        for i, masses in reach.items():
            entry = tree.entries[i]
            if (entry.actor != ego or entry.node.pending is not None
                    or entry.node.state.turn_index != first):
                continue
            qs = [a for a,x in enumerate(entry.actions) if isinstance(x, Investigate)]
            nonqs = [a for a in range(len(entry.actions)) if a not in qs]
            if not qs:
                raise AssertionError('Investigation should be unused at first proposal')
            for ids in tree.information_groups[i]:
                mass = float(masses[ids].sum())
                if mass <= 1e-10:
                    continue
                weights = np.zeros(tree.w)
                weights[ids] = masses[ids] / mass
                q = np.array([weights @ full[c][:,ego] for c in entry.children])
                nq = np.array([weights @ prohibited[c][:,ego] for c in entry.children])
                bestq, bestother = float(q[qs].max()), float(q[nonqs].max())
                value, noquery = float(q.max()), float(nq[nonqs].max())
                if noquery > value + TOL:
                    raise AssertionError('Prohibiting queries increased primary best-response value')
                if abs(value - float(weights @ tree.values[i][:,ego])) > TOL:
                    raise AssertionError('Reachable first proposal not optimal under reference')
                details = []
                for a in qs:
                    action = entry.actions[a]
                    slot = action.player, action.goal
                    support = sorted({tree.worlds[w][slot[0]][slot[1]]
                                      for w in np.flatnonzero(weights > 0)})
                    detail = dict(action_index=a,slot=list(slot),support=support,Q=float(q[a]))
                    if len(support)>1 and q[a]>=bestq-TOL:
                        if slot not in masked:
                            masked[slot] = contingent_values(tree,ego,masked_slot=slot)
                        masked_q = float(weights @ masked[slot][entry.children[a]][:,ego])
                        detail.update(masked_same_query_Q=masked_q,
                                      same_query_answer_value=float(q[a])-masked_q)
                    details.append(detail)
                actions = [x.to_dict() for x in entry.actions]
                offer_ids = [a for a,x in enumerate(actions) if x.get('action')=='OFFER']
                pass_ids = [a for a,x in enumerate(actions) if x.get('action')=='PASS']
                rows.append(dict(player=ego,root_index=i,history=histories[i],
                    own=list(tree.worlds[int(ids[0])][ego]),reach_mass=mass,
                    actions=actions,Q=q.tolist(),V_full=value,V_no_own_queries=noquery,
                    query_access_value=value-noquery,first_query_gap=bestq-bestother,
                    best_query_Q=bestq,best_nonquery_Q=bestother,
                    best_offer_Q=float(q[offer_ids].max()) if offer_ids else None,
                    PASS_Q=float(q[pass_ids[0]]) if pass_ids else None,
                    query_probability=float(sum(weights @ tree.policy[i][a] for a in qs)),
                    query_details=details))
        del full, prohibited, oracle_br, masked
        gc.collect()
    per_player = []
    for p in range(tree.n):
        cells = [r for r in rows if r['player']==p]
        mass = sum(r['reach_mass'] for r in cells)
        if abs(mass-1)>1e-8:
            raise AssertionError('First-proposal information cells do not have total reach one')
        per_player.append(dict(player=p,reach_mass=mass,
            query_access_value=sum(r['reach_mass']*r['query_access_value'] for r in cells),
            strict_query_mass=sum(r['reach_mass'] for r in cells if r['first_query_gap']>TOL),
            tied_query_mass=sum(r['reach_mass'] for r in cells if abs(r['first_query_gap'])<=TOL),
            inferior_query_mass=sum(r['reach_mass'] for r in cells if r['first_query_gap'] < -TOL),
            query_probability=sum(r['reach_mass']*r['query_probability'] for r in cells)))
    initial = [r for r in rows if r['root_index']==0]
    best_answer = [q['same_query_answer_value'] for r in rows for q in r['query_details']
                   if 'same_query_answer_value' in q]
    return dict(rows=rows,per_player=per_player,
        summary=dict(first_proposal_cells=len(rows),
            player_uniform_query_access=sum(r['query_access_value'] for r in per_player)/tree.n,
            player_uniform_strict_query_mass=sum(r['strict_query_mass'] for r in per_player)/tree.n,
            player_uniform_tied_query_mass=sum(r['tied_query_mass'] for r in per_player)/tree.n,
            player_uniform_inferior_query_mass=sum(r['inferior_query_mass'] for r in per_player)/tree.n,
            initial_actor_query_access=sum(r['reach_mass']*r['query_access_value'] for r in initial),
            initial_actor_strict_query_mass=sum(r['reach_mass'] for r in initial if r['first_query_gap']>TOL),
            max_measured_same_query_answer_value=max(best_answer,default=None)),
        ex_ante_payoffs=(tree.world_weights @ tree.values[0]).tolist())


def one_parent(job):
    parent, ref, pool_string, out_string, seconds, analysis_seconds = job
    pool, out = Path(pool_string), Path(out_string)
    pid, raw = parent['id'], parent['raw']
    status = dict(parent_id=pid,split=parent['split'],players=parent['players'],
                  status='started',reference_id=ref['id'])
    start = time.monotonic()
    phase = 'baseline_restore'
    tree = None
    try:
        assert_factorized(raw)
        if digest(pool/ref['file']) != ref['sha256']:
            raise ValueError('Original reference hash mismatch')
        tree = restore_reference(raw, ref, pool/ref['file'])
        tree.deadline = time.monotonic()+analysis_seconds
        checked = certify_policy(tree,epsilon=TOL)
        if checked is None:
            raise ValueError('Original profile failed independent re-certification')
        tree.values = checked['values']
        original_hash = tree.reference_identity()[0]
        if original_hash != ref['certificate']['policy_sha256']:
            raise ValueError('Original identity changed after validation')
        phase = 'baseline_metrics'
        baseline = metrics(tree,analysis_seconds)
        baseline.update(original_reference_file=ref['file'],original_reference_sha256=ref['sha256'],
            original_policy_sha256=original_hash,independent_certificate=checked['certificate'],
            nodes=len(tree.entries),identity_preserved=True)
        write(out/f'{pid}_baseline.json',baseline)
        schedule=raw['game']['round_robin']
        binding=max(Counter(schedule).values())>1
        status.update(binding=binding,baseline='validated-and-measured')
        del tree
        tree=None
        gc.collect()
        if not binding:
            equivalence=dict(status='reused-original-profile-under-nonbinding-quota-equivalence',
                original_reference_file=ref['file'],original_reference_sha256=ref['sha256'],
                original_policy_sha256=original_hash,
                proof='Each player has at most one proposal turn, so quota 1 can remove no OFFER at any legal history. Query, responses, payoff and observations remain identical apart from counters deterministically recoverable from public history. Identity map preserves every information set and strategy.',
                quota_solver_called=False,metric_values_identical_to_baseline=True,
                summary=baseline['summary'],ex_ante_payoffs=baseline['ex_ante_payoffs'])
            write(out/f'{pid}_quota.json',equivalence)
            status.update(status='complete-equivalent',quota='nonbinding-equivalence',
                baseline_summary=baseline['summary'],quota_summary=baseline['summary'],
                baseline_payoffs=baseline['ex_ante_payoffs'],quota_payoffs=baseline['ex_ante_payoffs'])
        else:
            phase='quota_solve'
            rules=OfferQuotaRules(raw,1)
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),
                lookahead_rr=len(schedule),max_nodes=160000,seconds=seconds).solve()
            if tree.cutoff_leaves:
                raise AssertionError('Quota game has nonterminal cutoff leaves')
            phase='quota_audit'
            tree.deadline=time.monotonic()+analysis_seconds
            native_audit=tree.audit_native()
            bookkeeping=audit_quota(tree)
            phase='quota_metrics'
            quota=metrics(tree,analysis_seconds)
            save_reference(out/f'{pid}_quota_reference.npz',tree)
            quota.update(status='new-full-terminal-certified-quota-profile',
                certificate=tree.certificate,native_audit=native_audit,quota_audit=bookkeeping,
                nodes=len(tree.entries),reference_sha256=digest(out/f'{pid}_quota_reference.npz'))
            write(out/f'{pid}_quota.json',quota)
            status.update(status='complete-resolved',quota='new-certified-full-terminal-profile',
                baseline_summary=baseline['summary'],quota_summary=quota['summary'],
                baseline_payoffs=baseline['ex_ante_payoffs'],quota_payoffs=quota['ex_ante_payoffs'],
                baseline_nodes=baseline['nodes'],quota_nodes=quota['nodes'])
    except Exception as exc:
        status.update(status='missing-result',failed_phase=phase,
            reason=f'{type(exc).__name__}: {exc}',oracle_label=None)
    status['seconds']=time.monotonic()-start
    write(out/f'{pid}_status.json',status)
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--solver-seconds',type=float,default=90)
    parser.add_argument('--analysis-seconds',type=float,default=180)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    registered=registered_snapshot('terminal-node-regret-grpo-readable-v8','terminal-readable-named-v2')
    active=json.loads((ROOT/registered['path']).read_text())
    pool=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    for rel,expected in active['data_selection_D_files'].items():
        if digest(ROOT/rel)!=expected:
            raise ValueError('Frozen input identity changed: '+rel)
    parents=[json.loads(l) for l in (pool/'parents.jsonl').read_text().splitlines()]
    refs={r['parent_id']:r for r in map(json.loads,(pool/'references.jsonl').read_text().splitlines())}
    if len(parents)!=100 or len({p['id'] for p in parents})!=100:
        raise ValueError('Original full 100 parents required')
    write(args.output/'parents.json',parents)
    sources={**active['contract_sources'],
        str(Path(__file__).relative_to(ROOT)):digest(Path(__file__)),
        'new/offer_budget_mechanism_20261021/research.py':digest(ROOT/'new/offer_budget_mechanism_20261021/research.py'),
        'new/offer_budget_mechanism_20261021/test_research.py':digest(ROOT/'new/offer_budget_mechanism_20261021/test_research.py')}
    defaults=dict(constructor=source_defaults(BoundedPrivateWindow.__init__),
                  numerical_solver=source_defaults(solve_equilibrium))
    write(args.output/'pipeline_snapshot.json',dict(version=VERSION,status='launched-not-completed',
        actual_argv=sys.argv,actual_options={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        active_training=registered,
        resolved_config=dict(pool=str(pool.relative_to(ROOT)),parents=100,offer_limit=1,
            original_reference='restore saved initial-terminal profile and independently re-certify',
            new_solver_seconds=args.solver_seconds,analysis_seconds_per_player=args.analysis_seconds,
            max_nodes=160000,lookahead_rr='len(original schedule); full terminal only',
            unchanged_constructor_and_solver_defaults=defaults,
            response_ties='own expected final utility, then others sum, only ACCEPT/REJECT',
            query='unchanged original per-player one use, consumes proposal turn',
            preferences='unchanged original Cartesian support and prior',
            sampling='complete tree and expected values; no Monte Carlo',
            measurement_scope='reachable first proposal of every player; full contingent BR and no-own-queries BR; answer mask for informative best queries',
            summary_weight='each original parent equal; within parent players equal and cells weighted by reference reach',
            tolerance=TOL,failure='missing, not zero signal; preserve partial artifacts',
            nonbinding='reuse original identity under documented complete-game equivalence'),
        source_manifest=sources,
        inputs={str(p.relative_to(ROOT)):digest(p) for p in (pool/'manifest.json',pool/'parents.jsonl',pool/'references.jsonl')},
        data_selection_D_identity=active['data_selection_D_files'],model_identity='none',
        reward_advantage_training='not applicable; mechanism diagnostics only',
        runtime=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),numpy=np.__version__,
            environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        production_changed=False,gpu_used=False))
    src=args.output/'source';src.mkdir()
    shutil.copyfile(__file__,src/Path(__file__).name)
    shutil.copyfile(ROOT/'new/offer_budget_mechanism_20261021/research.py',src/'research.py')
    suite=unittest.defaultTestLoader.loadTestsFromName('new.offer_budget_mechanism_20261021.test_research')
    test_result=unittest.TextTestRunner(verbosity=1).run(suite)
    write(args.output/'semantic_checks.json',dict(tests=test_result.testsRun,passed=test_result.wasSuccessful()))
    if not test_result.wasSuccessful():
        raise RuntimeError('Rule checks failed')
    # Original order is preserved in parents.json; dispatch independent jobs by
    # ascending tree size only to produce earlier progress, without selection.
    parents_ordered=sorted(parents,key=lambda p:(p['native_nodes'],p['id']))
    jobs=[(p,refs[p['id']],str(pool),str(args.output),args.solver_seconds,args.analysis_seconds) for p in parents_ordered]
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(one_parent,j) for j in jobs]
        for future in as_completed(futures):
            status=future.result()
            results.append(status)
            with (args.output/'progress.jsonl').open('a') as f:
                f.write(json.dumps(status,ensure_ascii=False)+'\n')
            print(json.dumps(dict(done=len(results),parent=status['parent_id'],
                status=status['status'],phase=status.get('failed_phase'),reason=status.get('reason'),
                seconds=status['seconds']),ensure_ascii=False),flush=True)
    write(args.output/'summary.json',dict(version=VERSION,status='completed-all-attempts',
        total_parents=100,completed=len(results),statuses=dict(Counter(r['status'] for r in results)),
        results=sorted(results,key=lambda r:r['parent_id']),
        failures_are_missing_not_zero=True,model_calls=0,gpu_used=False,production_changed=False))
    write(args.output/'COMPLETE.json',dict(status='all-100-attempted',
        pipeline_snapshot_sha256=digest(args.output/'pipeline_snapshot.json'),
        summary_sha256=digest(args.output/'summary.json')))


if __name__=='__main__':
    main()
