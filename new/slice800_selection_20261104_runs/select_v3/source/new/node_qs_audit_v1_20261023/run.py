"""Versioned CPU audit of saved terminal and bounded references; no new solve."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np
import scipy

from .metrics import measure, EPS, TOL
from new.sparse_solver_v1_20261023.common import ROOT, POOL, POOL_SHA, parents, sha, write
from new.sparse_solver_v1_20261023.probe import build
from new.decision_window_v1_20261022.window import DecisionWindow
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.equilibrium import certify_policy

VERSION = 'node-qs-interactivity-audit-v1'
REGISTRATION = ROOT/'examples/strategic_slices/versions/node_qs_audit_v1_20261023/SNAPSHOT.json'
TERMINAL = ROOT/'new/sparse_solver_v1_20261023/full100_v1'
WINDOW = ROOT/'new/sparse_solver_v1_20261023/pipeline_e2e_v1/references'


def inputs(mode):
    if mode == 'terminal':
        rows = json.loads((TERMINAL/'results.json').read_text())
        return {r['index']:dict(path=TERMINAL/'cases'/str(r['index'])/'reference.npz',
            sha256=r['reference_sha256'], result=TERMINAL/'cases'/str(r['index'])/'result.json')
            for r in rows if r['status']=='certified_native_terminal'}
    rows = json.loads((WINDOW/'REFERENCE_INDEX.json').read_text())
    return {r['index']:dict(path=WINDOW/r['reference'], sha256=r['reference_sha256']) for r in rows}


def summarize(rows):
    cf = [r for r in rows if r['counterfactual_mass'] > 0]
    on = [r for r in cf if r['reference_mass'] > 0]
    def scope(selected):
        proposals = [r for r in selected if r['phase']=='proposal']
        queries = [r for r in proposals if r['query_gap'] is not None]
        return dict(contexts=len(selected), proposals=len(proposals), responses=len(selected)-len(proposals),
            positive_Q_span=sum(r['span']>EPS for r in selected),
            all_actions_own_tied=sum(r['span']<=EPS for r in selected),
            response_social_tie_matters=sum(r['phase']=='response' and len(r['optimal'])<len(r['own_optimal']) for r in selected),
            query_available=len(queries), query_strictly_better=sum(r['query_gap']>EPS for r in queries),
            max_query_gap=max((r['query_gap'] for r in queries), default=None),
            private_S_positive=sum((r['S_private'] or 0)>EPS for r in selected),
            history_S_positive=sum((r['S_history'] or 0)>EPS for r in selected),
            max_private_S=max((r['S_private'] or 0 for r in selected), default=0.),
            max_history_S=max((r['S_history'] or 0 for r in selected), default=0.),
            private_answer_contexts=sum(bool(r['private_answers']) for r in selected),
            with_history_omission=sum(any(x['omitted'][0]=='history' for x in r['S_items']) for r in selected),
            offers_type_dependent=sum(any(o['acceptance_type_range']>EPS and abs(o['own_accept_minus_reject'])>EPS
                for o in r.get('offers',[])) for r in proposals),
            optimal_offer_type_dependent=sum(any(o['action'] in r['optimal'] and o['acceptance_type_range']>EPS
                and abs(o['own_accept_minus_reject'])>EPS for o in r.get('offers',[])) for r in proposals),
            static_dynamic_offer_disjoint=sum(r.get('offer_static_dynamic_disjoint',False) for r in proposals),
            immediate_action_optimal_disjoint=sum(not r['immediate_optimal_overlap'] for r in selected),
            max_BR_vs_ref_Q_difference=max((float(np.max(np.abs(np.array(r['Q'])-r['Q_reference']))) for r in selected),default=0.),
            proposal_spans=[r['span'] for r in proposals],
            positive_distinct_gaps=[r['best_minus_next_distinct'] for r in selected if r['best_minus_next_distinct'] is not None])
    return dict(all_cells=len(rows), zero_CF_cells=len(rows)-len(cf),
        S_unavailable_items=sum(r['unavailable_S_items'] for r in rows),
        counterfactual=scope(cf), on_reference=scope(on))


def examples(tree, rows, limit=2):
    categories = dict(
        private_S=lambda r:r['S_private'] or 0,
        history_S=lambda r:r['S_history'] or 0,
        query_advantage=lambda r:r['query_gap'] or 0,
        type_dependent_optimal_offer=lambda r:float(any(o['action'] in r['optimal'] and o['acceptance_type_range']>EPS
            and abs(o['own_accept_minus_reject'])>EPS for o in r.get('offers',[]))))
    output = {}
    for category, score in categories.items():
        chosen = sorted((r for r in rows if r['counterfactual_mass']>0 and score(r)>EPS),
            key=lambda r:(-score(r),-r['reference_mass'],r['node'],r['cell']))[:limit]
        output[category] = [dict(**r, history=[e.to_dict() for e in tree.entries[r['node']].node.state.transcript],
            commitments=tree.entries[r['node']].node.state.snapshot_commitments(),
            pending=None if tree.entries[r['node']].node.pending is None else tree.entries[r['node']].node.pending.to_dict())
            for r in chosen]
    return output


def worker(index, parent, identity, mode, output):
    start=time.monotonic(); path=output/'cases'/str(index); path.mkdir(parents=True)
    row=dict(index=index, parent_id=parent['id'], mode=mode, players=parent['configuration']['players'],
             status='started', reference_sha256=identity['sha256'])
    try:
        assert sha(identity['path'])==identity['sha256']
        if mode=='terminal': tree=build(parent,seconds=60)
        else:
            rules=StrategicRules(parent['raw'])
            tree=DecisionWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),
                max_nodes=100000,seconds=60)
        with np.load(identity['path']) as data: flat=data['probabilities']
        offset=0
        for p in tree.policy:
            if p is not None:
                p[:]=flat[offset:offset+p.size].reshape(p.shape);offset+=p.size
        assert offset==len(flat)
        tree.deadline=time.monotonic()+180
        certificate=certify_policy(tree,epsilon=EPS)
        assert certificate is not None, tree.equilibrium_audit
        row.update(nodes=len(tree.entries),worlds=tree.w,cutoff_leaves=len(tree.cutoff_leaves),
            native_audit=tree.audit_native(),certificate=certificate['certificate'])
        tree.deadline=float('inf')
        labels, operations=measure(tree)
        with gzip.open(path/'labels.jsonl.gz','wt',encoding='utf-8') as stream:
            for label in labels:
                stream.write(json.dumps(label,ensure_ascii=False,separators=(',',':'))+'\n')
        write(path/'examples.json',examples(tree,labels))
        row.update(status='measured',summary=summarize(labels),operations=operations,
            labels_sha256=sha(path/'labels.jsonl.gz'), examples_sha256=sha(path/'examples.json'))
    except Exception as exc:
        import traceback
        row.update(status='error',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    row['elapsed_seconds']=time.monotonic()-start;write(path/'result.json',row)
    print(dict(index=index,mode=mode,status=row['status'],elapsed=round(row['elapsed_seconds'],2),
        error=row.get('error')),flush=True)
    return row


def snapshot(output, config, identities):
    registered=json.loads(REGISTRATION.read_text())
    assert registered['version']==VERSION
    for path,digest in registered['source_hashes'].items():
        assert sha(ROOT/path)==digest, f'Source changed: {path}'
    assert sha(POOL)==POOL_SHA
    output.mkdir(parents=True,exist_ok=False)
    for rel in registered['source_hashes']:
        target=output/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,target)
    shutil.copyfile(REGISTRATION,output/'registered_snapshot_at_start.json')
    write(output/'pipeline_snapshot.json',dict(version=VERSION,created_on='2026-10-23',
        actual_argv=sys.argv, resolved_config=config,
        source_hashes=registered['source_hashes'], registration_sha256=sha(REGISTRATION),
        input_data=dict(path=str(POOL.relative_to(ROOT)),sha256=POOL_SHA),
        references={str(i):dict(path=str(x['path'].relative_to(ROOT)),sha256=x['sha256'])
                    for i,x in identities.items()},
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,
            scipy=scipy.__version__,platform=platform.platform(),
            threads={key:__import__('os').environ.get(key,'NOT_RECORDED') for key in
                ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        model='NOT_USED',prompt='NOT_CHANGED_NOT_USED',D='NOT_MEASURED',
        training='NOT_RUN',reward_advantage='NOT_CHANGED_NOT_USED',
        production_active='terminal-node-regret-grpo-readable-v8'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=['terminal','window'],default='terminal')
    parser.add_argument('--indices',default='all');parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();identities=inputs(args.mode)
    requested=list(range(100)) if args.indices=='all' else list(map(int,args.indices.split(',')))
    assert len(requested)==len(set(requested)) and all(0<=i<100 for i in requested)
    selected=[i for i in requested if i in identities]
    config=dict(mode=args.mode,requested_indices=requested,measured_indices=selected,
        missing_references=[i for i in requested if i not in identities],workers=args.workers,
        construction_seconds=60,reaudit_seconds=180,max_nodes=100000,
        metric_time_budget='NO_INTERNAL_TIME_LIMIT',epsilon=EPS,tie_tolerance=TOL,
        S='current-node true-info regret of reoptimized per-item-omitted forest strategy',
        omitted_policy_remaining_ties='uniform; conditional diagnostic, not tie-invariant claim',
        S_entry_weight='frozen-reference counterfactual likelihood, excluding focal past choices',
        zero_CF_S=None, own_information_retained='public/own preferences, rules, goals, current physical state, all other history/answers',
        scope='Research only; no selection, model, D, prompt or training change')
    snapshot(args.output,config,{i:identities[i] for i in selected})
    pool=parents();rows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        pending=[executor.submit(worker,i,pool[i],identities[i],args.mode,args.output) for i in selected]
        for future in as_completed(pending):
            rows.append(future.result());rows.sort(key=lambda r:r['index']);write(args.output/'results.json',rows)
    write(args.output/'COMPLETE.json',dict(requested=len(requested),measured=sum(r['status']=='measured' for r in rows),
        missing_references=config['missing_references'],errors=[r['index'] for r in rows if r['status']!='measured'],
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),results_sha256=sha(args.output/'results.json')))


if __name__=='__main__': main()
