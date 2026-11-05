"""Independent forced-current-action LP checks on the saved three-player case."""
from new import qs_action_profile_20261104 as m
import argparse
from dataclasses import replace
import io
import json
from pathlib import Path
import tarfile

import numpy as np
from new.A2H2_structure_20261026 import IndexedReference
from new.node_qs_audit_v1_20261023.metrics import Observations, contingent_values, forest_response
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.equilibrium import _reach


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output = args.output.resolve()
    m.VERSION = 'qs-action-profile-witness-v1'
    m.REG = m.ROOT/'examples/strategic_slices/versions/qs_action_profile_witness_v1_20261104/SNAPSHOT.json'
    previous = m.ROOT/'new/three_player_walkthrough_20261029/run_v1'
    inputs = [previous/'CASE.json', previous/'ANSWER_OMISSION.json', previous/'pipeline_snapshot.json',
              m.ROOT/'new/structure_pool_remote_results_20261029/results.tar.gz']
    m.snapshot(args.output, dict(operation='Saved actual three-player case, no new equilibrium/game',
        index=10, node=151856, focal=0, omitted=['private', 2, 2], worlds=[0, 1, 2],
        root_masses='Equal1/3 from prior saved counterfactual masses1/324 each',
        max_nodes=10000, construct_seconds=30, LP_seconds_per_solve=60,
        LP='18 independent forced-current-action sequence-form LPs; own-optimal, social constraints relaxed',
        diagnostic_checks=['equal-utility policy switch', 'tiny-regret deterministic switch', 'JS symmetry and bound',
                           'Q common-shift invariance', 'three real answer contexts and exact current/future decomposition'],
        workers=1, threads=1, D='NOT_MEASURED', candidate800='NOT_GENERATED'), {})
    m.write(args.output/'input_identity.json', {str(p.relative_to(m.ROOT)):m.sha(p) for p in inputs})
    case = json.loads(inputs[0].read_text()); old = json.loads(inputs[1].read_text())
    archive = inputs[-1]
    name = 'runtime/new/structure_pool_v1_20261026/remote_remaining18_runtime_v4_20261029/cases/10/reference.npz'
    with tarfile.open(archive) as tar:
        # Result paths are relative to the run; recover the exact recorded path.
        run = 'runtime/new/structure_pool_v1_20261026/remote_remaining18_runtime_v4_20261029/'
        result = case['original_result']
        name = run+str(Path(result['result_path']).parent/'reference.npz')
        reference = tar.extractfile(name).read()
    import hashlib
    assert hashlib.sha256(reference).hexdigest() == case['original_result']['reference_sha256']
    with np.load(io.BytesIO(reference)) as data:
        flat = data['probabilities']
    indexed = IndexedReference(case['job'], flat); node, offset = indexed.find(151856)
    ids = [0, 1, 2]; weights = np.ones(3)/3
    tree = BoundedPrivateWindow(indexed.rules, node, [indexed.rules.worlds[i] for i in ids],
        world_weights=weights, lookahead_rr=3, max_nodes=10000, seconds=30)
    assert not tree.cutoff_leaves
    pos = offset
    for entry, policy in zip(tree.entries, tree.policy):
        if policy is None:
            continue
        size = len(entry.actions)*indexed.w
        policy[:] = flat[pos:pos+size].reshape(len(entry.actions), indexed.w)[:, ids]; pos += size
    assert pos-offset == indexed.stats(node)[1]
    tree.deadline = float('inf'); obs = Observations(tree, 0); roots = {0:weights}; mask = ('private',2,2)
    result = m.forest_with_actions(tree, 0, roots, omitted=mask, observations=obs)
    legacy = forest_response(tree, 0, roots, omitted=mask, observations=obs)
    np.testing.assert_allclose(result['values'][0], legacy['values'][0], atol=1e-10, rtol=0)
    np.testing.assert_allclose(result['root_policy'][0], legacy['root_policy'][0], atol=1e-10, rtol=0)
    full = contingent_values(tree, 0, _reach(tree, 0))
    qfull = np.stack([full[ch][:,0] for ch in tree.entries[0].children]).T
    qtrue = result['root_action_values'][0][:,:,0].T
    qsubjective = weights@qtrue
    rows=[]
    for wi in range(3):
        prior = next(r for r in old['answer_comparisons'] if r['answer'] == indexed.rules.worlds[wi][2][2])
        np.testing.assert_allclose(qfull[wi], prior['full_Q'], atol=1e-8, rtol=0)
        pf = np.zeros(len(qsubjective)); best=np.flatnonzero(qfull[wi] >= qfull[wi].max()-m.TOL);pf[best]=1/len(best)
        pm = result['root_policy'][0][:,wi]
        loss = float(qfull[wi].max()-result['values'][0][wi,0])
        np.testing.assert_allclose(loss, prior['S'], atol=1e-8, rtol=0)
        rows.append(dict(answer=prior['answer'], Q_full=qfull[wi].tolist(), Q_omitted_subjective=qsubjective.tolist(),
            Q_omitted_evaluated_true=qtrue[wi].tolist(), canonical_full_policy=pf.tolist(), omitted_policy=pm.tolist(),
            S=loss, **m.distribution_stats(qfull[wi],pf,pm,loss)))
    saved_entry=tree.entries[0]; saved_policy=tree.policy[0]
    checks=[]
    try:
        for ai in range(len(saved_entry.actions)):
            tree.entries[0] = replace(saved_entry, actions=(saved_entry.actions[ai],), children=(saved_entry.children[ai],))
            tree.policy[0] = np.ones((1,tree.w))
            # A forced action is an intervention for verification only, not a
            # rule/menu modification of any generated game or training input.
            local_obs=Observations(tree,0)
            lp_omit=sequence_lp(tree,0,roots,omitted=mask,observations=local_obs)
            lp_full=sequence_lp(tree,0,roots,omitted=None,observations=local_obs)
            np.testing.assert_allclose(lp_omit['V_omitted_LP'],qsubjective[ai],atol=1e-8,rtol=0)
            np.testing.assert_allclose(lp_full['V_omitted_LP'],weights@qfull[:,ai],atol=1e-8,rtol=0)
            checks.append(dict(action=ai,omitted=lp_omit,full=lp_full,both_match=True))
    finally:
        tree.entries[0]=saved_entry;tree.policy[0]=saved_policy
    tests={}
    x=m.distribution_stats([1,1],[1,0],[0,1],0)
    assert x['policy_total_variation']==1 and x['own_current_loss']==0
    tests['equal_utility_full_distribution_switch_has_zero_regret']=x
    y=m.distribution_stats([1,1-1e-6],[1,0],[0,1],1e-6)
    assert abs(y['policy_JS_nats']-np.log(2))<1e-12 and y['own_current_loss']<2e-6
    tests['maximal_divergence_can_have_tiny_regret']=y
    z=m.distribution_stats([10,10-1e-6],[1,0],[0,1],1e-6)
    np.testing.assert_allclose(z['action_regret'],y['action_regret'],atol=1e-12,rtol=0)
    swapped=m.distribution_stats([1,1],[0,1],[1,0])
    assert swapped['policy_JS_nats']==x['policy_JS_nats']
    tests['common_shift_invariance_and_JS_symmetry']=True
    m.write(args.output/'REAL_CASE.json',dict(parent_id=case['job']['id'], index=10, original_node=151856,
        native_nodes=len(tree.entries), cutoff_leaves=0, answer_contexts=rows, forced_action_LP_checks=checks,
        scope='Single saved reference; no cross-equilibrium guarantee or full24 recomputation'))
    m.write(args.output/'ANALYTIC_CHECKS.json',tests)
    m.write(args.output/'COMPLETE.json',dict(three_Q_S_contexts_match=True,legacy_forest_policy_matches=True,
        forced_action_LP_matches=len(checks)*2,analytic_checks_passed=True,
        real_case_sha256=m.sha(args.output/'REAL_CASE.json'), pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
