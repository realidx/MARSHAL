"""Exact fixed-reference omission profiles on existing three-player candidates.

All focal actions are retained. Only opponent branches with exactly zero
counterfactual mass in every supported world may receive zero-contribution
stubs. These are not heuristic terminal leaves. Legacy labels/certificates
are hash checked; native unpruned forests verify the sparse implementation.
"""
from new import qs_action_profile_20261104 as m
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from functools import lru_cache
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time
from types import SimpleNamespace

import numpy as np
from new.A2H2_structure_20261026 import IndexedReference, canonical_geometry
from training.b_sft.shared_teacher import Entry
from new.node_qs_audit_v1_20261023.metrics import Observations

VERSION='candidate-qs-profiles-sparse-v1'
REG=m.ROOT/'examples/strategic_slices/versions/candidate_qs_profiles_v1_20261104/SNAPSHOT.json'
BASE=m.ROOT/'new/three_player_complexity_v1_20261023'
REMOTE='runtime/new/structure_pool_v1_20261026/'
REMOTE_RUN=REMOTE+'remote_remaining18_runtime_v4_20261029/'
CRITICAL=('training/b_sft/decision_policy.py','training/b_sft/shared_teacher.py',
          'training/b_sft/social_private_teacher.py','training/b_sft/preference_contract.py',
          'training/strategic_slices/bounded.py','training/strategic_slices/equilibrium.py',
          'new/strategic_game_v1_20261021/rules.py')


def digest(data):return hashlib.sha256(data).hexdigest()
def identity(path):return dict(path=str(Path(path).relative_to(m.ROOT)),sha256=m.sha(path))


def source_check(snapshot):
    return {p:dict(saved=snapshot['source_hashes'][p],current=m.sha(m.ROOT/p),
        matches=snapshot['source_hashes'][p]==m.sha(m.ROOT/p))for p in CRITICAL}


def inventory():
    tasks=[];provenance={}
    for arm,run_name,reload_name in [('H2','local_H2_33_v1','local_H2_reload_v1'),
                                    ('A2H2','local_A2H2_33_v1','local_A2H2_reload_v1')]:
        run=BASE/run_name;reload=BASE/reload_name
        complete=json.loads((run/'COMPLETE.json').read_text())
        assert m.sha(run/'results.json')==complete['results_sha256']
        assert m.sha(run/'pipeline_snapshot.json')==complete['pipeline_snapshot_sha256']
        snap=json.loads((run/'pipeline_snapshot.json').read_text());critical=source_check(snap)
        assert all(x['matches']for x in critical.values()),critical
        jobs={j['index']:j for j in json.loads((run/'jobs.json').read_text())}
        reload_results=json.loads((reload/'results.json').read_text())
        audited={}
        for record in reload_results:
            assert record['status']=='independently_reloaded'
            req=reload/Path(record['result_path']).parent/'request.json'
            audited[record['index']]=json.loads(req.read_text())['reference_sha256']
        provenance[arm]=dict(run=identity(run/'pipeline_snapshot.json'),results=identity(run/'results.json'),
            jobs=identity(run/'jobs.json'),reload=identity(reload/'results.json'),critical_sources=critical)
        for result in json.loads((run/'results.json').read_text()):
            job=jobs[result['index']];folder=run/Path(result['result_path']).parent
            task=dict(key=f'{arm}-{job["original_index"]}',arm=arm,index=job['index'],
                original_index=job['original_index'],job=job,result=result,
                source=dict(result=identity(folder/'result.json')),
                available=result.get('labels')=='MEASURED')
            if task['available']:
                assert audited[result['index']]==result['reference_sha256']
                for file,key in [('reference.npz','reference_sha256'),('labels.jsonl.gz','labels_sha256')]:
                    path=folder/file;assert m.sha(path)==result[key]
                    task['source'][file]=identity(path)
            tasks.append(task)
    bundle=m.ROOT/'new/structure_pool_remote_results_20261029'
    archive=bundle/'results.tar.gz';manifest=json.loads((bundle/'MANIFEST.json').read_text())
    assert m.sha(archive)==manifest['archive']['sha256']
    expected={r['path']:r for r in manifest['files']}
    with tarfile.open(archive)as tar:
        def read(name):
            data=tar.extractfile(name).read();assert digest(data)==expected[name]['sha256'];return data
        remote=json.loads(read(REMOTE_RUN+'results.json'))
        remote_snap=json.loads(read(REMOTE_RUN+'pipeline_snapshot.json'))
        remote_reload=json.loads(read(REMOTE+'remote_reload18_runtime_v4_20261029/results.json'))
        assert all(r['status']=='independently_reloaded'for r in remote_reload)
        assert {r['index']for r in remote_reload}=={r['index']for r in remote if r.get('labels')=='MEASURED'}
        local=m.ROOT/'new/structure_pool_v1_20261026/local_pilot_v1'
        local_results=json.loads((local/'results.json').read_text())
        jobs=list(map(json.loads,(local.parent/'raw_v1/parents.jsonl').read_text().splitlines()))
        critical=source_check(remote_snap);assert all(x['matches']for x in critical.values()),critical
        provenance['structure24']=dict(archive=identity(archive),manifest=identity(bundle/'MANIFEST.json'),
            pool=identity(local.parent/'raw_v1/parents.jsonl'),local_snapshot=identity(local/'pipeline_snapshot.json'),
            remote_snapshot_sha256=digest(read(REMOTE_RUN+'pipeline_snapshot.json')),critical_sources=critical)
        results={r['index']:r for r in local_results+remote};assert len(results)==24
        for job in jobs:
            result=results[job['index']]
            task=dict(key=f'structure24-{job["index"]}',arm='structure24',index=job['index'],
                original_index=None,job=job,result=result,source={},available=result.get('labels')=='MEASURED')
            if task['available']:
                for file,key in [('reference.npz','reference_sha256'),('labels.jsonl.gz','labels_sha256')]:
                    if job['index']<6:
                        path=local/Path(result['result_path']).parent/file
                        assert m.sha(path)==result[key];task['source'][file]=identity(path)
                    else:
                        name=REMOTE_RUN+str(Path(result['result_path']).parent/file)
                        assert digest(read(name))==result[key]
                        task['source'][file]=dict(archive=str(archive.relative_to(m.ROOT)),member=name,sha256=result[key])
            tasks.append(task)
    assert len(tasks)==90 and sum(t['available']for t in tasks)==83
    return tasks,provenance


def bytes_for(source,cache=None):
    if 'path'in source:
        data=(m.ROOT/source['path']).read_bytes()
    else:
        with tarfile.open(m.ROOT/source['archive'])as tar:data=tar.extractfile(source['member']).read()
    assert digest(data)==source['sha256'];return data


class SparseNative:
    def __init__(self,indexed,cache_nodes):
        self.indexed=indexed;self.rules=indexed.rules;self.flat=indexed.flat
        self.worlds=self.rules.worlds;self.w=len(self.worlds);self.n=self.rules.spec.n_players
        self.types=np.array(self.worlds,dtype=float)
        self.locate=lru_cache(maxsize=cache_nodes)(indexed.find)
        self.expand=lru_cache(maxsize=cache_nodes)(self._expand)

    def _expand(self,global_index):
        node,offset=self.locate(global_index);actions=self.rules.actions(node)
        pos=global_index+1;off=offset+len(actions)*self.w;children=[]
        for action in actions:
            child=self.rules._apply(node,action);nn,nf=self.indexed.stats(child)
            children.append((child,pos,off));pos+=nn;off+=nf
        return node,offset,actions,children

    def forest(self,roots,focal,prune=True):
        tree=SimpleNamespace(worlds=self.worlds,w=self.w,n=self.n,entries=[],policy=[])
        stats=Counter();new_roots={};original={}
        def grow(node,gi,offset,mass):
            i=len(tree.entries);tree.entries.append(None);tree.policy.append(None)
            original[i]=gi
            if node.state.is_terminal:
                value=np.einsum('wpg,g->wp',self.types,node.state.goal_satisfaction())
                tree.entries[i]=Entry(node,None,(),(),value);stats['native_terminal_leaves']+=1;return i
            if prune and not np.any(mass>0):
                assert np.all(mass==0)
                tree.entries[i]=Entry(node,None,(),(),np.zeros((self.w,self.n)))
                stats['exact_zero_mass_stubs']+=1;return i
            _,_,actions,children=self.expand(gi);actor=self.rules.actor(node)
            policy=self.flat[offset:offset+len(actions)*self.w].reshape(len(actions),self.w)
            assert np.min(policy)>=0
            child_ids=[]
            for ai,(child,cgi,coff)in enumerate(children):
                cmass=mass if actor==focal else mass*policy[ai]
                child_ids.append(grow(child,cgi,coff,cmass))
            tree.entries[i]=Entry(node,actor,actions,tuple(child_ids));tree.policy[i]=policy
            stats['focal_action_branches_retained'if actor==focal else'opponent_action_branches']+=len(actions)
            return i
        for gi,mass in roots.items():
            node,offset=self.locate(gi);i=grow(node,gi,offset,mass)
            new_roots[i]=mass;original[i]=gi
        stats['retained_nodes']=len(tree.entries)
        stats['native_equivalent_nodes']=sum(self.indexed.stats(self.locate(i)[0])[0]for i in roots)
        mapping={original[i]:i for i in new_roots}
        return tree,new_roots,mapping,dict(stats)


def add_profile(row,item,qm,qtrue,pm,omitted_best):
    q=np.array(row['Q']);pf=np.zeros(len(q));pf[row['optimal']]=1/len(row['optimal'])
    row['canonical_full_action_probabilities']=pf.tolist()
    item.update(Q_omitted_subjective=qm.tolist(),Q_omitted_evaluated_true=qtrue.tolist(),
        omitted_action_probabilities=pm.tolist(),omitted_protocol_optimal=list(map(int,omitted_best)),
        omitted_own_optimal=np.flatnonzero(qm>=qm.max()-m.TOL).tolist())
    item.update(m.distribution_stats(q,pf,pm,item['S']))
    assert item['own_future_loss']>=-m.EPS
    assert abs(float(pm@(q-qtrue))-item['own_future_loss'])<m.EPS
    item['relative_Q_change']=((qm.max()-qm)-(q.max()-q)).tolist()
    item['relative_Q_change_Linf']=float(np.abs(item['relative_Q_change']).max())
    item['common_own_optimal']=sorted(set(row['own_optimal'])&set(item['omitted_own_optimal']))
    item['common_protocol_optimal']=sorted(set(row['optimal'])&set(item['omitted_protocol_optimal']))


def worker(task,out,config):
    start=time.monotonic();folder=out/'cases'/task['key'];folder.mkdir(parents=True)
    result={k:task[k]for k in ('key','arm','index','original_index')};result['status']='started'
    m.write(folder/'request.json',dict(task=task,config=config))
    try:
        reference=bytes_for(task['source']['reference.npz']);raw=bytes_for(task['source']['labels.jsonl.gz'])
        rows=list(map(json.loads,gzip.decompress(raw).splitlines()))
        assert len(rows)==task['result']['summary']['counterfactual']['contexts']
        assert all(r['counterfactual_mass']>0 for r in rows)
        with np.load(io.BytesIO(reference))as data:flat=data['probabilities']
        indexed=IndexedReference(task['job'],flat);assert indexed.nodes==task['result']['nodes']
        sparse=SparseNative(indexed,config['native_cache_nodes'])
        lookup={};fake=SimpleNamespace(entries={},worlds=indexed.rules.worlds)
        for row in rows:
            gi=row['node']
            pf=np.zeros(len(row['Q']));pf[row['optimal']]=1/len(row['optimal'])
            row['canonical_full_action_probabilities']=pf.tolist()
            if gi not in fake.entries:
                node,_=sparse.locate(gi);actions=indexed.rules.actions(node)
                fake.entries[gi]=SimpleNamespace(node=node,actions=actions)
            assert [a.to_dict()for a in fake.entries[gi].actions]==row['actions']
            lookup[row['node'],row['cell']]=deepcopy(row['S_items'])
        tasks=defaultdict(list);observers={p:Observations(fake,p)for p in range(indexed.rules.spec.n_players)}
        for row in rows:
            for item in row['S_items']:
                mask=tuple(item['omitted']);key=observers[row['actor']].key(row['node'],row['world_ids'][0],mask)
                tasks[row['actor'],mask,key].append((row,item))
        operations=Counter();checks=[]
        for (focal,mask,key),members in tasks.items():
            assert all(item['full_contexts']==len(members)for _,item in members)
            if len(members)==1:
                row,item=members[0];assert item['S']==0
                q=np.array(row['Q']);pf=np.zeros(len(q));pf[row['optimal']]=1/len(row['optimal'])
                add_profile(row,item,q,q,pf,row['optimal']);operations['singleton_forests']+=1;continue
            roots={}
            for row,item in members:
                roots.setdefault(row['node'],np.zeros(indexed.w))[row['world_ids']]=row['counterfactual_mass']*np.array(row['posterior'])
            tree,local_roots,mapping,counts=sparse.forest(roots,focal)
            result_dp=m.forest_with_actions(tree,focal,local_roots,omitted=mask,observations=Observations(tree,focal))
            operations.update(counts);operations['nontrivial_forests']+=1
            total=sum(x.sum()for x in roots.values())
            subjective=sum(np.einsum('awp,w->ap',result_dp['root_action_values'][mapping[gi]],mass)
                for gi,mass in roots.items())/total
            best=m.optimal_indices(subjective,focal,tree.entries[next(iter(local_roots))].actions,m.TOL)
            if (len(checks)<config['unpruned_checks_per_case'] and counts['exact_zero_mass_stubs']>0
                    and counts['native_equivalent_nodes']<=config['unpruned_max_nodes']):
                full,full_roots,full_map,full_counts=sparse.forest(roots,focal,prune=False)
                independently=m.forest_with_actions(full,focal,full_roots,omitted=mask,observations=Observations(full,focal))
                for gi,mass in roots.items():
                    ids=np.flatnonzero(mass>0);a=mapping[gi];b=full_map[gi]
                    np.testing.assert_allclose(result_dp['root_action_values'][a][:,ids],independently['root_action_values'][b][:,ids],atol=1e-9,rtol=0)
                    np.testing.assert_allclose(result_dp['root_policy'][a][:,ids],independently['root_policy'][b][:,ids],atol=1e-9,rtol=0)
                checks.append(dict(focal=focal,omitted=list(mask),roots=list(roots),sparse_nodes=counts['retained_nodes'],
                    native_nodes=full_counts['retained_nodes'],all_root_action_values_and_policies_match=True))
            for row,item in members:
                li=mapping[row['node']];ids=row['world_ids'];posterior=np.array(row['posterior'])
                qtrue=np.einsum('aw,w->a',result_dp['root_action_values'][li][:,ids,focal],posterior)
                own=float(posterior@result_dp['values'][li][ids,focal])
                pm=result_dp['root_policy'][li][:,ids[int(np.flatnonzero(posterior>0)[0])]]
                assert abs((max(row['Q'])-own)-item['S'])<m.EPS,(task['key'],row['node'],mask)
                np.testing.assert_allclose(pm,item['omitted_action_probabilities'],atol=1e-9,rtol=0)
                np.testing.assert_allclose(pm@qtrue,own,atol=1e-9,rtol=0)
                add_profile(row,item,subjective[:,focal],qtrue,pm,best)
        for row in rows:
            for item,prior in zip(row['S_items'],lookup[row['node'],row['cell']],strict=True):
                assert item['S']==prior['S']and item['omitted']==prior['omitted']
            # Diagnostic skeleton count only; never merge distinct histories or beliefs.
            node=fake.entries[row['node']].node;state=node.state
            row['physical_skeleton']=json.dumps(dict(actor=row['actor'],turn=row['turn'],phase=row['phase'],
                commitments=state.snapshot_commitments(),query_used=state.query_used,offer_used=state.offer_used,
                pending=None if node.pending is None else node.pending.to_dict()),sort_keys=True,separators=(',',':'))
        summary=m.profile_summary(rows)
        summary['zero_CF_contexts']=task['result']['summary']['zero_CF_cells']
        for prop,predicate in [('positive_S',lambda r:any(x['S']>m.EPS for x in r['S_items'])),
                ('relative_Q_changed',lambda r:any(x['relative_Q_change_Linf']>m.EPS for x in r['S_items'])),
                ('distribution_changed',lambda r:any(x['policy_total_variation']>m.EPS for x in r['S_items']))]:
            selected=[r for r in rows if predicate(r)]
            summary[prop+'_physical_skeletons']=len({r['physical_skeleton']for r in selected})
            summary[prop+'_reference_mass']=sum(r['reference_mass']for r in selected)
        summary['reference_mass']=sum(r['reference_mass']for r in rows)
        with gzip.open(folder/'labels.jsonl.gz','wt')as stream:
            for row in rows:stream.write(json.dumps(row,separators=(',',':'))+'\n')
        features=dict(actions=indexed.rules.spec.n_actions_per_player,goals=len(indexed.rules.spec.goals),
            typed_geometry=canonical_geometry(task['job']['raw'],True),
            public_all_want=[p for p,types in indexed.rules.catalogues.items()if len(types)==1 and all(v==1 for v in types[0])])
        result.update(status='measured',summary=summary,operations=dict(operations),unpruned_checks=checks,
            structural_features=features,legacy_all_S_and_policies_match=True,Q='REUSED_HASH_VERIFIED_LEGACY_FULL_Q',
            inherited_reference_certificate=task['result']['certificate'],reference_sha256=task['result']['reference_sha256'],
            labels_sha256=m.sha(folder/'labels.jsonl.gz'))
    except Exception as exc:
        import traceback
        result.update(status='error',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    result['elapsed_seconds']=time.monotonic()-start;m.write(folder/'result.json',result)
    print(dict(key=task['key'],status=result['status'],seconds=round(result['elapsed_seconds'],2),error=result.get('error')),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--keys',default='all');parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();args.output=args.output.resolve()
    all_tasks,provenance=inventory();available={t['key']:t for t in all_tasks if t['available']}
    keys=list(available)if args.keys=='all'else args.keys.split(',')
    assert len(keys)==len(set(keys)) and all(k in available for k in keys)
    config=dict(operation='Supplement existing candidate labels with exact fixed-reference sparse omission profiles',
        keys=keys,workers=args.workers,native_cache_nodes=8192,unpruned_checks_per_case=3,unpruned_max_nodes=2000,
        prune='Only exact zero incoming counterfactual mass at opponents; retain every focal action; no probability tolerance',
        endpoint='Native terminal; zero-contribution stubs are NOT heuristic/truncated terminal evaluations',
        full_Q='Reuse old labels with hash and prior independent reference audit; no global BR recomputation',
        S='Every old omission S and saved root policy must match new DP',
        certificates='Reuse unchanged saved certificates and critical source hashes; no new equilibrium search/full-tree reaudit',
        time_limits='NO_NEW_INTERNAL_SOLVER_OR_METRIC_LIMIT',numerical_epsilon=m.EPS,tie_tolerance=m.TOL,
        D='NOT_MEASURED',selection800='NOT_RUN',new_parents='NOT_GENERATED',production='UNCHANGED_V8',
        input_provenance=provenance,
        selected_data_identity={k:dict(id=available[k]['job']['id'],
            raw_sha256=digest(json.dumps(available[k]['job']['raw'],sort_keys=True,separators=(',',':')).encode()),
            source=available[k]['source'])for k in keys})
    m.VERSION,m.REG=VERSION,REG;m.snapshot(args.output,config,{})
    m.write(args.output/'INVENTORY.json',dict(all_candidates=all_tasks,provenance=provenance,
        requested=90,available=83,missing=[t['key']for t in all_tasks if not t['available']]))
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        futures=[executor.submit(worker,available[k],args.output,config)for k in keys]
        for future in as_completed(futures):
            results.append(future.result());results.sort(key=lambda r:r['key']);m.write(args.output/'results.json',results)
    m.write(args.output/'COMPLETE.json',dict(requested=len(keys),measured=sum(r['status']=='measured'for r in results),
        errors=[r['key']for r in results if r['status']!='measured'],results_sha256=m.sha(args.output/'results.json'),
        inventory_sha256=m.sha(args.output/'INVENTORY.json'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
