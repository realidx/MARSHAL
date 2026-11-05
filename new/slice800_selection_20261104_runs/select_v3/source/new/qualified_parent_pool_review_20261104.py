"""Independent identity/count checks and readable qualified-parent roster."""
from new import qualified_parents_6535_20261104 as p
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True);parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    for k in ('pool','audit','selection','output'):setattr(args,k,getattr(args,k).resolve())
    p.VERSION='qualified-parent-pool-review-v1'
    p.REG=p.m.ROOT/'examples/strategic_slices/versions/qualified_parent_pool_review_v1_20261104/SNAPSHOT.json'
    p.snapshot(args.output,dict(operation='Independent final asset identities, quality invariants and readable admission/rejection ledger',
        workers=1,threads=1,scientific_scope='Oracle/structure qualification only; no new model or gameplay run'),
        dict(pool=p.ident(args.pool/'MANIFEST.json'),audit=p.ident(args.audit/'COMPLETE.json'),selection=p.ident(args.selection/'SELECTION.json')))
    complete=json.loads((args.pool/'COMPLETE.json').read_text());manifest=json.loads((args.pool/'MANIFEST.json').read_text())
    assert p.m.sha(args.pool/'MANIFEST.json')==complete['manifest_sha256']
    assert p.m.sha(args.pool/'parents.jsonl')==complete['parents_sha256']==manifest['parent_sha256']
    parents=list(map(json.loads,(args.pool/'parents.jsonl').read_text().splitlines()))
    assert len(parents)==100 and len({x['canonical_id']for x in parents})==100 and len({x['origin_group']for x in parents})==100
    counts=Counter((x['players'],x['purpose'])for x in parents);assert dict(counts)==p.QUOTAS
    for asset in manifest['assets'].values():assert p.m.sha(args.pool/asset['path'])==asset['sha256']
    checks={r['key']:r for r in json.loads((args.pool/'WITNESS_CHECKS.json').read_text())}
    goals=Counter();hidden=Counter();scoring=Counter();actions=Counter();source=Counter();phases=Counter();planning=Counter()
    lowers=[];all_errors=[];selected_rows=[]
    lines=['# 合格65/35父游戏v1逐题索引','',
        '这是Oracle/决策结构验收结果，D未测；不是800入口名单或模型训练就绪声明。',
        '主用途：information=信息损失；valuation=估值变化；planning=不需新增调查的互动/后续机会。','',
        '| 新index | 来源 | 人数 | 主用途 | 目标数 | 隐藏单元 | 行动数 | 见证node/cell | 独立检查 |',
        '|---:|---|---:|---|---:|---:|---|---|---|']
    for parent in parents:
        raw=parent['raw'];game=raw['game'];assert p.digest(raw)==parent['source_raw_sha256']
        assert p.canonical_parent(raw)==parent['canonical_id']
        assert len(game['round_robin'])==2*game['n_players']
        assert game['investigation_budget']==game['offer_budget']==1
        c=checks[parent['source_key']];assert p.m.sha(args.pool/c['path'])==c['sha256']
        check=json.loads((args.pool/c['path']).read_text());row=check['witness'];proof=check['proof']
        assert check['Q_check']['all_action_Q_match']
        all_errors.extend(abs(a-b)for a,b in zip(row['Q'],check['Q_check']['Q_replayed']))
        if parent['purpose']=='information':assert proof['S_lower']>p.m.EPS;lowers.append(proof['S_lower'])
        elif parent['purpose']=='valuation':assert p.valuation_witness(row)is not None
        else:assert p.planning_witness(row)is not None;planning[proof['kind']]+=1
        ng=len(game['goals']);nh=sum(len({r[g]for r in types})>1 for types in raw['type_catalogues'].values()for g in range(ng))
        flags=[g['binary']for g in game['goals']];mode='binary'if all(flags)else'linear'if not any(flags)else'mixed'
        goals[parent['players'],ng]+=1;hidden[parent['players'],nh]+=1;scoring[parent['players'],mode]+=1
        actions[parent['players'],tuple(game['n_actions_per_player'])]+=1;source[parent['source_key'].split('-')[0]]+=1
        phases[parent['purpose'],row['phase']]+=1
        detail=dict(index=parent['index'],source_key=parent['source_key'],players=parent['players'],purpose=parent['purpose'],
            goals=ng,hidden_cells=nh,scoring=mode,actions=game['n_actions_per_player'],
            witness_node=row['node'],witness_cell=row['cell'],witness_check=str((args.pool/c['path']).relative_to(p.m.ROOT)))
        selected_rows.append(detail)
        target=str(args.pool/c['path'])
        lines.append(f'| {parent["index"]} | {parent["source_key"]} | {parent["players"]} | {parent["purpose"]} | {ng} | {nh} | {game["n_actions_per_player"]} | {row["node"]}/{row["cell"]} | [事实/Q/证明]({target}) |')
    audits=json.loads((args.audit/'results.json').read_text());selected={x['source_key']for x in parents}
    canonical={x['canonical_id']for x in parents};origin={x['origin_group']for x in parents};not_selected=[]
    for record in audits:
        if record['key']in selected:continue
        reason=('audit_execution_error'if record['status']!='audited'else
            'no_witness_for_this_versions_primary_roles'if not record['roles']else
            'another_version_of_same_origin_selected'if record['origin_group']in origin else
            'renaming_equivalent_parent_selected'if record['canonical_id']in canonical else
            'not_needed_under_exact_quotas_and_geometry_diversity')
        not_selected.append(dict(key=record['key'],eligible_roles=record['roles'],reason=reason,
            audit=str((args.audit/record['path']).relative_to(p.m.ROOT)),not_a_model_difficulty_judgment=True))
    assert len(not_selected)==82
    group_review=json.loads((p.CAND/'review_v3/PARENTS.json').read_text());positive={x['key']for x in group_review if x['counts']['positive_S']>0}
    summary=dict(parents=100,purpose_counts={f'{n}/{r}':k for(n,r),k in counts.items()},source_counts=dict(source),
        typed_geometries=manifest['typed_geometries'],max_geometry_repetition=manifest['max_geometry_repetition'],
        unique_origins=100,unique_canonical=100,selected_with_any_positive_own_S=sum(x['source_key']in positive for x in parents),
        goals={str(k):v for k,v in goals.items()},hidden_cells={str(k):v for k,v in hidden.items()},
        scoring={str(k):v for k,v in scoring.items()},actions={str(k):v for k,v in actions.items()},
        witness_phases={str(k):v for k,v in phases.items()},planning_proofs=dict(planning),
        information_LP_lower_range=[min(lowers),max(lowers)],max_independent_witness_Q_error=max(all_errors),
        asset_hashes_verified=len(manifest['assets']),new_games_generated=0,
        no_witness_rejected=sum(x['reason']=='no_witness_for_this_versions_primary_roles'for x in not_selected),
        unselected_reason_counts=dict(Counter(x['reason']for x in not_selected)),
        missing_original25='RETAINED_CHALLENGE_NOT_LOW_VALUE',D='NOT_MEASURED',selection800='NOT_RUN',test='NOT_GENERATED')
    p.m.write(args.output/'SUMMARY.json',summary);p.m.write(args.output/'SELECTED_INDEX.json',selected_rows)
    p.m.write(args.output/'NOT_SELECTED.json',not_selected);(args.output/'INDEX.md').write_text('\n'.join(lines)+'\n')
    p.m.write(args.output/'COMPLETE.json',dict(all100_purpose_and_Q_checks_passed=True,all200_asset_hashes_passed=True,
        summary_sha256=p.m.sha(args.output/'SUMMARY.json'),roster_sha256=p.m.sha(args.output/'SELECTED_INDEX.json'),
        nonselected_sha256=p.m.sha(args.output/'NOT_SELECTED.json'),index_sha256=p.m.sha(args.output/'INDEX.md'),
        pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
