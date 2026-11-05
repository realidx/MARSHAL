"""Independent native/visibility/coverage review and D-before800 export."""
from new import slice800_selection_20261104_v3 as s
from new import entry_supply_audit_20261104 as supply
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import gzip
import json
from pathlib import Path

p=s.p
VERSION='slice800-native-export-v1'
REG=p.m.ROOT/'examples/strategic_slices/versions/slice800_native_export_v1_20261104/SNAPSHOT.json'


def verify_parent(parent,selected,pool,query_categories,out):
    assert p.m.sha(p.m.ROOT/parent['admission']['path'])==parent['admission']['sha256']
    source=json.loads((p.m.ROOT/parent['admission']['path']).read_text())['source']
    assert p.digest(source['job']['raw'])==parent['source_raw_sha256']==p.digest(parent['raw'])
    assert p.m.sha(pool/parent['labels']['path'])==parent['labels']['sha256']
    assert p.m.sha(pool/parent['reference']['path'])==parent['reference']['sha256']
    indexed=p.IndexedReference(source['job']);rules=indexed.rules
    wanted={(e['candidate']['node'],e['candidate']['cell']):e for e in selected};assert len(wanted)==len(selected)
    records=[]
    with gzip.open(pool/parent['labels']['path'],'rt')as stream:
        for line in stream:
            row=json.loads(line);key=row['node'],row['cell']
            if key not in wanted:continue
            item=wanted[key];candidate=item['candidate'];role=item['role']
            assert row['counterfactual_mass']>0 and row['Q_scope']=='contingent_BR'
            node,_=indexed.find(row['node']);actions=[a.to_dict()for a in rules.actions(node)]
            assert actions==row['actions']and rules.actor(node)==row['actor']
            assert node.state.turn_index==row['turn']
            phase='response'if node.pending is not None else'proposal';assert phase==row['phase']
            slots=tuple(p.observed_slots(node,row['actor']))
            assert list(slots)==[tuple(x[:2])for x in row['private_answers']]
            assert abs(sum(row['posterior'])-1)<1e-9
            for wi in row['world_ids']:
                world=rules.worlds[wi];assert list(world[row['actor']])==row['own_type']
                assert all(world[a][g]==value for a,g,value in row['private_answers'])
            base=dict(actor=row['actor'],turn=row['turn'],commitments=node.state.snapshot_commitments(),
                query_used=node.state.query_used,offer_used=node.state.offer_used,
                pending=None if node.pending is None else node.pending.to_dict(),
                history=[event.to_dict()for event in node.state.transcript],legal=actions)
            entry_id=p.digest([parent['canonical_id'],p.digest(base),row['own_type'],sorted(row['private_answers'])])
            assert entry_id==candidate['id']
            physical=p.digest({k:v for k,v in base.items()if k not in ('history','legal')})
            assert physical==candidate['physical_skeleton']
            horizon=supply.focal_horizon(rules,node,row['actor']);assert horizon==candidate['focal_decisions_to_native_terminal']
            positive=[x for x in row['S_items']if x['S']>p.m.EPS]
            features=dict(multi=horizon['min']>=2,single=horizon['max']==1,
                private=any(x['omitted'][0]=='private'for x in positive),
                history=any(x['omitted'][0]=='history'for x in positive),
                future_only=any(x['own_future_loss']>p.m.EPS for x in positive)and not any(x['own_current_loss']>p.m.EPS for x in positive))
            assert features==candidate['features']
            if role=='acquire_required':assert query_categories[entry_id]==s.query.NECESSARY
            elif role=='acquire_mixed':assert query_categories[entry_id]==s.query.AMPLIFIES
            elif role=='information_use':assert positive
            elif role=='valuation':assert p.valuation_witness(row)is not None
            elif role=='planning':assert p.planning_witness(row)is not None
            elif role=='response_own':assert phase=='response'and not positive and row['span']>p.m.EPS
            elif role=='response_social':
                assert phase=='response'and not positive and row['span']<=p.m.EPS
                values=[row['Q_others'][a]for a in row['own_optimal']];assert max(values)-min(values)>p.m.EPS
            else:raise AssertionError(role)
            ng=len(parent['raw']['game']['goals']);public=[]
            for actor in range(parent['players']):
                types=parent['raw']['type_catalogues'][str(actor)]
                public.append([types[0][g]if len({t[g]for t in types})==1 else None for g in range(ng)])
            facts=dict(**base,phase=phase,own_preferences=row['own_type'],own_direct_answers=row['private_answers'],
                public_preferences=public,game_rules=parent['raw']['game'],
                background_prior=parent['raw'].get('background_prior','NOT_RECORDED'),
                protocol='Response own final utility first; only own ties maximize sum of others final utilities',
                scope='Native visible facts, not a rendered system/user/tools request; Oracle fields must not enter model context')
            record=dict(id=p.digest([VERSION,parent['id'],entry_id])[:24],entry_id=entry_id,
                parent_id=parent['id'],parent_index=parent['index'],source_key=parent['source_key'],
                split=item['split'],primary_role=role,all_coverage_tags=candidate['tags'],
                features=features,focal_decisions_to_native_terminal=horizon,physical_skeleton=physical,
                model_facts=facts,oracle_annotation=row,
                source=dict(parent_pool='new/qualified_parent_pool_65_35_20261104/v1',
                    parent_raw_sha256=parent['source_raw_sha256'],reference=parent['reference'],profile=parent['labels']),
                control=dict(player=row['actor'],start='CURRENT_ENTRY',end='NATIVE_TERMINAL',
                    opponents='SAME_FROZEN_CERTIFIED_REFERENCE',world_sampling='Conditional posterior in oracle_annotation; not independently reset to parent prior'),
                D='NOT_MEASURED',prompt='NOT_FINALIZED',
                response_scoring='PROTOCOL_ALIGNMENT_REQUIRED_BEFORE_MODEL_D_OR_TRAINING'if role=='response_social'else'NOT_CHANGED_BY_EXPORT')
            records.append(record)
    assert len(records)==len(selected)
    records.sort(key=lambda x:(x['oracle_annotation']['node'],x['oracle_annotation']['cell']))
    path=out/'checks'/str(parent['index'])/'records.json';p.m.write(path,records)
    print(dict(index=parent['index'],entries=len(records),native_visibility_role_check='PASS'),flush=True)
    return records


def verify_coverage(records,parents,mandatory):
    assert len(records)==800 and len({r['entry_id']for r in records})==800
    counts=Counter((r['split'],r['primary_role'])for r in records)
    assert dict(counts)=={(split,role):n for split,qs in s.QUOTAS.items()for role,n in qs.items()}
    by_parent=defaultdict(list);physical=Counter();roles=defaultdict(Counter)
    for r in records:
        by_parent[r['parent_index']].append(r);physical[r['parent_index'],r['physical_skeleton']]+=1
        roles[r['parent_index']][r['primary_role']]+=1
    assert len(by_parent)==100 and max(physical.values())<=3
    split_parent={}
    for i,rs in by_parent.items():
        splits={r['split']for r in rs};assert len(splits)==1;split=next(iter(splits));split_parent[i]=split
        assert len(rs)<=s.PARENT_CAP[split]
        for role,cap in s.ROLE_CAP.items():assert roles[i][role]<=cap
    for n,purpose in [(2,'information'),(2,'valuation'),(2,'planning'),(3,'information'),(3,'valuation'),(3,'planning')]:
        ids=[p['index']for p in parents if p['players']==n and p['purpose']==purpose]
        assert sum(split_parent[i]=='validation'for i in ids)*5==len(ids)
    selected_by_id={r['entry_id']:r for r in records}
    for entry,role in mandatory.items():assert selected_by_id[entry]['primary_role']==role
    summaries={}
    for split in s.QUOTAS:
        rs=[r for r in records if r['split']==split];info=[r for r in rs if r['primary_role']=='information_use']
        n=len(rs);three=sum(parents[r['parent_index']]['players']==3 for r in rs)
        assert .3*n<=three<=.4*n
        multi=sum(r['features']['multi']for r in rs);assert multi>=.25*n
        protections=dict(multi=60 if split=='train'else 20,private=90 if split=='train'else 30,
                         history=60 if split=='train'else 20,future_only=15 if split=='train'else 5)
        for feature,minimum in protections.items():assert sum(r['features'][feature]for r in info)>=minimum
        parent_counts=Counter(r['parent_index']for r in rs)
        summaries[split]=dict(entries=n,parents=len(parent_counts),two_player=n-three,three_player=three,
            primary_roles=dict(Counter(r['primary_role']for r in rs)),
            guaranteed_multidecision=multi,single_focal_decision=sum(r['features']['single']for r in rs),
            window_histogram=dict(Counter(f'{r["focal_decisions_to_native_terminal"]["min"]}-{r["focal_decisions_to_native_terminal"]["max"]}'for r in rs)),
            information_use_protections={key:sum(r['features'][key]for r in info)for key in protections},
            max_parent_entries=max(parent_counts.values()),min_parent_entries=min(parent_counts.values()),
            parent_counts=dict(sorted(parent_counts.items())))
    shared_geometries=set(parents[i]['geometry']for i,split in split_parent.items()if split=='train')&set(parents[i]['geometry']for i,split in split_parent.items()if split=='validation')
    return dict(splits=summaries,parent_overlap=0,entry_overlap=0,protected_admission_witnesses=100,
        inherited_LP_information_witnesses=60,max_physical_skeleton_entries=max(physical.values()),
        represented_parent_roles=sum(len(v)for v in roles.values()),represented_parent_actors=len({(r['parent_index'],r['model_facts']['actor'])for r in records}),
        shared_typed_geometries=len(shared_geometries),typed_geometry_disjoint_claim=False,
        all_native_facts_actions_beliefs_and_role_checks=True,new_per_entry_Q_LP='NOT_RUN_EXISTING_HASH_BOUND_PROFILES_REUSED')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--pool',type=Path,required=True);parser.add_argument('--queries',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    for k in ('selection','pool','queries','output'):setattr(args,k,getattr(args,k).resolve())
    complete=json.loads((args.selection/'COMPLETE.json').read_text());assert complete['selected']==800
    assert p.m.sha(args.selection/'SELECTION.json')==complete['selection_sha256']
    chosen=json.loads((args.selection/'SELECTION.json').read_text())['entries']
    mandatory=json.loads((args.selection/'MANDATORY.json').read_text())
    parents=[json.loads(x)for x in(args.pool/'parents.jsonl').read_text().splitlines()]
    qcat={e['entry_id']:e['category']for c in json.loads((args.queries/'RESULTS.json').read_text())for e in c['entries']}
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='Independent all800native observation/role/coverage verification andD-before export',
        workers=args.workers,inherit_selection_version=s.VERSION,window='Current focal player to native terminal, same reference opponents',
        public_private_separation='model_facts excludes true hidden world, posterior,Q,S and raw ego own_preferences; oracle_annotation separate',
        validation='Every selected native observation ID, action menu, direct-answer support, conditional profile and role predicate; all hard coverage constraints',
        new_full_Q_or_LP='NOT_RUN; reuse hash-bound profiles and existing witnesses',
        runnable_training='NOT_CONNECTED; finalprompt, protocol scoring and modelD pending'),
        dict(selection=p.ident(args.selection/'SELECTION.json'),mandatory=p.ident(args.selection/'MANDATORY.json'),
             parents=p.ident(args.pool/'parents.jsonl'),parent_manifest=p.ident(args.pool/'MANIFEST.json'),queries=p.ident(args.queries/'RESULTS.json')))
    groups=defaultdict(list)
    for item in chosen:groups[item['candidate']['parent_index']].append(item)
    records=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        fs=[executor.submit(verify_parent,parents[i],items,args.pool,qcat,args.output)for i,items in groups.items()]
        for future in as_completed(fs):records.extend(future.result())
    records.sort(key=lambda r:(r['split'],r['parent_index'],r['oracle_annotation']['node'],r['oracle_annotation']['cell']))
    summary=verify_coverage(records,parents,mandatory);p.m.write(args.output/'SUMMARY.json',summary)
    files={}
    for split in ('train','validation'):
        path=args.output/f'{split}.jsonl'
        with path.open('w')as stream:
            for row in records:
                if row['split']==split:stream.write(p.stable(row)+'\n')
        files[path.name]=dict(sha256=p.m.sha(path),bytes=path.stat().st_size)
    lines=['# 800入口候选逐题索引','',
        'D之前的覆盖候选；不是最终100训练slice。状态控制到原生终局；模型prompt/回应评分未接通。',
        '角色配额只指定主用途，完整交叉标签/行动Q/逐条S见对应splitJSONL；node/cell保留原身份。','',
        '|split|父index|来源|主用途|actor|阶段|node/cell|本人窗口|',
        '|---|---:|---|---|---:|---|---|---|']
    for r in records:
        a=r['oracle_annotation'];h=r['focal_decisions_to_native_terminal']
        lines.append(f'|{r["split"]}|{r["parent_index"]}|{r["source_key"]}|{r["primary_role"]}|{a["actor"]}|{a["phase"]}|{a["node"]}/{a["cell"]}|{h["min"]}–{h["max"]}|')
    (args.output/'ENTRY_INDEX.md').write_text('\n'.join(lines)+'\n')
    splits={str(i):next(r['split']for r in records if r['parent_index']==i)for i in range(100)}
    p.m.write(args.output/'PARENT_SPLIT.json',splits)
    manifest=dict(version=VERSION,selection_version=s.VERSION,status='REVIEWED_D_BEFORE800_PENDING_FINAL_PROMPT_PROTOCOL_SCORING_AND_D',
        parent_pool=p.ident(args.pool/'MANIFEST.json'),selection=p.ident(args.selection/'SELECTION.json'),
        files=files,summary_sha256=p.m.sha(args.output/'SUMMARY.json'),
        index_sha256=p.m.sha(args.output/'ENTRY_INDEX.md'),parent_split_sha256=p.m.sha(args.output/'PARENT_SPLIT.json'),
        profile_reference_assets='Hash-bound original parent pool required; not recopied',
        prompt_tools='NOT_FINALIZED_NOT_CHANGED',reward_training='NOT_CHANGED_NOT_CONNECTED',D='NOT_MEASURED',
        test='NOT_GENERATED_PARENT100_EXTERNAL',production='UNCHANGED_V8')
    p.m.write(args.output/'MANIFEST.json',manifest)
    p.m.write(args.output/'COMPLETE.json',dict(status=manifest['status'],entries=800,all_native_and_coverage_checks_passed=True,
        manifest_sha256=p.m.sha(args.output/'MANIFEST.json'),pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
