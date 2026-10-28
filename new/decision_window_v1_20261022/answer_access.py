"""Isolate private answer use from the public signaling effect of a query.

This is a pre-answer access diagnostic, NOT the new current-node S protocol.
Other-player strategies, public query event and physical state remain fixed.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
import json

from new.decision_window_v1_20261022.probe import ROOT, OPTIONS, write, sha
from new.decision_window_v1_20261022.window import DecisionWindow, VERSION
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.decision_policy import optimal_indices
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.equilibrium import _reach


def restricted_response_values(tree, focal, omitted):
    """Exact contingent BR with one answer unavailable throughout continuation.

    Group by own preferences + remaining own answers at each unchanged public
    history. Conditional weights come from fixed opponents, excluding all own
    choices. The same distribution must be used in worlds merged by omission.
    """
    reach=_reach(tree,focal);values=[None]*len(tree.entries)
    for index in reversed(range(len(tree.entries))):
        tree._check();entry=tree.entries[index]
        if entry.actor is None:values[index]=entry.payoff;continue
        children=np.stack([values[c] for c in entry.children])
        if entry.actor!=focal:
            values[index]=np.einsum('aw,awp->wp',tree.policy[index],children);continue
        slots=[slot for slot in observed_slots(entry.node,focal) if slot!=omitted]
        groups=defaultdict(list)
        for wi,world in enumerate(tree.worlds):
            groups[(world[focal],tuple(world[p][g] for p,g in slots))].append(wi)
        probs=np.zeros_like(tree.policy[index])
        for rows in groups.values():
            ids=np.array(rows);weights=reach[index][ids]
            if weights.sum()==0:weights=tree.world_weights[ids]
            means=np.einsum('awp,w->ap',children[:,ids],weights/weights.sum())
            best=optimal_indices(means,focal,entry.actions,1e-9)
            probs[np.ix_(best,ids)]=1/len(best)
            np.testing.assert_allclose(probs[:,ids],np.broadcast_to(probs[:,ids[:1]],probs[:,ids].shape))
        values[index]=np.einsum('aw,awp->wp',probs,children)
    return values


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();run=args.run_dir.resolve()
    results={r['index']:r for r in json.loads((run/'results.json').read_text())}
    parents={p['index']:p for p in map(json.loads,(ROOT/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl').read_text().splitlines())}
    selected=json.loads((run/'ANALYSIS.json').read_text())['parents_with_positive_query_gap']
    snapshot=dict(version=VERSION,actual_argv=sys.argv,created_on='2026-10-22',
        source_hashes={str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__))},
        probe_snapshot_sha256=sha(run/'pipeline_snapshot.json'),input_results_sha256=sha(run/'results.json'),
        input_analysis_sha256=sha(run/'ANALYSIS.json'),
        scope='All six certified parents with positive root query gaps; post-outcome diagnostic, not membership selection',
        selected_indices=selected,resolved_config=dict(construction_seconds=30,diagnostic_seconds=30,
            options=OPTIONS,mask='Only the queried private answer; all public history, preferences and binding state retained',
            opponents='One unchanged selected bounded-game profile',
            own_policy='Full contingent best response, then exact answer-restricted best response',
            omitted_policy_ties='Existing own utility then response-only others-sum, equal mixture of remaining ties',
            off_path='Existing counterfactual reach / conditional prior convention'),
        environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform()),
        model='NOT_USED',production_S='NOT_IMPLEMENTED',D='NOT_MEASURED',training='NOT_RUN')
    write(run/'answer_access_snapshot.json',snapshot)
    output=[]
    for index in selected:
        parent=parents[index];r=results[index];rules=StrategicRules(parent['raw'])
        tree=DecisionWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),seconds=30,**OPTIONS)
        assert sha(run/r['reference'])==r['reference_sha256']
        with np.load(run/r['reference']) as data:flat=data['probabilities']
        cursor=0
        for i,p in enumerate(tree.policy):
            if p is not None:
                tree.policy[i]=flat[cursor:cursor+p.size].reshape(p.shape).copy();cursor+=p.size
        assert cursor==len(flat) and tree.reference_identity()[0]==r['certificate']['policy_sha256']
        tree.deadline=time.monotonic()+30;focal=tree.root_actor
        updates,_=tree.response(focal)
        policy=[None if p is None else p.copy() for p in tree.policy]
        for i,p in updates.items():policy[i]=p
        full=tree.evaluate(policy)
        for ai,action in enumerate(tree.entries[0].actions):
            if action.to_dict()['action']!='INVESTIGATE':continue
            masked=restricted_response_values(tree,focal,(action.player,action.goal))
            child=tree.entries[0].children[ai]
            for ids in tree.groups[focal]:
                own=list(tree.worlds[ids[0]][focal])
                context=next(c for c in r['bounded_root_Q']['private_contexts'] if c['own_type']==own)
                if (context['best_investigate_minus_best_nonquery'] or 0)<=1e-8:continue
                if max(context['Q'])-context['Q'][ai]>1e-8:continue
                weights=tree.world_weights[ids];weights=weights/weights.sum()
                with_answer=float(weights@full[child][ids,focal])
                without_answer=float(weights@masked[child][ids,focal])
                assert with_answer+1e-8>=without_answer
                output.append(dict(index=index,focal=focal,own_type=own,query=action.to_dict(),
                    full_answer_value=with_answer,answer_restricted_value=without_answer,
                    private_answer_access_gain=with_answer-without_answer,
                    root_query_vs_nonquery_gap=context['best_investigate_minus_best_nonquery']))
    result=dict(diagnostic='pre-answer private-access loss under same public query and fixed opponents; NOT current-node S',
                contexts=output,positive_contexts=sum(r['private_answer_access_gain']>1e-8 for r in output),
                positive_parents=sorted({r['index'] for r in output if r['private_answer_access_gain']>1e-8}))
    write(run/'ANSWER_ACCESS_DIAGNOSTIC.json',result)
    write(run/'ANSWER_ACCESS_COMPLETE.json',dict(snapshot_sha256=sha(run/'answer_access_snapshot.json'),
        result_sha256=sha(run/'ANSWER_ACCESS_DIAGNOSTIC.json'),
        source_identity_verified=all(sha(ROOT/p)==h for p,h in snapshot['source_hashes'].items()),
        all_selected_parents_checked=True,model_D_training=False))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
