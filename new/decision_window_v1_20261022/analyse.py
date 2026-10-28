"""Inspect frozen probe output and reload one information-use witness."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy

from new.decision_window_v1_20261022.probe import ROOT, OPTIONS, sha, write
from new.decision_window_v1_20261022.window import DecisionWindow, VERSION
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.equilibrium import certify_policy


def information_witness(parent, result, run):
    """Same public history and own type, different private answer and best action.

    This tests actual information use under one accepted bounded profile. It
    does not implement omitted-information policy optimization or measure S.
    """
    rules=StrategicRules(parent['raw'])
    tree=DecisionWindow(rules,rules.initial(),rules.worlds,
        world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),seconds=30,**OPTIONS)
    path=run/result['reference'];assert sha(path)==result['reference_sha256']
    with np.load(path) as data:flat=data['probabilities']
    cursor=0
    for i,p in enumerate(tree.policy):
        if p is not None:
            count=p.size;tree.policy[i]=flat[cursor:cursor+count].reshape(p.shape).copy();cursor+=count
    assert cursor==len(flat)
    identity,_=tree.reference_identity()
    assert identity==result['certificate']['policy_sha256']
    tree.deadline=time.monotonic()+30;tree.values=tree.evaluate()
    checked=certify_policy(tree,epsilon=OPTIONS['epsilon'])
    assert checked is not None
    native=tree.audit_native()
    focal=tree.root_actor
    contexts=result['bounded_root_Q']['private_contexts']
    for context in contexts:
        if (context['best_investigate_minus_best_nonquery'] or 0)<=1e-8:continue
        query_indices=[i for i,a in enumerate(tree.entries[0].actions)
                       if a.to_dict()['action']=='INVESTIGATE']
        qa=max(query_indices,key=lambda i:context['Q'][i])
        query=tree.entries[0].actions[qa];query_child=tree.entries[0].children[qa]
        reach=[None]*len(tree.entries)
        reach[0]=tree.world_weights*np.array([list(w[focal])==context['own_type'] for w in tree.worlds])
        for i,e in enumerate(tree.entries):
            for a,c in enumerate(e.children):
                reach[c]=reach[i]*tree.policy[i][a]
                if i==0 and c!=query_child:reach[c]=np.zeros(tree.w)
            if e.actor!=focal or e.node.state.turn_index!=tree.next_own_proposal_index:continue
            groups=[]
            for ids in tree.information_groups[i]:
                mass=float(reach[i][ids].sum())
                if mass<=1e-12:continue
                weights=reach[i][ids]/mass
                q=[float(weights@tree.values[c][ids,focal]) for c in e.children]
                best=[a for a,v in enumerate(q) if max(q)-v<=1e-8]
                groups.append(dict(answer=tree.worlds[ids[0]][query.player][query.goal],
                    reach_mass=mass,Q=q,best_actions=best))
            for left in groups:
                for right in groups:
                    if left['answer']>=right['answer'] or set(left['best_actions'])&set(right['best_actions']):continue
                    return dict(index=parent['index'],focal=focal,own_type=context['own_type'],
                        initial_investigation=query.to_dict(),
                        root_query_advantage=context['best_investigate_minus_best_nonquery'],
                        same_public_history=[event.to_dict() for event in e.node.state.transcript],
                        own_next_proposal_turn=e.node.state.turn_index,
                        actions=[a.to_dict() for a in e.actions],answer_cases=[left,right],
                        selected_profile_positive_reach=True,independent_reload_certificate=checked['certificate'],
                        native_audit=native,meaning='Private-answer-sensitive next action; NOT an S measurement')
    return dict(index=parent['index'],independent_reload_certificate=checked['certificate'],
                native_audit=native,example='No disjoint optimal-action witness at positive reach found')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();run=args.run_dir.resolve()
    assert (run/'COMPLETE.json').is_file()
    results=json.loads((run/'results.json').read_text())
    structure=json.loads((run/'structure_100.json').read_text())
    missing=set(json.loads((ROOT/'new/remote_solver_results_20261022/SUMMARY.json').read_text())['unavailable_indices'])
    parents={p['index']:p for p in map(json.loads,(ROOT/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl').read_text().splitlines())}
    certified=[r for r in results if r['status']=='certified_bounded']
    groups=defaultdict(list)
    for row in structure:groups[row['configuration']['players']].append(row)
    reduction={str(n):dict(parents=len(rows),full_nodes=sum(r['full_nodes'] for r in rows),
        window_nodes=sum(r['window_nodes'] for r in rows),
        aggregate_reduction_factor=sum(r['full_nodes'] for r in rows)/sum(r['window_nodes'] for r in rows),
        window_min=min(r['window_nodes'] for r in rows),window_max=max(r['window_nodes'] for r in rows))
        for n,rows in groups.items()}
    signals=[]
    for r in certified:
        contexts=r['bounded_root_Q']['private_contexts']
        gaps=[c['best_investigate_minus_best_nonquery'] for c in contexts
              if c['best_investigate_minus_best_nonquery'] is not None]
        signals.append(dict(index=r['index'],contexts=len(contexts),
            query_comparable=bool(gaps),positive_query_contexts=sum(v>1e-8 for v in gaps),
            negative_query_contexts=sum(v< -1e-8 for v in gaps),
            tied_query_contexts=sum(abs(v)<=1e-8 for v in gaps),
            max_query_gap=max(gaps) if gaps else None))
    candidate=next(r for r in certified if r['index']==9)
    example=information_witness(parents[9],candidate,run)
    output=dict(version=VERSION,date='2026-10-22',
        attempts=len(results),outcomes=dict(Counter(r['status'] for r in results)),
        original_15=dict(attempts=15,bounded_certified=[r['index'] for r in certified if r['index'] in missing],
                        bounded_missing=[r['index'] for r in results if r['index'] in missing and r['status']=='unavailable']),
        failures=[dict(index=r['index'],phase=r['failed_phase'],reason=r['reason']) for r in results if r['status']=='unavailable'],
        reduction=reduction,root_query_diagnostics=signals,
        parents_with_positive_query_gap=[r['index'] for r in signals if r['positive_query_contexts']],
        max_saved_own_deviation=max(r['independent_certificate']['max_own_deviation_gain'] for r in certified),
        max_saved_local_support_gain=max(r['independent_certificate']['max_local_supported_action_gain'] for r in certified),
        scope='Bounded game results. Different objective, source and CPU budgets from old remote results; not repaired terminal labels.',
        S='NOT_MEASURED',D='NOT_MEASURED',training='NOT_RUN')
    write(run/'ANALYSIS.json',output);write(run/'INFORMATION_USE_WITNESS.json',example)
    write(run/'analysis_snapshot.json',dict(version=VERSION,actual_argv=sys.argv,
        source_hashes={str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__))},
        probe_snapshot_sha256=sha(run/'pipeline_snapshot.json'),
        source_identity='Original probe source copies/hash contract plus this analysis module',
        inputs={p.name:sha(p) for p in [run/'results.json',run/'structure_100.json',run/'COMPLETE.json']},
        outputs={p.name:sha(p) for p in [run/'ANALYSIS.json',run/'INFORMATION_USE_WITNESS.json']},
        environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform()),
        reload_scope='Frozen index9 full numerical certificate/native audit only; other accepted references inspected from saved certificates',
        model='NOT_USED',S_D_training='NOT_RUN',production_changed=False))
    print(json.dumps(output,ensure_ascii=False,indent=2))
    print('Information-use example:',json.dumps({k:v for k,v in example.items()
        if k not in ['independent_reload_certificate','native_audit']},ensure_ascii=False))


if __name__=='__main__':main()
