"""Model-blind evidence-enriched development supplement; retain the original pack."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from training.b_sft.social_holdout import fixture, topology_id, collect_setup
from training.b_sft.online_social import VERSION
from training.b_sft.online_social_audit import verify
from training.b_sft.social_cases import key, P_INSTRUCTION


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_pack(path):
    for name, expected in json.loads((path/'checksums.json').read_text()).items():
        if hashlib.sha256((path/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {path/name}')


def informative(row):
    return bool(row['teacher']['B_aux_mask'] and any(len(b['answer']['possible_preferences']) < 3
        for b in row['teacher']['B_by_target'] or []))


def write_review(out):
    rows=read_rows(out/'questions.jsonl');traces=read_rows(out/'trajectories.jsonl')
    summary=json.loads((out/'summary.json').read_text())
    lines=['# 独立结构 B 审查包','',
        '原 v1 完整保留；新增结构按教师公开证据筛选，未使用 LM 得分。这是证据丰富的开发诊断，不是随机分布上的无偏测试。',
        '',f"{summary['independent_topologies']} 个独立结构，{len(rows)} 个决策点，{summary['informative_B_questions']} 个可评分的非全可能集合 B 点。",
        '', '| 结构 | 玩家 | commitment/人 | goal | 全部点 | 有信息 B 点 |','|---|---:|---|---:|---:|---:|']
    for source in sorted({r['source'] for r in rows}):
        raw=json.loads((out/'games'/f'{source}.json').read_text())['fixture'];g=raw['game'];rs=[r for r in rows if r['source']==source]
        lines.append(f"| {source} | {g['n_players']} | {g['n_actions_per_player']} | {len(g['goals'])} | {len(rs)} | {sum(informative(r) for r in rs)} |")
    for source in sorted(summary['informative_by_source']):
        r=next(r for r in rows if r['source']==source and informative(r));n=len(r['input']['history'])
        trace=next(t for t in traces if t['source']==source and r['id'] in t['snapshots'])
        lines+=['',f"## {source}：{r['id']}",'','教师判断（完整输入见 questions.jsonl / B_inputs.jsonl 中同 ID）：']
        for b in r['teacher']['B_by_target']:
            lines.append(f"- P{b['player']}.G{b['goal']}：{b['answer']['possible_preferences']}；favored={b['answer']['favored']}。")
        lines+=['','起点后的公开证据（setup 不作为偏好证据）：','```json']
        lines.append(json.dumps([e for e in trace['events'][:n] if e['kind']!='setup'],ensure_ascii=False,indent=2));lines+=['```']
    lines+=['','注意：同局多个点有关联；20 个有信息点来自 evidence-430230，必须按结构分别报告。',
        '尚未做真实 LM 测试，也不将这些教师标签视为未知任意伙伴策略下的普遍真值。']
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n')


def build(training, original, out, candidates=32, min_structures=4, min_informative=16):
    if out.exists(): raise ValueError('Use a new output directory')
    check_pack(training); check_pack(original)
    shutil.copytree(original, out)
    recipes = [dict(id=f'evidence-{430200+i}', seed=430200+i,
        n=3 if i%2==0 else 4, k=2 if i%2==0 else 1,
        g=4 if i%2==0 else 5, mode=('single' if i%4<2 else 'multi_goal') if i%2==0 else 'multi_partner')
        for i in range(candidates)]
    plan = dict(protocol=VERSION, recipes=recipes, min_new_structures=min_structures,
        min_new_informative_decisions=min_informative, setups=['pass','one_commitment','two_commitments'],
        selection='First nonoverlapping structures with >=2 usable informative B snapshots; retain ALL their snapshots and controls. Stop after both quotas. Teacher evidence selection, never LM score selection.',
        split='Evidence-enriched development diagnostic, not representative random test distribution.')
    (out/'supplement_plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    excluded = {topology_id(json.loads(p.read_text())['fixture']) for p in (training/'games').glob('*.json')}
    fixtures = {p.stem: json.loads(p.read_text())['fixture'] for p in (out/'games').glob('*.json')}
    excluded |= {topology_id(f) for f in fixtures.values()}
    rows = {r['id']:r for r in read_rows(out/'questions.jsonl')}
    trajectories = read_rows(out/'trajectories.jsonl'); old = json.loads((out/'summary.json').read_text())
    statuses = old['cases'][:]; roots = old['root_questions'][:]; selected=[]; added=0
    with (out/'screening.jsonl').open('w') as log:
        for recipe in recipes:
            candidate_rows={}; ts=[]; ss=[]; rr=[]
            try:
                raw, _ = fixture(recipe); topology=topology_id(raw)
                if topology in excluded:
                    result=dict(recipe=recipe, status='topology_overlap')
                else:
                    prefixes={s:fixture(recipe,s)[1] for s in plan['setups']}
                    for setup,prefix in prefixes.items():
                        collect_setup(raw,prefix,recipe,topology,setup,candidate_rows,rr,ts,ss,score_p=False)
                    n=sum(informative(r) for r in candidate_rows.values())
                    result=dict(recipe=recipe, status='selected' if n>=2 else 'insufficient_evidence',
                        informative=n, decisions=len(candidate_rows), cases=ss)
                    if n>=2:
                        # Recompute complete P tables only for selected structures.
                        candidate_rows={};ts=[];ss=[];rr=[]
                        for setup,prefix in prefixes.items():
                            collect_setup(raw,prefix,recipe,topology,setup,candidate_rows,rr,ts,ss)
                        verify({recipe['id']:raw},list(candidate_rows.values()),ts)
                        rows.update(candidate_rows);trajectories.extend(ts);statuses.extend(ss);roots.extend(rr)
                        fixtures[recipe['id']]=raw; excluded.add(topology);selected.append(recipe);added+=n
                        (out/'games'/f"{recipe['id']}.json").write_text(json.dumps(dict(fixture=raw,prefixes=prefixes,topology=topology),indent=2)+'\n')
            except ValueError as exc:
                result=dict(recipe=recipe,status='invalid_candidate',reason=str(exc))
            log.write(json.dumps(result)+'\n');log.flush();print(json.dumps(result),flush=True)
            if len(selected)>=min_structures and added>=min_informative: break
    pairs={}
    for e in trajectories:
        for a,b in zip(e['snapshots'],e['snapshots'][1:]):
            x,y=rows[a],rows[b]
            if not(x['teacher']['B_aux_mask'] and y['teacher']['B_aux_mask']):continue
            answers=lambda r: {(v['player'],v['goal']):v['answer'] for v in r['teacher']['B_by_target'] or []}
            pair=dict(before=a,after=b,category='maintain' if answers(x)==answers(y) else 'update')
            pairs[key(pair)]=pair
    exports={'questions.jsonl':list(rows.values()),'trajectories.jsonl':trajectories,'pairs.jsonl':list(pairs.values()),
        'B_inputs.jsonl':[dict(id=r['id'],input=r['input']) for r in rows.values()],
        'P_contexts.jsonl':[dict(id=r['id'],context=dict(r['input'],instruction=P_INSTRUCTION),belief_source='actual model B output required') for r in rows.values()]}
    for name,data in exports.items(): (out/name).write_text(''.join(json.dumps(r)+'\n' for r in data))
    by_source=Counter(r['source'] for r in rows.values() if informative(r))
    summary=dict(protocol=VERSION,split='evidence_enriched_development_generalization',actual_LM=False,model_based_selection=False,
        independent_topologies=len(fixtures),new_structures=len(selected),selected_recipes=selected,decisions=len(rows),
        informative_B_questions=sum(by_source.values()),informative_by_source=dict(by_source),
        quota_met=len(selected)>=min_structures and added>=min_informative,trajectories=len(trajectories),
        pairs=len(pairs),pair_counts=dict(Counter(p['category'] for p in pairs.values())),cases=statuses,root_questions=roots,
        verification=verify(fixtures,list(rows.values()),trajectories),training_overlap=False,
        limitations=['Teacher-selected evidence enrichment; not an unbiased random benchmark.',
                    'Correlated snapshots within structures; report per structure and selected-target coverage.',
                    'Still short endgames under the declared partner policy, not arbitrary-strategy transfer.'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    write_review(out)
    (out/'checksums.json').unlink()
    (out/'checksums.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.rglob('*') if p.is_file()},indent=2)+'\n')
    return summary


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--training-pack',type=Path,default=Path('new/local_data/social_cases_v2'))
    p.add_argument('--original-pack',type=Path,default=Path('new/local_data/social_generalization_v1'))
    p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.training_pack,a.original_pack,a.output_dir),indent=2))
