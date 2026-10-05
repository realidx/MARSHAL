"""Generate a multi-entrance candidate pool from full initial terminal oracles."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.build import sample_parent,structural_family
from training.strategic_slices.common import digest,file_hash,write_json as _write_json,save_reference
from training.strategic_slices.diagnose_bounded import count_bounded_nodes
from training.strategic_slices.equilibrium import certify_policy
from training.strategic_slices.oracle_consistent import measure_parent,CONTRACT,canonical_parent
from training.strategic_slices.terminal_candidates import restore_reference
from examples.strategic_slices.retry_terminal_budgets import classify


def write_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    _write_json(temporary,value);temporary.replace(path)


def identity(raw):
    return digest({key:raw[key] for key in ('game','type_catalogues','background_prior')})[:24]


def prepare(out):
    source=Path('new/local_data/strategic_slices_terminal_candidates_unified_v1')
    parents={r['id']:r for r in map(json.loads,(source/'parents.jsonl').read_text().splitlines())}
    refs=[r for r in map(json.loads,(source/'references.jsonl').read_text().splitlines()) if not r['history']]
    all_rows=[json.loads(line) for line in (source/'candidates.jsonl').read_text().splitlines()]
    jobs=[];seen=set()
    for ref in refs:
        parent=parents[ref['parent_id']];raw=parent['raw'];pid=identity(raw)
        if pid in seen:continue
        seen.add(pid)
        controls=[r for r in all_rows if r['parent_id']==parent['id'] and (r['information_channels']['entry_and_future_public_history'] or 0)>1e-6]
        jobs.append(dict(raw=raw,parent_id=pid,origin=parent['origin'],calibration_family=parent.get('calibration_family',False),
            reuse=dict(record=ref,file=str(source/ref['file']),sha256=file_hash(source/ref['file'])),collective_controls=controls))
    # Declared small multi-round experiment before short-parent expansion.
    for i in range(12):
        raw=sample_parent(2026101100+i,2,rounds=2)
        jobs.append(dict(raw=raw,parent_id=identity(raw),origin=dict(kind='native-random',seed=2026101100+i,rounds=2),solver_seconds=120))
    # A fixed, independent pool. Select by recorded order and predeclared caps, not timing.
    for i in range(200):
        n=2 if i%2==0 else 3;raw=sample_parent(2026101200+i,n,rounds=1)
        jobs.append(dict(raw=raw,parent_id=identity(raw),origin=dict(kind='native-random',seed=2026101200+i,rounds=1),solver_seconds=30))
    for i,job in enumerate(jobs):job['index']=i
    write_json(out/'jobs.json',jobs)
    write_json(out/'config.json',dict(contract=CONTRACT,target_parents=100,target_players={'2':50,'3':50},
        max_parents_per_family=8,max_windows_per_parent=16,min_distinct_histories=2,entrance_limit=24,
        max_nodes=160000,solver_seconds_short=30,solver_seconds_multiround=120,
        note='No D. Reused parents have initial-root references only. New private supports and utility rules are unmodified. Fixed candidate order; failures have no C/S.'))


def worker(out,index):
    job=json.loads((out/'jobs.json').read_text())[index];raw=job['raw'];pid=job['parent_id'];start=time.monotonic()
    result=dict(index=index,parent_id=pid,status='started',oracle_label=None)
    folder=out/'cases'/str(index);folder.mkdir(parents=True,exist_ok=True);write_json(folder/'raw.json',raw)
    try:
        short=len(raw['game']['round_robin'])==raw['game']['n_players']
        if index>=49 and short and (out/'HOLD_SHORT_EXPANSION').exists() and not (folder/'reference.npz').exists():
            result.update(status='deferred_scope_discussion',players=raw['game']['n_players'])
            write_json(folder/'result.json',result);return
        if index>=49 and short and not (folder/'reference.npz').exists():
            from examples.strategic_slices.package_oracle_consistent import selection
            counts=selection(out)[2]
            if counts[raw['game']['n_players']]>=50:
                result.update(status='not_attempted_player_quota',players=raw['game']['n_players'])
                write_json(folder/'result.json',result);return
        rules=PrivateInvestigationRules(raw)
        result.update(players=rules.spec.n_players,worlds=len(rules.worlds),total_proposals=len(rules.spec.round_robin),family=structural_family(raw['game']))
        local=folder/'result.json'
        if local.exists() and (folder/'reference.npz').exists():
            previous=json.loads(local.read_text())
            if 'certificate' in previous:
                job['reuse']=dict(record=dict(history=[],certificate=previous['certificate']),
                    file=str(folder/'reference.npz'),sha256=file_hash(folder/'reference.npz'))
        if 'reuse' in job:
            saved=job['reuse'];assert file_hash(saved['file'])==saved['sha256']
            tree=restore_reference(raw,saved['record'],saved['file'])
            tree.deadline=time.monotonic()+120
            check=certify_policy(tree)
            if check is None:raise ValueError('Reused initial reference failed independent recertification')
            result['reused_reference_independently_certified']=True
        else:
            # A renamed copy of an already verified earlier parent cannot add
            # coverage. Detect it before constructing/solving another tree.
            canonical=canonical_parent(raw)
            for prior_job in json.loads((out/'jobs.json').read_text())[:index]:
                prior_path=out/f"cases/{prior_job['index']}/result.json"
                if not prior_path.exists():continue
                prior=json.loads(prior_path.read_text())
                if prior.get('status')!='verified':continue
                if canonical_parent(prior_job['raw'])==canonical:
                    result.update(status='known_isomorphic_parent',duplicate_of=prior_job['parent_id'],
                                  seconds=time.monotonic()-start)
                    write_json(folder/'result.json',result);return
            count=count_bounded_nodes(rules,rules.initial(),3)['unfolded_public_history_nodes']
            result['nodes']=count
            options=job.get('solver_options',{})
            max_nodes=options.get('max_nodes',160000)
            result['solver_options']=dict(seconds=job['solver_seconds'],**options)
            if count>max_nodes:
                result.update(status='node_budget',reason=f'{count} > {max_nodes}');write_json(folder/'result.json',result);return
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=3,
                max_nodes=max_nodes,seconds=job['solver_seconds'],
                large_tree_ordered_sweeps=options.get('large_tree_ordered_sweeps',2),
                max_joint_cells=options.get('max_joint_cells',4096),
                max_joint_evaluations=options.get('max_joint_evaluations',160)).solve()
        result.update(nodes=len(tree.entries),solve_restore_seconds=time.monotonic()-start)
        tree.deadline=time.monotonic()+240
        audit=tree.audit_native();assert audit['cutoff_leaves']==0
        assert tree.entries[0].node.state.turn_index==0
        assert all(e.node.state.is_terminal for e in tree.entries if e.actor is None)
        save_reference(folder/'reference.npz',tree)
        result.update(certificate=tree.certificate,native_audit=audit,reference_sha256=file_hash(folder/'reference.npz'))
        result['status']='certified';write_json(folder/'result.json',result)
        rows,selection=measure_parent(tree,pid,limit=24,cap=16-len(job.get('collective_controls',[])))
        for original in job.get('collective_controls',[]):
            row=deepcopy(original);row['parent_id']=pid
            row['id']=digest((pid,'collective',original['id']))[:24]
            row['entrance_id']=digest((pid,'collective',[m['root_index'] for m in row['members']]))[:24]
            row['entry_kind']='oracle-reach-collective';row['decision_kind']='proposal'
            row.pop('reference_id',None);row.pop('split',None);row.pop('family',None)
            row['calibration_control']=True;rows.append(row)
        distinct_histories={tuple(m['history']) if m['history_encoding']=='native-action-indices' else json.dumps(m['history'],sort_keys=True) for row in rows for m in row['members']}
        if len(rows)<2 or len(distinct_histories)<2:
            result.update(status='insufficient_entrances',selection=selection,candidates=[])
        else:
            result.update(status='verified',selection=selection,candidates=rows,selection_version='ego-k-coverage-v2')
        result['seconds']=time.monotonic()-start
        result.pop('oracle_label',None)
    except Exception as exc:
        was_certified=result.get('status')=='certified'
        result.update(status='measurement_failed' if was_certified else classify(str(exc)),reason=str(exc),seconds=time.monotonic()-start)
        traceback.print_exc()
    write_json(folder/'result.json',result)
    print(index,result['status'],result.get('seconds'),len(result.get('candidates',[])),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker',type=int);p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=0)
    p.add_argument('--until-target',action='store_true')
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
    if not (out/'jobs.json').exists():prepare(out)
    if a.prepare_only:return
    if a.worker is not None:worker(out,a.worker);return
    jobs=json.loads((out/'jobs.json').read_text());indices=list(range(a.start,min(len(jobs),a.start+a.count if a.count else len(jobs))))
    def launch(index):
        folder=out/'cases'/str(index);folder.mkdir(parents=True,exist_ok=True)
        if (folder/'result.json').exists():
            old=json.loads((folder/'result.json').read_text())
            if old['status'] not in ('started','certified','deferred_scope_discussion','pending_retry') and not (old['status']=='verified' and old.get('selection_version')!='ego-k-coverage-v2'):return old
        with (folder/'worker.log').open('w') as log:
            try:
                subprocess.run([sys.executable,'-m','examples.strategic_slices.build_oracle_consistent','--output',str(out),'--worker',str(index)],
                    stdout=log,stderr=subprocess.STDOUT,check=True,timeout=jobs[index].get('worker_seconds',360),
                    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
                result=json.loads((folder/'result.json').read_text())
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
                result=dict(index=index,status='worker_failure',reason=str(exc),oracle_label=None)
                write_json(folder/'result.json',result)
        print(index,result['status'],result.get('players'),len(result.get('candidates',[])),flush=True);return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        if a.until_target:
            from examples.strategic_slices.package_oracle_consistent import selection
            for start in range(0,len(indices),4):
                eligible=selection(out)[0]
                config=json.loads((out/'config.json').read_text())
                if len(eligible)>=100 and sum(r['total_proposals']>r['players'] for _,r in eligible)>=config.get('min_multiround_parents',0):break
                list(pool.map(launch,indices[start:start+4]))
                accepted,_,counts=selection(out)
                print('target progress',len(accepted),dict(counts),flush=True)
        else:list(pool.map(launch,indices))
    results=[json.loads(f.read_text()) for f in sorted((out/'cases').glob('*/result.json'),key=lambda f:int(f.parent.name))]
    write_json(out/'summary.json',dict(results=results,statuses=dict(Counter(r['status'] for r in results))))

if __name__=='__main__':main()
