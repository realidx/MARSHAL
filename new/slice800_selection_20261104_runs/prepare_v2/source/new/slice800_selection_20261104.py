"""Versioned coverage-selected800 entry candidates, held out by parent."""
from new import qualified_parents_6535_20261104 as p
from new import query_answer_access_20261104 as query
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix

VERSION='slice800-coverage-selection-v1'
REG=p.m.ROOT/'examples/strategic_slices/versions/slice800_selection_v1_20261104/SNAPSHOT.json'
ROLES=('acquire_required','acquire_mixed','information_use','valuation','planning','response_own','response_social')
QUOTAS={'train':dict(zip(ROLES,(45,15,240,120,120,30,30))),
        'validation':dict(zip(ROLES,(15,5,80,40,40,10,10)))}
ROLE_CAP={'acquire_required':6,'acquire_mixed':4,'information_use':10}
PARENT_CAP={'train':12,'validation':16}
SEED=20261104


def rank(value):return int(hashlib.sha256(p.stable([VERSION,SEED,value]).encode()).hexdigest(),16)
def features(row):
    tags=set(row['tags']);h=row['focal_decisions_to_native_terminal']
    return dict(multi=h['min']>=2,single=h['max']==1,private='information_private'in tags,
        history='information_history'in tags,future_only='information_future'in tags and'information_current'not in tags)


def roles_for(row,category):
    tags=set(row['tags']);roles=[]
    if category==query.NECESSARY:roles.append('acquire_required')
    if category==query.AMPLIFIES:roles.append('acquire_mixed')
    if 'information_use'in tags:roles.append('information_use')
    if 'valuation_verified_predicate'in tags:roles.append('valuation')
    if 'planning_verified_predicate'in tags:roles.append('planning')
    if 'information_use'not in tags and row['phase']=='response':
        if 'response_own_choice'in tags:roles.append('response_own')
        elif 'response_social_priority'in tags:roles.append('response_social')
    return roles


def prepare(args):
    pool=args.pool;inv=args.inventory
    parents=[json.loads(x)for x in(pool/'parents.jsonl').read_text().splitlines()]
    assert len(parents)==100
    cases=json.loads((inv/'PARENTS.json').read_text())
    qresults=json.loads((args.queries/'RESULTS.json').read_text())
    qcat={e['entry_id']:e['category']for c in qresults for e in c['entries']}
    assert len(qcat)==235
    mandatory={};witness_keys={}
    for parent in parents:
        check=json.loads((pool/parent['witness_check']['path']).read_text())
        assert p.m.sha(pool/parent['witness_check']['path'])==parent['witness_check']['sha256']
        w=check['witness'];witness_keys[parent['index']]=(w['node'],w['cell'])
    keep={};bins=defaultdict(list);large=defaultdict(list);stats=Counter()
    for case in cases:
        parent=parents[case['index']];file=inv/case['entries']['path'];assert p.m.sha(file)==case['entries']['sha256']
        with gzip.open(file,'rt')as stream:
            for line in stream:
                row=json.loads(line);stats['input_observable_entries']+=1
                category=qcat.get(row['id']);roles=roles_for(row,category)
                if not roles:continue
                row=dict(row,roles=roles,features=features(row),query_category=category)
                if (row['node'],row['cell'])==witness_keys[row['parent_index']]:
                    role={'information':'information_use','valuation':'valuation','planning':'planning'}[parent['purpose']]
                    assert role in roles;mandatory[row['id']]=role;keep[row['id']]=row
                # Preserve all rare acquisition/information/planning entries.
                rare=set(roles)&{'acquire_required','acquire_mixed','information_use','planning'}
                if rare:keep[row['id']]=row
                else:
                    # Observations are NOT merged. Within this exact incidence
                    # bin, at most3 can be selected under the physical cap.
                    key=(row['parent_index'],row['physical_skeleton'],tuple(roles),p.stable(row['features']))
                    items=bins[key];items.append(row);items.sort(key=lambda r:rank(r['id']));del items[3:]
    assert len(mandatory)==100
    for values in bins.values():
        for row in values:
            # A declared deterministic proposal shortlist for abundant roles;
            # its lossless physical-bin reduction above is distinct from this.
            for role in row['roles']:
                band='multi'if row['features']['multi']else'single'if row['features']['single']else'optional'
                key=(row['parent_index'],role,band)
                large[key].append(row)
    for values in large.values():
        values.sort(key=lambda r:rank(r['id']))
        for row in values[:64]:keep[row['id']]=row
    values=sorted(keep.values(),key=lambda r:(r['parent_index'],r['node'],r['cell']))
    stats['shortlist_entries']=len(values);stats['mandatory_witnesses']=len(mandatory)
    stats['role_assignments']=sum(len(r['roles'])for r in values)
    p.m.write(args.output/'CANDIDATES.json',values);p.m.write(args.output/'MANDATORY.json',mandatory)
    p.m.write(args.output/'PREPARE.json',dict(counts=dict(stats),per_role=dict(Counter(role for row in values for role in row['roles'])),
        note='Shortlist is a declared coverage proposal, not a model or Q/S magnitude ranking; no entry selection yet'))
    return parents,values,mandatory


class Model:
    def __init__(self):self.names=[];self.lb=[];self.ub=[];self.integer=[];self.constraints=[];self.lower=[];self.upper=[]
    def variable(self,name,lo=0,hi=1,integer=True):
        i=len(self.names);self.names.append(name);self.lb.append(lo);self.ub.append(hi);self.integer.append(int(integer));return i
    def add(self,items,lo=-np.inf,hi=np.inf):
        self.constraints.append(dict(items));self.lower.append(lo);self.upper.append(hi)
    def solve(self,objective,seconds):
        rr=[];cc=[];vv=[]
        for i,row in enumerate(self.constraints):
            for j,v in row.items():rr.append(i);cc.append(j);vv.append(v)
        matrix=coo_matrix((vv,(rr,cc)),shape=(len(self.constraints),len(self.names))).tocsc()
        cost=np.zeros(len(self.names))
        for i,v in objective.items():cost[i]=v
        result=milp(cost,integrality=np.array(self.integer),bounds=Bounds(self.lb,self.ub),
            constraints=LinearConstraint(matrix,self.lower,self.upper),
            options=dict(time_limit=seconds,mip_rel_gap=0.))
        if result.x is None:return result,None
        rounded=np.rint(result.x)
        assert np.max(np.abs(rounded-result.x))<1e-5
        lhs=matrix@rounded
        assert np.all(lhs>=np.array(self.lower)-1e-6)and np.all(lhs<=np.array(self.upper)+1e-6)
        return result,rounded.astype(int)


def select(args,parents,rows,mandatory):
    model=Model();y={r['index']:model.variable(('validation_parent',r['index']))for r in parents}
    x={};by_parent=defaultdict(list);by_entry=defaultdict(list);by_physical=defaultdict(list)
    by_role=defaultdict(list);by_pr=defaultdict(list);by_actor=defaultdict(list)
    for i,row in enumerate(rows):
        for role in row['roles']:
            for split in ('train','validation'):
                v=model.variable(('entry',i,role,split));x[v]=(i,role,split)
                by_parent[row['parent_index'],split].append(v);by_entry[row['id']].append(v)
                by_physical[row['parent_index'],row['physical_skeleton']].append(v)
                by_role[split,role].append(v);by_pr[row['parent_index'],role].append(v)
                by_actor[row['parent_index'],row['actor']].append(v)
    def sumrow(ids):return {i:1 for i in ids}
    for ids in by_entry.values():model.add(sumrow(ids),hi=1)
    for ids in by_physical.values():model.add(sumrow(ids),hi=3)
    for split in QUOTAS:
        for role,n in QUOTAS[split].items():model.add(sumrow(by_role[split,role]),n,n)
    for parent in parents:
        i=parent['index'];t=sumrow(by_parent[i,'train']);t[y[i]]=PARENT_CAP['train'];model.add(t,hi=PARENT_CAP['train'])
        v=sumrow(by_parent[i,'validation']);v[y[i]]=-PARENT_CAP['validation'];model.add(v,hi=0)
        for role,cap in ROLE_CAP.items():model.add(sumrow(by_pr[i,role]),hi=cap)
    for n,purpose in [(2,'information'),(2,'valuation'),(2,'planning'),(3,'information'),(3,'valuation'),(3,'planning')]:
        group=[r for r in parents if r['players']==n and r['purpose']==purpose]
        count=len(group)//5;assert count*5==len(group)
        model.add({y[r['index']]:1 for r in group},count,count)
    for entry,role in mandatory.items():
        ids=[v for v in by_entry[entry]if x[v][1]==role];model.add(sumrow(ids),1,1)
    for split in QUOTAS:
        total=sum(QUOTAS[split].values());three=[v for v,(i,r,s)in x.items()if s==split and parents[rows[i]['parent_index']]['players']==3]
        model.add(sumrow(three),.3*total,.4*total)
        multi=[v for v,(i,r,s)in x.items()if s==split and rows[i]['features']['multi']]
        model.add(sumrow(multi),.25*total,np.inf)
        for feature,n in [('multi',60 if split=='train'else20),('private',90 if split=='train'else30),
                          ('history',60 if split=='train'else20),('future_only',15 if split=='train'else5)]:
            ids=[v for v,(i,r,s)in x.items()if s==split and r=='information_use'and rows[i]['features'][feature]]
            model.add(sumrow(ids),n,np.inf)
    role_presence={}
    for key,ids in by_pr.items():
        if not ids:continue
        z=model.variable(('parent_role',key));role_presence[key]=z
        model.add({z:1,**{i:-1 for i in ids}},hi=0)
        model.add({**sumrow(ids),z:-PARENT_CAP['validation']},hi=0)
    actor_presence={}
    for key,ids in by_actor.items():
        z=model.variable(('parent_actor',key));actor_presence[key]=z
        model.add({z:1,**{i:-1 for i in ids}},hi=0)
        model.add({**sumrow(ids),z:-PARENT_CAP['validation']},hi=0)
    maximum=model.variable('max_scaled_parent_load',0,48)
    for (parent,split),ids in by_parent.items():
        factor=4 if split=='train'else3;model.add({**{i:factor for i in ids},maximum:-1},hi=0)
    stages=[('parent_role_coverage',{i:-1 for i in role_presence.values()}),
            ('parent_actor_coverage',{i:-1 for i in actor_presence.values()}),
            ('balanced_parent_load',{maximum:1}),
            ('deterministic_hash',{v:(rank([rows[i]['id'],role,split])%1000003)/1000003 for v,(i,role,split)in x.items()}|
             {v:(rank(['parent',i])%1000003)/1000003 for i,v in y.items()})]
    log=[];solution=None
    for name,objective in stages:
        start=time.monotonic();result,current=model.solve(objective,args.stage_seconds)
        rec=dict(stage=name,status=int(result.status),message=result.message,seconds=time.monotonic()-start,
            has_feasible_solution=current is not None,mip_gap=None if current is None else float(result.mip_gap))
        if current is None:
            if solution is None:
                p.m.write(args.output/'OPTIMIZATION.json',log+[rec]);return None
            rec['retained_previous_feasible']=True;log.append(rec);continue
        solution=current;score=sum(objective[i]*solution[i]for i in objective);rec['objective']=score;log.append(rec)
        print(rec,flush=True)
        if name!='deterministic_hash':model.add(objective,score,score)
        p.m.write(args.output/'OPTIMIZATION.json',log)
    selected=[dict(candidate=rows[i],role=role,split=split)for v,(i,role,split)in x.items()if solution[v]]
    assert len(selected)==800
    split_parents={str(i):'validation'if solution[v]else'train'for i,v in y.items()}
    p.m.write(args.output/'PARENT_SPLIT.json',split_parents)
    p.m.write(args.output/'SELECTION.json',dict(status='COVERAGE_SELECTED_PENDING_NATIVE_EXPORT_REVIEW',
        entries=selected,optimization=log,optimality='Only stages with status0 proved optimal; all chosen records satisfy hard constraints'))
    return selected


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True);parser.add_argument('--queries',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--stage-seconds',type=float,default=60.)
    parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    for k in ('pool','inventory','queries','output'):setattr(args,k,getattr(args,k).resolve())
    pool_c=json.loads((args.pool/'COMPLETE.json').read_text());assert p.m.sha(args.pool/'MANIFEST.json')==pool_c['manifest_sha256']
    assert p.m.sha(args.pool/'parents.jsonl')==pool_c['parents_sha256']
    inv_c=json.loads((args.inventory/'COMPLETE.json').read_text());assert p.m.sha(args.inventory/'PARENTS.json')==inv_c['parent_results_sha256']
    query_c=json.loads((args.queries/'COMPLETE.json').read_text());assert p.m.sha(args.queries/'RESULTS.json')==query_c['results_sha256']
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='D-before coverage800 and80/20parent-disjoint split',workers=1,
        prepare_only=args.prepare_only,role_quotas=QUOTAS,parent_caps=PARENT_CAP,role_parent_caps=ROLE_CAP,
        physical_cap=3,stage_seconds=args.stage_seconds,seed=SEED,
        abundant_shortlist='3per exact constraint-incidence physical bin, then64per parent/role/lengthband; retain all information/acquisition/planning and100witnesses',
        coverage='per split30-40%three-player entries;>=25%guaranteed multidecision; info-use multi80/private120/history80/future-only20 across800',
        split='Exact20%of each parent player-count/primary-purpose stratum; no parent overlap',
        objective='Time-limited sequential parent-role, parent-actor coverage, scaled max load, deterministic hash; noQ/S magnitudes orD',
        status='D-before candidate selection only; native export pending; no prompt/training integration',
        response_social='Own utility flat, protocol secondary choice; scoring/prompt alignment required beforeD/training'),
        dict(pool=p.ident(args.pool/'MANIFEST.json'),inventory=p.ident(args.inventory/'PARENTS.json'),queries=p.ident(args.queries/'RESULTS.json')))
    parents,rows,mandatory=prepare(args)
    if args.prepare_only:return
    selected=select(args,parents,rows,mandatory)
    p.m.write(args.output/'COMPLETE.json',dict(status='SHORTFALL_OR_TIME_LIMIT_NO_FEASIBLE_SELECTION'if selected is None else'800_SELECTED_PENDING_NATIVE_EXPORT_REVIEW',
        selected=0 if selected is None else len(selected),candidate_sha256=p.m.sha(args.output/'CANDIDATES.json'),
        selection_sha256=None if selected is None else p.m.sha(args.output/'SELECTION.json'),
        pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json'),D='NOT_MEASURED',production='UNCHANGED_V8'))


if __name__=='__main__':main()
