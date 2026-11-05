"""Audit existing native decision fixtures; never relabel or modify a corpus."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import time

from training.social_mixed.frozen.training.b_sft.decision_corpus import Fixture, digest
from training.social_mixed.frozen.benac_p.endgame import Node, SearchLimit
from training.social_mixed.frozen.benac_p.endgame_partner import InformationStateRequired, InconsistentPartnerHistory

TOL = 1e-9


def action_audit(rows):
    """All rows must use the same native legal-action ordering."""
    if not rows or not rows[0] or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError('Expected nonempty aligned Q rows')
    opt = [{i for i, v in enumerate(r) if max(r)-v <= TOL} for r in rows]
    common = sorted(set.intersection(*opt))
    regret = [max(max(r)-r[a] for r in rows) for a in range(len(rows[0]))]
    return dict(common_optimal_actions=common, optimal_actions_by_condition=[sorted(o) for o in opt],
                best_fixed_action_worst_regret=min(regret),
                best_fixed_actions=[i for i, v in enumerate(regret) if v-min(regret) <= TOL],
                disjoint_optimal_pair=next(([i,j] for i in range(len(opt)) for j in range(i+1,len(opt))
                                            if not opt[i] & opt[j]), None),
                value_sensitive=any(abs(rows[i][a]-rows[0][a]) > TOL
                                    for i in range(1,len(rows)) for a in range(len(rows[0]))))


def structure_id(raw):
    game = deepcopy(raw['game'])
    for k in ('seed', 'metadata', 'private_preferences'):
        game.pop(k, None)
    return 'structure-' + digest(game)[:24]


def audit(certificate, max_nodes):
    raw = certificate['fixture']; start = time.monotonic()
    result = dict(id=raw['id'], source_id=certificate['source_id'], split=certificate['split'],
                  structure_id=structure_id(raw), players=raw['game']['n_players'], status='ok',
                  coverage=[], teacher_scope='Conditional single-hidden-preference reference; not arbitrary unknown partners.')
    try:
        if any(not g.get('binary', True) for g in raw['game']['goals']):
            raise ValueError('Linear goals unsupported by Fixture; refusing conversion')
        f = Fixture(raw, max_nodes)
        q = f.search.q_values(f.root)
        actions = [a.to_dict() for a,_ in q]
        rows=[]; conditions=[]; skipped=0
        for w in f.root.worlds:
            node=Node(f.root.state,(w,),f.root.pending)
            try:
                typed=f.search.q_values(node)
            except InconsistentPartnerHistory:
                skipped+=1; continue
            if [a.to_dict() for a,_ in typed] != actions:
                raise ValueError('Conditional legal actions are not aligned')
            rows.append([v for _,v in typed]); conditions.append(f.support(node))
        result.update(actions=actions, root_q=[v for _,v in q], root_support=f.support(f.root),
                      conditional_supports=conditions, conditional_q=rows, skipped_conditions=skipped)
        if rows:
            result['fixed_action_audit']=action_audit(rows)
        result['conditional_audit_complete']=bool(rows) and not skipped
        # Singleton-world tests are counterfactual information conditions, not
        # proof that current observation distinguishes these worlds.
        result['observable_switch_witness']=False
        if len(rows)>1 and not skipped:
            result['coverage'].append('common_optimum_control' if result['fixed_action_audit']['common_optimal_actions']
                                      else 'conditional_no_common_optimum')
        best=max(v for _,v in q); info=[]; maintain=update=False
        for index,(a,v) in enumerate(q):
            branches=f.window_step(f.root,a)
            supports=[f.support(b.node) for b in branches]
            live=[b for b in branches if not b.node.state.is_terminal]
            for b in live:
                if f.support(b.node)==f.support(f.root):maintain=True
                else:update=True
            if live and len(live)==len(branches) and any(s!=f.support(f.root) for s in supports):
                info.append(dict(action_index=index, q=v, regret=best-v,
                                 posterior_supports=supports,
                                 branch_weights=[b.weight for b in branches]))
        result['informative_actions_with_later_decision']=info
        if maintain:result['coverage'].append('maintain_before_action')
        if update:result['coverage'].append('update_before_action')
        if any(x['regret']>TOL for x in info):result['coverage'].append('costly_information_control')
        if any(x['regret']<=TOL for x in info):result['coverage'].append('optimal_informative_action')
        result['positive_value_of_information_proven']=False
        result['favored_within_set_coverage']=False
        result['own_goal_counterfactual_coverage']=False
    except (SearchLimit, InformationStateRequired, ValueError) as exc:
        result.update(status='unavailable', reason=f'{type(exc).__name__}: {exc}', coverage=[])
    result['seconds']=round(time.monotonic()-start,3)
    return result


def shortlist(rows, limit):
    """Greedy coverage proposal; never promote held-out structures into training."""
    groups=defaultdict(list)
    for r in rows:groups[r['structure_id']].append(r)
    pool=[]
    for key,rs in groups.items():
        splits={r['split'] for r in rs}
        if not splits <= {'train','development'}:continue
        ok=[r for r in rs if r['status']=='ok']
        if ok:pool.append(dict(structure_id=key, splits=sorted(splits),
                               ids=[r['id'] for r in ok], players=ok[0]['players'],
                               coverage=sorted({c for r in ok for c in r['coverage']})))
    chosen=[]; covered=set()
    while pool and len(chosen)<limit:
        # Coverage includes player count; fill only where a structure adds value.
        def features(r):return set(r['coverage'])|{f"players_{r['players']}"}
        pool.sort(key=lambda r:(-len(features(r)-covered),r['structure_id']))
        best=pool.pop(0)
        if not features(best)-covered:break
        best['new_coverage']=sorted(features(best)-covered)
        chosen.append(best);covered|=features(best)
    return chosen


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus',type=Path,nargs='+',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--max-nodes',type=int,default=3000)
    p.add_argument('--seed-limit',type=int,default=8)
    args=p.parse_args(argv)
    if args.max_nodes<1 or args.seed_limit<1:p.error('Budgets must be positive')
    if args.output_dir.exists():p.error('Use a new output directory')
    args.output_dir.mkdir(parents=True)
    rows=[]; seen={}
    with (args.output_dir/'decisions.jsonl').open('w') as out:
        for corpus in args.corpus:
            for line in (corpus/'certificates.jsonl').read_text().splitlines():
                c=json.loads(line); key=(structure_id(c['fixture']),c['root_decision_id'])
                if key in seen:
                    if seen[key]!=c['split']:raise ValueError('Duplicate decision crosses splits')
                    continue
                seen[key]=c['split'];r=audit(c,args.max_nodes);r['corpus']=str(corpus)
                rows.append(r);out.write(json.dumps(r,ensure_ascii=False)+'\n');out.flush()
                print(json.dumps({k:r[k] for k in ('id','status','coverage','seconds')}),flush=True)
    chosen=shortlist(rows,args.seed_limit)
    summary=dict(decisions=len(rows),structures=len({r['structure_id'] for r in rows}),
                 statuses=dict(Counter(r['status'] for r in rows)),
                 total_audit_seconds=round(sum(r['seconds'] for r in rows),3),
                 complete_multicondition_decisions=sum(r.get('conditional_audit_complete',False) and len(r.get('conditional_q',[]))>1 for r in rows),
                 coverage_structures={c:len({r['structure_id'] for r in rows if c in r['coverage']})
                                      for c in sorted({c for r in rows for c in r['coverage']})},
                 proposed_seed_structures=chosen, training_ready=False,
                 missing=['observable evidence requiring different optimal actions',
                          'positive net value of information certificate',
                          'favored within a multi-element set', 'own-goal counterfactuals'],
                 scope='Exact serialized structure grouping, not isomorphism deduplication. Development selections are design seeds, not held-out evidence. Conditional Q varies information assumptions, not necessarily reachable observations.')
    (args.output_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    lines=['# 游戏结构覆盖与捷径审计','',f"{summary['structures']} 个结构，{len(rows)} 个决策点。仅作开发选种，training_ready=false。",'',
           '共同最优只表示当前节点、所列参考条件下存在固定动作；不证明整局可用固定策略。无共同最优也不证明当前证据能区分条件。', '',
           '| 决策点 | split | 人数 | 状态 | 共同最优索引 | 固定动作最坏 regret 下界 | 覆盖 |','|---|---|---:|---|---|---:|---|']
    for r in rows:
        a=r.get('fixed_action_audit',{}) if r.get('conditional_audit_complete') and len(r.get('conditional_q',[]))>1 else {}
        lines.append(f"| {r['id']} | {r['split']} | {r['players']} | {r['status']} | {a.get('common_optimal_actions','未知')} | {a.get('best_fixed_action_worst_regret','未知')} | {', '.join(r['coverage'])} |")
    lines+=['','## 建议保留的设计种子','', '仅从 train/development 提议；validation/test/OOD 不进入训练候选。同一结构只选一次，覆盖增益为零时不凑满八局。','']
    for r in chosen:lines.append(f"- {r['structure_id']}（{','.join(r['splits'])}）：{', '.join(r['ids'])}；新增 {', '.join(r['new_coverage'])}")
    lines+=['','## 尚缺的证据','']+['- '+x for x in summary['missing']]
    lines+=['','局部 Q 与耗时、全部合法动作、条件支持集、信息行动详见 decisions.jsonl。结构分组尚不识别重命名同构；最优信息行动不等于信息本身具有正净价值。']
    (args.output_dir/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
