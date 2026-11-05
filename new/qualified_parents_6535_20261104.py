"""Versioned evidence-based65/35 parent curation; no model/D/800 selection."""
from new import qs_action_profile_20261104 as m
from new import candidate_qs_profiles_20261104_v3 as sparse_impl
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import lil_matrix
from new.A2H2_structure_20261026 import IndexedReference,canonical_geometry
from new.node_qs_audit_v1_20261023.metrics import Observations,contingent_values
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.b_sft.social_private_teacher import observed_slots
from training.strategic_slices.equilibrium import _reach
from training.strategic_slices.oracle_consistent import canonical_parent

VERSION='qualified-parent-pool-65-35-v1'
REG=m.ROOT/'examples/strategic_slices/versions/qualified_parents_65_35_v1_20261104/SNAPSHOT.json'
CAND=m.ROOT/'new/candidate_qs_profiles_20261104_runs'
ORIG=m.ROOT/'new/qs_action_profile_20261104_runs'
QUOTAS={(2,'information'):40,(2,'valuation'):15,(2,'planning'):10,
        (3,'information'):20,(3,'valuation'):5,(3,'planning'):10}


def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x):return hashlib.sha256(stable(x).encode()).hexdigest()
def ident(path):return dict(path=str(Path(path).relative_to(m.ROOT)),sha256=m.sha(path))
def source_bytes(x):return sparse_impl.base.bytes_for(x)


def sources():
    out=[];parents=m.parents()
    old_results={r['index']:r for r in json.loads((m.OLD/'results.json').read_text())}
    original_refs=m.legacy.inputs('terminal')
    for name in ['pilot_v1','remaining_v1']:
        run=ORIG/name;complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        for result in json.loads((run/'results.json').read_text()):
            index=result['index'];p=parents[index];reference=original_refs[index]
            labels=run/'cases'/str(index)/'labels.jsonl.gz';assert m.sha(labels)==result['labels_sha256']
            assert m.sha(reference['path'])==reference['sha256']
            job=dict(p,original_index=index)
            out.append(dict(key=f'original{result["players"]}P-{index}',players=result['players'],
                origin_group=f'original-{index}',job=job,
                source=dict(reference=ident(reference['path']),labels=ident(labels)),
                inherited_result=old_results[index],profile_result=result))
    inv=json.loads((CAND/'pilot_v3/INVENTORY.json').read_text());tasks={x['key']:x for x in inv['all_candidates']}
    for name in ['pilot_v3','remaining_v3']:
        run=CAND/name;complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        for result in json.loads((run/'results.json').read_text()):
            task=tasks[result['key']];labels=run/'cases'/task['key']/'labels.jsonl.gz'
            assert m.sha(labels)==result['labels_sha256']
            origin=(f'structure-pair-{task["job"]["pair_id"]}'if task['arm']=='structure24'
                    else f'original-{task["original_index"]}')
            out.append(dict(key=task['key'],players=3,origin_group=origin,job=task['job'],
                source=dict(reference=task['source']['reference.npz'],labels=ident(labels)),
                inherited_result=task['result'],profile_result=result))
    assert len(out)==182
    for x in out:
        raw=x['job']['raw'];x['canonical_id']=canonical_parent(raw)
        x['raw_sha256']=digest(raw);x['geometry']=canonical_geometry(raw,True)
    return out


def read_rows(source):
    data=source_bytes(source['source']['labels'])
    return [r for line in gzip.decompress(data).splitlines()if(r:=json.loads(line))['counterfactual_mass']>0]


def valuation_witness(row):
    if row['span']<=m.EPS or max(row['S_private'],row['S_history'])>m.EPS:return None
    for item in row['S_items']:
        if (item['relative_Q_change_Linf']>m.EPS and item['S']<=m.EPS
                and item['own_current_loss']<=m.EPS and item['common_protocol_optimal']
                and (item.get('response_secondary_loss')or 0)<=m.EPS):
            return dict(kind='relative_action_values_change_without_canonical_loss',omitted=item['omitted'],
                Q_full=row['Q'],Q_omitted=item['Q_omitted_subjective'],relative_change=item['relative_Q_change'],
                full_optimal=row['optimal'],omitted_optimal=item['omitted_protocol_optimal'],
                common_optimal=item['common_protocol_optimal'],S=item['S'],current_loss=item['own_current_loss'])
    return None


def planning_witness(row):
    # This is a counterexample to explicit myopic baselines, not a new reward.
    if (row['phase']!='proposal' or row['query_gap']is None or row['query_gap']>=-m.EPS
            or row['span']<=m.EPS or max(row['S_private'],row['S_history'])>m.EPS):return None
    actions=row['actions'];q=np.array(row['Q']);offers={x['action']:x for x in row.get('offers',[])}
    if len(offers)<2:return None
    nonquery=[i for i,a in enumerate(actions)if a.get('action')!='INVESTIGATE']
    best=[i for i in row['optimal']if i in nonquery]
    if not best:return None
    pas=next(i for i,a in enumerate(actions)if a.get('action')=='PASS')
    base=float(row['immediate_child_utility'][pas]);optimistic=np.full(len(actions),base)
    roundtrip=np.full(len(actions),base)
    for ai,offer in offers.items():
        optimistic[ai]=offer['static_accepted_utility']
        roundtrip[ai]=base+offer['acceptance']*(offer['static_accepted_utility']-base)
    def myopic_info(values):
        value=max(values[i]for i in nonquery)
        ids=[i for i in nonquery if values[i]>=value-m.TOL]
        return ids,float(q.max()-max(q[i]for i in ids))
    optimistic_best,response_gap=myopic_info(optimistic)
    roundtrip_best,continuation_gap=myopic_info(roundtrip)
    route_response=response_gap>m.EPS and any(i in offers and offers[i]['acceptance']<1-m.EPS
        and abs(offers[i]['Q_accept']-offers[i]['Q_reject'])>m.EPS for i in optimistic_best)
    route_future=continuation_gap>m.EPS
    if not(route_response or route_future):return None
    return dict(kind='continuation_planning'if route_future else'opponent_response_planning',
        query_gap=row['query_gap'],optimal_nonquery=best,
        optimistic_accepted_utility=optimistic.tolist(),optimistic_best=optimistic_best,
        optimistic_terminal_regret=response_gap,one_turn_expected_utility=roundtrip.tolist(),
        one_turn_best=roundtrip_best,one_turn_terminal_regret=continuation_gap,
        no_single_item_own_omission_loss=True,
        explanation='Investigation legal and strictly worse; accounting for response or subsequent play changes the best action')


def row_rank(row):
    # Late short witnesses keep validation cheap; this is not task difficulty.
    return (row['reference_mass']<=0,-row['turn'],row['node'],row['cell'])


def make_sparse(source):
    with np.load(io.BytesIO(source_bytes(source['source']['reference'])))as data:flat=data['probabilities']
    indexed=IndexedReference(source['job'],flat)
    return sparse_impl.SparseNative(indexed,8192)


def omission_members(sparse,rows,target,mask):
    fake=SimpleNamespace(entries={},worlds=sparse.worlds);obs=Observations(fake,target['actor'])
    def key(row):
        i=row['node']
        if i not in fake.entries:
            node,_=sparse.locate(i);fake.entries[i]=SimpleNamespace(node=node,actions=sparse.rules.actions(node))
        return obs.key(i,row['world_ids'][0],mask)
    wanted=key(target);members=[]
    for row in rows:
        if row['actor']!=target['actor']or row['turn']!=target['turn']or row['phase']!=target['phase']or row['own_type']!=target['own_type']:continue
        if mask[0]=='private'and row['node']!=target['node']:continue
        item=next((x for x in row['S_items']if x['omitted']==list(mask)),None)
        if item is not None and key(row)==wanted:members.append((row,item))
    return members


def information_proof(sparse,rows,row,item):
    mask=tuple(item['omitted']);members=omission_members(sparse,rows,row,mask)
    assert len(members)==item['full_contexts']
    roots={}
    for r,_ in members:roots.setdefault(r['node'],np.zeros(sparse.w))[r['world_ids']]=r['counterfactual_mass']*np.array(r['posterior'])
    tree,local,mapping,stats=sparse.forest(roots,row['actor'])
    target=(mapping[row['node']],set(row['world_ids']))
    obs=Observations(tree,row['actor'])
    full=sequence_lp(tree,row['actor'],local,omitted=None,observations=obs)
    omitted=sequence_lp(tree,row['actor'],local,omitted=mask,observations=obs,target=target)
    total=sum(float(v.sum())for v in roots.values())
    full_expected=sum(r['counterfactual_mass']*max(r['Q'])for r,_ in members)/total
    assert abs(full['V_omitted_LP']-full_expected)<1e-7
    lower=max(row['Q'])-omitted['target_own_value_max']
    upper=max(row['Q'])-omitted['target_own_value_min']
    group_gain=full['V_omitted_LP']-omitted['V_omitted_LP']
    assert lower<=item['S']+1e-7<=upper+2e-7
    return dict(kind='independently_LP_verified_information_loss',omitted=list(mask),
        S=item['S'],S_lower=max(0.,float(lower)),S_upper=max(0.,float(upper)),
        full_group_value=full['V_omitted_LP'],omitted_group_value=omitted['V_omitted_LP'],
        group_gain=group_gain,full_LP=full,omitted_LP=omitted,forest_stats=stats,
        qualified=lower>m.EPS,scope='Same fixed reference; all own-optimal omitted policies, social relaxation; not cross-equilibrium')


def audit_worker(source,out):
    start=time.monotonic();folder=out/'cases'/source['key'];folder.mkdir(parents=True)
    record=dict(key=source['key'],players=source['players'],origin_group=source['origin_group'],
        canonical_id=source['canonical_id'],geometry=source['geometry'],status='started',roles={},source=source)
    try:
        rows=read_rows(source);record['contexts']=len(rows)
        assert len(rows)==source['profile_result']['summary']['contexts']
        counts=Counter();valuation=[];planning=[];positive=[]
        for row in rows:
            b=valuation_witness(row)
            if b:counts['valuation']+=1;valuation.append((row,b))
            c=planning_witness(row)
            if c:counts['planning']+=1;counts[c['kind']]+=1;planning.append((row,c))
            for item in row['S_items']:
                if item['S']>m.EPS:positive.append((row,item))
        for role,values in [('valuation',valuation),('planning',planning)]:
            if values:
                row,proof=min(values,key=lambda x:((x[1]['kind']!='continuation_planning')if role=='planning'else False,*row_rank(x[0])))
                record['roles'][role]=dict(witness=row,proof=proof)
        trials=[]
        if positive:
            sparse=make_sparse(source)
            # Diagnostic witness selection, never a model-difficulty ranking.
            ordered=sorted(positive,key=lambda x:(-x[1]['S'],*row_rank(x[0])))
            seen=set()
            for row,item in ordered:
                signature=(tuple(item['omitted']),row['node'],row['cell'])
                if signature in seen:continue
                seen.add(signature)
                try:proof=information_proof(sparse,rows,row,item)
                except Exception as exc:
                    trials.append(dict(node=row['node'],cell=row['cell'],omitted=item['omitted'],error=f'{type(exc).__name__}: {exc}'));continue
                trials.append(dict(node=row['node'],cell=row['cell'],omitted=item['omitted'],lower=proof['S_lower']))
                if proof['qualified']:
                    record['roles']['information']=dict(witness=row,proof=proof);break
                if len(trials)>=12:break
        record.update(status='audited',eligible_role_counts=dict(counts),information_trials=trials,
            exclusion_reason=None if record['roles']else'No witness passes the declared admission tests')
    except Exception as exc:
        import traceback
        record.update(status='error',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
    record['elapsed_seconds']=time.monotonic()-start;m.write(folder/'audit.json',record)
    print(dict(key=source['key'],status=record['status'],roles=list(record['roles']),seconds=round(record['elapsed_seconds'],2),error=record.get('error')),flush=True)
    return {k:record[k]for k in ('key','players','origin_group','canonical_id','geometry','status','elapsed_seconds')}|dict(
        roles=list(record['roles']),path=str((folder/'audit.json').relative_to(out)),sha256=m.sha(folder/'audit.json'),
        counts=record.get('eligible_role_counts',{}),error=record.get('error'))


def snapshot(out,config,input_ids):
    m.VERSION,m.REG=VERSION,REG
    config=dict(config,admission_epsilon=m.EPS,tie_tolerance=m.TOL,model_D='NOT_MEASURED',
        selection800='NOT_RUN',test='NOT_GENERATED',endpoint='NATIVE_TERMINAL',input_identity=input_ids)
    m.snapshot(out,config,{})


def audit(args):
    src=sources();snapshot(args.output,dict(operation='Declared witness admission audit',workers=args.workers,
        purpose_quota={f'{p}/{r}':n for(p,r),n in QUOTAS.items()},
        independent_LP='Existing sequence LP60s per optimization,1e-9 feasibility; conservative target-S bounds',
        information_witness_attempt_limit=12,information_acceptance='LP lower S>1e-8; no arbitrary utility cutoff',
        valuation_acceptance='Zero own S and current regret; relative Q change>1e-8; common protocol optimal; no secondary loss',
        planning_acceptance='Investigation legal and strictly suboptimal; explicit optimistic-response or one-turn baseline has terminal regret',
        witness_pick='Prefer continuation proof, reference-reachable then late; information maxS is verification only, not parent score'),
        {x['key']:dict(raw_sha256=x['raw_sha256'],source=x['source'])for x in src})
    m.write(args.output/'SOURCES.json',src);results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        pending=[executor.submit(audit_worker,x,args.output)for x in src]
        for future in as_completed(pending):
            results.append(future.result());results.sort(key=lambda x:x['key']);m.write(args.output/'results.json',results)
    counts=Counter()
    for r in results:
        for role in r['roles']:counts[f'{r["players"]}/{role}']+=1
    m.write(args.output/'COMPLETE.json',dict(audited=len(results),errors=[r['key']for r in results if r['status']!='audited'],
        role_supply=dict(counts),results_sha256=m.sha(args.output/'results.json'),sources_sha256=m.sha(args.output/'SOURCES.json'),
        pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


def choose(args):
    run=args.audit.resolve();complete=json.loads((run/'COMPLETE.json').read_text())
    assert m.sha(run/'results.json')==complete['results_sha256']
    audited=[r for r in json.loads((run/'results.json').read_text())if r['status']=='audited'and r['roles']]
    snapshot(args.output,dict(operation='Exact purpose quotas, canonical/origin uniqueness and structural diversity',
        quotas={f'{p}/{r}':n for(p,r),n in QUOTAS.items()},
        objectives=['Maximize distinct typed geometry','Minimize maximum geometry repetition','Deterministic SHA256 tie break'],
        parent_importance_ranking='NO_Q_S_MAGNITUDE_OR_MODEL_SCORE',milp_seconds_per_stage=120,workers=1),
        dict(audit_complete=ident(run/'COMPLETE.json'),audit_results=ident(run/'results.json')))
    assignments=[(r,role)for r in audited for role in r['roles']]
    families=sorted({r['geometry']for r in audited});nf=len(families);nx=len(assignments);nt=nx+nf
    family_index={f:nx+i for i,f in enumerate(families)}
    constraints=[]
    def constrain(ids,low,high,extra=None):constraints.append((ids,low,high,extra or {}))
    for cell,n in QUOTAS.items():constrain([i for i,(r,role)in enumerate(assignments)if(r['players'],role)==cell],n,n)
    for field in ['key','canonical_id','origin_group']:
        groups=defaultdict(list)
        for i,(r,role)in enumerate(assignments):groups[r[field]].append(i)
        for ids in groups.values():constrain(ids,0,1)
    for family,yi in family_index.items():
        ids=[i for i,(r,role)in enumerate(assignments)if r['geometry']==family]
        constrain(ids,0,np.inf,{yi:-1})
        constrain(ids,-np.inf,0,{yi:-len(ids)})
        constrain(ids,-np.inf,0,{nt:-1})
    def solve(objective,more=()):
        allc=constraints+list(more);mat=lil_matrix((len(allc),nt+1));lo=[];hi=[]
        for ri,(ids,l,h,extras)in enumerate(allc):
            mat[ri,ids]=1
            for i,v in extras.items():mat[ri,i]=v
            lo.append(l);hi.append(h)
        upper=np.ones(nt+1);upper[-1]=100
        return milp(np.array(objective),integrality=np.ones(nt+1),bounds=Bounds(np.zeros(nt+1),upper),
            constraints=LinearConstraint(mat.tocsr(),lo,hi),options=dict(time_limit=120.,mip_rel_gap=0.))
    objective=np.zeros(nt+1);objective[nx:nt]=-1
    first=solve(objective)
    if not first.success:
        m.write(args.output/'SHORTFALL.json',dict(status='INFEASIBLE_OR_NOT_PROVEN',solver_message=first.message,
            admitted_role_supply=complete['role_supply'],next='Generate only deficient types; do not lower gates'))
        return
    coverage=int(round(first.x[nx:nt].sum()));coverage_row=(list(range(nx,nt)),coverage,coverage,{})
    objective=np.zeros(nt+1);objective[-1]=1
    second=solve(objective,[coverage_row]);assert second.success,second.message
    repetition=int(round(second.x[-1]));load_row=([nt],repetition,repetition,{})
    objective=np.zeros(nt+1)
    for i,(r,role)in enumerate(assignments):objective[i]=int(digest([VERSION,r['key'],role])[:10],16)/16**10
    third=solve(objective,[coverage_row,load_row]);assert third.success,third.message
    selected=[]
    for i,(r,role)in enumerate(assignments):
        if third.x[i]>.5:
            assert m.sha(run/r['path'])==r['sha256']
            selected.append(dict(key=r['key'],players=r['players'],purpose=role,origin_group=r['origin_group'],
                canonical_id=r['canonical_id'],geometry=r['geometry'],audit_path=str((run/r['path']).relative_to(m.ROOT)),
                audit_sha256=r['sha256']))
    selected.sort(key=lambda x:(x['players'],x['purpose'],x['key']))
    assert len(selected)==100 and len({x['canonical_id']for x in selected})==100 and len({x['origin_group']for x in selected})==100
    counts=Counter((x['players'],x['purpose'])for x in selected);assert dict(counts)==QUOTAS
    m.write(args.output/'SELECTION.json',dict(status='SELECTED_PENDING_INDEPENDENT_WITNESS_VERIFICATION',parents=selected,
        counts={f'{p}/{r}':n for(p,r),n in counts.items()},typed_geometries=coverage,max_geometry_repetition=repetition,
        missing_or_unselected_are_not_low_model_value=True))
    m.write(args.output/'COMPLETE.json',dict(selected=100,typed_geometries=coverage,max_geometry_repetition=repetition,
        selection_sha256=m.sha(args.output/'SELECTION.json'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


def sparse_full_Q(sparse,row):
    mass=np.zeros(sparse.w);mass[row['world_ids']]=row['posterior']
    tree,roots,mapping,stats=sparse.forest({row['node']:mass},row['actor'])
    ids=np.flatnonzero(mass>0);weights=mass[ids]/mass[ids].sum()
    tree.worlds=tuple(tree.worlds[i]for i in ids);tree.world_weights=weights;tree.w=len(ids)
    tree.information_groups={};tree._check=lambda:None
    for i,e in enumerate(tree.entries):
        if e.actor is None:
            e.payoff=e.payoff[ids]
        else:
            tree.policy[i]=tree.policy[i][:,ids]
            if e.actor==row['actor']:
                groups=defaultdict(list)
                for wi,w in enumerate(tree.worlds):
                    key=(w[row['actor']],tuple((p,g,w[p][g])for p,g in observed_slots(e.node,row['actor'])))
                    groups[key].append(wi)
                tree.information_groups[i]=[np.array(x,dtype=int)for x in groups.values()]
    values=contingent_values(tree,row['actor'],_reach(tree,row['actor']))
    root=next(iter(roots));q=np.array([weights@values[ch][:,row['actor']]for ch in tree.entries[root].children])
    np.testing.assert_allclose(q,row['Q'],atol=1e-7,rtol=0)
    return dict(all_action_Q_match=True,Q_replayed=q.tolist(),forest_stats=stats)


def verify_worker(item,out):
    audit_path=m.ROOT/item['audit_path'];assert m.sha(audit_path)==item['audit_sha256']
    record=json.loads(audit_path.read_text());source=record['source'];chosen=record['roles'][item['purpose']]
    sparse=make_sparse(source);row=chosen['witness'];check=sparse_full_Q(sparse,row)
    node,_=sparse.locate(row['node']);actions=[a.to_dict()for a in sparse.rules.actions(node)]
    assert actions==row['actions'];assert row['counterfactual_mass']>0
    if item['purpose']=='information':assert chosen['proof']['S_lower']>m.EPS
    elif item['purpose']=='valuation':assert valuation_witness(row)is not None
    else:assert planning_witness(row)is not None
    fact=dict(public_history=[e.to_dict()for e in node.state.transcript],
        commitments=node.state.snapshot_commitments(),query_used=node.state.query_used,offer_used=node.state.offer_used,
        pending=None if node.pending is None else node.pending.to_dict(),
        own_preferences=row['own_type'],own_direct_answers=row['private_answers'],legal_actions=actions,
        scope='Native decision facts and Oracle annotations; not a rendered model request')
    path=out/'checks'/f'{item["key"]}.json';m.write(path,dict(key=item['key'],purpose=item['purpose'],
        Q_check=check,witness=row,proof=chosen['proof'],facts=fact))
    return dict(key=item['key'],status='verified',path=str(path.relative_to(out)),sha256=m.sha(path))


def export(args):
    selection=json.loads((args.selection/'SELECTION.json').read_text());items=selection['parents']
    assert len(items)==100
    snapshot(args.output,dict(operation='Independent all-action witness Q replay and byte-identity parent export',
        workers=args.workers,pool_status='QUALIFIED_ORACLE_STRUCTURE_POOL_NOT_MODEL_TRAINING_READY',
        validation_test_splits='NOT_ASSIGNED',selection800='NOT_RUN',purpose_quota={f'{p}/{r}':n for(p,r),n in QUOTAS.items()}),
        dict(selection=ident(args.selection/'SELECTION.json')))
    checks=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        futures=[executor.submit(verify_worker,x,args.output)for x in items]
        for future in as_completed(futures):checks.append(future.result())
    assert len(checks)==100;m.write(args.output/'WITNESS_CHECKS.json',checks)
    parents=[];assets={}
    for index,item in enumerate(items):
        audit_data=json.loads((m.ROOT/item['audit_path']).read_text());source=audit_data['source']
        folder=args.output/'assets'/str(index);folder.mkdir(parents=True)
        for role,name in [('reference','reference.npz'),('labels','labels.jsonl.gz')]:
            data=source_bytes(source['source'][role]);(folder/name).write_bytes(data)
            assets[f'{index}/{name}']=dict(path=str((folder/name).relative_to(args.output)),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        raw=source['job']['raw']
        parents.append(dict(index=index,id=digest([VERSION,source['canonical_id']])[:24],canonical_id=source['canonical_id'],
            raw=raw,purpose=item['purpose'],players=item['players'],origin_group=item['origin_group'],source_key=item['key'],
            source_raw_sha256=source['raw_sha256'],geometry=item['geometry'],reference=assets[f'{index}/reference.npz'],
            labels=assets[f'{index}/labels.jsonl.gz'],witness_check=next(x for x in checks if x['key']==item['key']),
            admission=dict(path=item['audit_path'],sha256=item['audit_sha256']),
            inherited_native_certificate=source['inherited_result']['certificate'],D='NOT_MEASURED'))
    with(args.output/'parents.jsonl').open('w')as stream:
        for p in parents:stream.write(stable(p)+'\n')
    counts=Counter((x['players'],x['purpose'])for x in parents);assert dict(counts)==QUOTAS
    manifest=dict(version=VERSION,status='QUALIFIED_ORACLE_STRUCTURE_POOL_PENDING_PROMPT_D_AND_800',parents=100,
        purpose_counts={f'{p}/{r}':n for(p,r),n in counts.items()},source_counts=dict(Counter(p['source_key'].split('-')[0]for p in parents)),
        unique_canonical_parents=len({p['canonical_id']for p in parents}),unique_origin_groups=len({p['origin_group']for p in parents}),
        typed_geometries=len({p['geometry']for p in parents}),max_geometry_repetition=max(Counter(p['geometry']for p in parents).values()),
        all100_witness_Q_replayed=True,information_witnesses_independent_LP=60,
        assets=assets,parent_sha256=m.sha(args.output/'parents.jsonl'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json'),
        old_parent25='RETAINED_CHALLENGE_MISSING_NOT_CLASSIFIED_LOW_VALUE',new_generation='NOT_RUN_EXISTING_SUPPLY_SUFFICIENT',
        training_validation_split='NOT_ASSIGNED',candidate800='NOT_SELECTED',test='NOT_GENERATED',D='NOT_MEASURED',production='UNCHANGED_V8')
    m.write(args.output/'MANIFEST.json',manifest);m.write(args.output/'COMPLETE.json',dict(parents=100,
        manifest_sha256=m.sha(args.output/'MANIFEST.json'),parents_sha256=m.sha(args.output/'parents.jsonl'),
        checks_sha256=m.sha(args.output/'WITNESS_CHECKS.json'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['audit','choose','export'])
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--audit',type=Path);parser.add_argument('--selection',type=Path)
    args=parser.parse_args();args.output=args.output.resolve()
    if args.operation=='audit':audit(args)
    elif args.operation=='choose':choose(args)
    else:export(args)


if __name__=='__main__':main()
